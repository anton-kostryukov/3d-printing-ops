"""Bounded file snapshots and inert archive extraction shared with the remote worker."""

from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import stat
import tarfile
from pathlib import Path, PurePosixPath

MAX_ARCHIVE_BYTES = 32 * 1024 * 1024
MAX_TREE_BYTES = 64 * 1024 * 1024
MAX_ENTRIES = 10000


def ignored(parts):
    return any(part == ".git" or part.startswith("._") for part in parts)


def manifest(root):
    root = Path(root)
    if not root.is_dir():
        raise ValueError(f"config directory does not exist: {root}")
    entries = []
    total = 0
    for directory, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = sorted(name for name in dirnames if not ignored((name,)))
        names = sorted(
            filenames + [name for name in dirnames if (Path(directory) / name).is_symlink()]
        )
        for name in names:
            path = Path(directory) / name
            relative = path.relative_to(root)
            if ignored(relative.parts):
                continue
            info = path.lstat()
            if stat.S_ISLNK(info.st_mode):
                link = os.readlink(path)
                data = link.encode("utf-8")
                kind = "symlink"
                digest = hashlib.sha256(data).hexdigest()
                size = len(data)
            elif stat.S_ISREG(info.st_mode):
                size = info.st_size
                total += size
                if total > MAX_TREE_BYTES:
                    raise ValueError("config exceeds the 64 MiB snapshot limit")
                hasher = hashlib.sha256()
                with path.open("rb") as handle:
                    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                        hasher.update(chunk)
                digest = hasher.hexdigest()
                kind = "file"
            else:
                raise ValueError(f"unsupported config file type: {relative}")
            entry = {"path": relative.as_posix(), "type": kind, "size": size, "sha256": digest}
            if kind == "symlink":
                entry["target"] = link
            else:
                entry["mode"] = info.st_mode & 0o777
            entries.append(entry)
            if len(entries) > MAX_ENTRIES:
                raise ValueError("config exceeds the 10000-file snapshot limit")
    entries.sort(key=lambda item: item["path"])
    return {"root": str(root), "files": entries}


def fingerprint(snapshot):
    data = json.dumps(snapshot["files"], sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(data.encode()).hexdigest()


def create_archive(root, expanded=False):
    root = Path(root)
    output = io.BytesIO()
    total = 0
    count = 0
    with tarfile.open(fileobj=output, mode="w:gz", dereference=expanded) as archive:
        # Walk explicitly: following symlink directories recursively can form cycles.
        def visit(directory, relative, ancestors):
            nonlocal total, count
            real = directory.resolve()
            if real in ancestors:
                raise ValueError(f"recursive config symlink: {relative}")
            for path in sorted(directory.iterdir()):
                name = relative / path.name
                if ignored(name.parts):
                    continue
                count += 1
                if count > MAX_ENTRIES:
                    raise ValueError("config exceeds the 10000-entry archive limit")
                if path.is_symlink() and not expanded:
                    archive.add(path, arcname=name.as_posix(), recursive=False)
                elif path.is_dir():
                    archive.add(path, arcname=name.as_posix(), recursive=False)
                    visit(path, name, ancestors | {real})
                elif path.is_file():
                    total += path.stat().st_size
                    if total > MAX_TREE_BYTES:
                        raise ValueError("config exceeds the 64 MiB snapshot limit")
                    archive.add(path, arcname=name.as_posix(), recursive=False)
                else:
                    raise ValueError(f"unsupported or dangling expanded config file: {name}")

        visit(root, Path(), set())
    data = output.getvalue()
    if len(data) > MAX_ARCHIVE_BYTES:
        raise ValueError("compressed config exceeds the 32 MiB archive limit")
    return data


def extract_archive(payload, target):
    """Preserve links as inert entries; never write through an archived link."""
    if len(payload) > MAX_ARCHIVE_BYTES:
        raise ValueError("compressed config exceeds the 32 MiB archive limit")
    target = Path(target)
    target.mkdir(parents=True, exist_ok=True)
    if any(target.iterdir()):
        raise ValueError("archive extraction requires an empty target")
    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as archive:
        members = []
        seen = set()
        size = 0
        for member in archive:
            if len(members) >= MAX_ENTRIES:
                raise ValueError("archive exceeds the 10000-entry limit")
            path = PurePosixPath(member.name)
            if path.is_absolute() or ".." in path.parts:
                raise ValueError(f"unsafe path in config archive: {member.name}")
            if not path.parts:
                continue
            if path in seen:
                raise ValueError(f"duplicate path in config archive: {member.name}")
            if ignored(path.parts):
                continue
            if not (member.isdir() or member.isfile() or member.issym()):
                raise ValueError(f"unsupported archive member: {member.name}")
            seen.add(path)
            members.append((path, member))
            size += member.size
            if size > MAX_TREE_BYTES:
                raise ValueError("archive exceeds the 64 MiB extracted size limit")
        links = {path for path, member in members if member.issym()}
        for path, _member in members:
            if any(parent in links for parent in path.parents):
                raise ValueError(f"archive member traverses an archived symlink: {path}")
        # Links are created last, including absolute links used by Moonraker modules.
        for path, member in members:
            if member.issym():
                continue
            destination = target.joinpath(*path.parts)
            if member.isdir():
                destination.mkdir(parents=True, exist_ok=True)
            else:
                destination.parent.mkdir(parents=True, exist_ok=True)
                with archive.extractfile(member) as source, destination.open("xb") as handle:
                    shutil.copyfileobj(source, handle)
                destination.chmod(member.mode & 0o777)
        for path, member in members:
            if member.issym():
                destination = target.joinpath(*path.parts)
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.symlink_to(member.linkname)
        for path, member in reversed(members):
            if member.isdir():
                target.joinpath(*path.parts).chmod(member.mode & 0o777)
