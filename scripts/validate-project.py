#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import subprocess
import sys
import tomllib
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parent.parent


def fail(message: str) -> None:
    print(f"validation error: {message}", file=sys.stderr)
    raise SystemExit(1)


version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
if not re.fullmatch(r"\d+\.\d+\.\d+", version):
    fail("VERSION must use semantic x.y.z form")

marketplace = json.loads((ROOT / "marketplace.json").read_text(encoding="utf-8"))
skills = marketplace.get("skills", [])
if len(skills) != 1 or skills[0].get("id") != "klipper-ops":
    fail("marketplace must currently expose exactly the klipper-ops skill")
if skills[0].get("version") != version:
    fail("marketplace skill version does not match VERSION")
if skills[0].get("source", {}).get("ref") != version:
    fail("marketplace source ref must equal VERSION")
if skills[0].get("path") != "skills/klipper-ops":
    fail("marketplace install path must point to the skill, not MCP")

skill_text = (ROOT / "skills/klipper-ops/SKILL.md").read_text(encoding="utf-8")
if f"Version: `{version}`" not in skill_text:
    fail("SKILL.md version does not match VERSION")
frontmatter = yaml.safe_load(skill_text.split("---", 2)[1])
if frontmatter.get("name") != "klipper-ops" or not frontmatter.get("description"):
    fail("skill frontmatter must provide a name and description")
if len(skill_text.splitlines()) > 150:
    fail("keep SKILL.md concise")
if any((ROOT / "skills/klipper-ops/scripts/klipper_ops_mcp").glob("*.py")):
    fail("runtime must live in the separate MCP package")

pyproject_path = ROOT / "mcp/klipper-ops-server/pyproject.toml"
with pyproject_path.open("rb") as handle:
    pyproject = tomllib.load(handle)
if pyproject["project"]["version"] != version:
    fail("MCP package version does not match VERSION")

init_text = (ROOT / "mcp/klipper-ops-server/src/klipper_ops_mcp/__init__.py").read_text(
    encoding="utf-8"
)
if f'__version__ = "{version}"' not in init_text:
    fail("MCP module version does not match VERSION")

readme = (ROOT / "README.md").read_text(encoding="utf-8")
if f"Current version: `{version}`." not in readme:
    fail("README current version does not match VERSION")

scripts = sorted((ROOT / "skills/klipper-ops/scripts").glob("*.sh"))
scripts.extend(sorted((ROOT / "skills/klipper-ops/scripts/lib").glob("*.sh")))
for script in scripts:
    if not script.stat().st_mode & 0o111:
        fail(f"shell script is not executable: {script.relative_to(ROOT)}")
scripts.extend(sorted((ROOT / "tests").glob("*.sh")))
for script in scripts:
    subprocess.run(["bash", "-n", str(script)], check=True)

interface = yaml.safe_load((ROOT / "skills/klipper-ops/agents/openai.yaml").read_text())
if not 25 <= len(interface["interface"]["short_description"]) <= 64:
    fail("agent short description must contain 25-64 characters")
if "$klipper-ops" not in interface["interface"]["default_prompt"]:
    fail("default prompt must explicitly reference the skill")

changelog = (ROOT / "CHANGELOG.md").read_text()
if not re.search(
    r"^## " + re.escape(version) + r" - \d{4}-\d{2}-\d{2}$", changelog, re.M
):
    fail("CHANGELOG.md must include a dated entry for VERSION")

print(f"project validation passed for {version}")
