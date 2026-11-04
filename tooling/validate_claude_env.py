#!/usr/bin/env python3
"""Validate the .claude engineering environment.

Checks that every skill and subagent has parseable YAML frontmatter with the
fields Claude Code needs, that names are unique and match their filename, and
that no file is a hollow placeholder.

Exit code 0 only if every check passes.
"""
from __future__ import annotations

import json
import pathlib
import re
import sys

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
CLAUDE = ROOT / ".claude"
errors: list[str] = []
warnings: list[str] = []


def split_frontmatter(text: str) -> tuple[dict, str]:
    if not text.startswith("---"):
        raise ValueError("no frontmatter")
    parts = text.split("---", 2)
    if len(parts) < 3:
        raise ValueError("unterminated frontmatter")
    return yaml.safe_load(parts[1]) or {}, parts[2].strip()


def check_skills() -> None:
    skills_dir = CLAUDE / "skills"
    dirs = sorted(p for p in skills_dir.iterdir() if p.is_dir())
    print(f"skills found: {len(dirs)}")
    seen: set[str] = set()
    for d in dirs:
        skill = d / "SKILL.md"
        if not skill.exists():
            errors.append(f"{d.name}: missing SKILL.md")
            continue
        try:
            meta, body = split_frontmatter(skill.read_text())
        except Exception as exc:
            errors.append(f"{d.name}: {exc}")
            continue
        name = meta.get("name")
        desc = meta.get("description")
        if not name:
            errors.append(f"{d.name}: frontmatter missing 'name'")
        elif name != d.name:
            errors.append(f"{d.name}: name '{name}' != directory name")
        elif name in seen:
            errors.append(f"{d.name}: duplicate skill name")
        else:
            seen.add(name)
        if not desc or len(str(desc)) < 60:
            errors.append(f"{d.name}: description missing or too short")
        if len(body) < 700:
            errors.append(f"{d.name}: body too thin ({len(body)} chars)")
        if body.count("##") < 2:
            errors.append(f"{d.name}: needs at least two sections")
        code_blocks = body.count("```")
        print(f"  {d.name:<38} desc={len(str(desc)):>4}c body={len(body):>5}c "
              f"sections={body.count('##'):>2} codefences={code_blocks}")


def check_agents() -> None:
    agents_dir = CLAUDE / "agents"
    files = sorted(agents_dir.glob("*.md"))
    print(f"\nsubagents found: {len(files)}")
    seen: set[str] = set()
    for f in files:
        try:
            meta, body = split_frontmatter(f.read_text())
        except Exception as exc:
            errors.append(f"{f.name}: {exc}")
            continue
        name = meta.get("name")
        desc = meta.get("description")
        tools = meta.get("tools")
        if not name:
            errors.append(f"{f.name}: missing 'name'")
        elif name != f.stem:
            errors.append(f"{f.name}: name '{name}' != filename")
        elif name in seen:
            errors.append(f"{f.name}: duplicate agent name")
        else:
            seen.add(name)
        if not desc or len(str(desc)) < 40:
            errors.append(f"{f.name}: description missing or too short")
        if not tools:
            errors.append(f"{f.name}: missing 'tools' permission list")
        for required in ("**Role.**", "**Scope", "**Required skills.**",
                         "**Deliverables.**", "**Testing responsibility.**"):
            if required not in body:
                errors.append(f"{f.name}: missing section {required}")
        if "Refuse and escalate" not in body:
            warnings.append(f"{f.name}: no escalation clause")
        print(f"  {name:<34} tools={str(tools)[:28]:<30} body={len(body):>5}c")


def check_rules() -> None:
    rules = sorted((CLAUDE / "rules").glob("*.md"))
    print(f"\nrules found: {len(rules)}")
    for r in rules:
        text = r.read_text()
        if not re.match(r"^# Rule: ", text):
            errors.append(f"rules/{r.name}: must start with '# Rule: '")
        if len(text) < 200:
            errors.append(f"rules/{r.name}: too thin")
        print(f"  {r.name:<34} {len(text):>5}c")


def check_settings_and_hooks() -> None:
    settings_path = CLAUDE / "settings.json"
    settings = json.loads(settings_path.read_text())
    perms = settings["permissions"]
    print(f"\nsettings.json: {len(perms['allow'])} allow, {len(perms['ask'])} ask, "
          f"{len(perms['deny'])} deny")
    for bad in ("Read(.env)",):
        if bad not in perms["deny"]:
            errors.append("settings.json: .env must be denied for Read")
    hooks = settings.get("hooks", {})
    referenced: set[str] = set()
    for event, matchers in hooks.items():
        for m in matchers:
            for h in m.get("hooks", []):
                cmd = h.get("command", "")
                m2 = re.search(r"\.claude/hooks/([\w.-]+)", cmd)
                if m2:
                    referenced.add(m2.group(1))
    print(f"hooks referenced: {sorted(referenced)}")
    for name in sorted(referenced):
        p = CLAUDE / "hooks" / name
        if not p.exists():
            errors.append(f"settings.json references missing hook {name}")
        elif not p.stat().st_mode & 0o111:
            errors.append(f"hook {name} is not executable")
    if not (CLAUDE.parent / "CLAUDE.md").exists():
        errors.append("root CLAUDE.md missing")


def main() -> int:
    check_skills()
    check_agents()
    check_rules()
    check_settings_and_hooks()

    print()
    for w in warnings:
        print(f"WARN  {w}")
    for e in errors:
        print(f"ERROR {e}")
    print()
    if errors:
        print(f"FAILED with {len(errors)} error(s)")
        return 1
    print("OK: claude environment valid "
          f"({len(list((CLAUDE/'skills').iterdir()))} skills, "
          f"{len(list((CLAUDE/'agents').glob('*.md')))} subagents)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
