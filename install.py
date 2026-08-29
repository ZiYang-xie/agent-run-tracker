#!/usr/bin/env python3
from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
HOME = Path.home()

RUNTIME_DST = HOME / ".codex" / "agent-run-tracker"
SKILL_DST = HOME / ".agents" / "skills" / "agent-run-tracker"
HOOKS_PATH = HOME / ".codex" / "hooks.json"
TRACKER_HOME = HOME / ".agent-tracker"

PROMPT_CMD = f'python3 "{RUNTIME_DST / "track_prompt.py"}"'
STOP_CMD = f'python3 "{RUNTIME_DST / "track_stop.py"}"'


def load_hooks():
    if not HOOKS_PATH.exists():
        return {"description": "User Codex hooks.", "hooks": {}}
    try:
        obj = json.loads(HOOKS_PATH.read_text(encoding="utf-8"))
        if not isinstance(obj, dict):
            raise ValueError("hooks.json must contain one JSON object")
        obj.setdefault("hooks", {})
        return obj
    except Exception as e:
        raise SystemExit(f"Cannot parse {HOOKS_PATH}: {e}")


def handler_exists(groups, command):
    for group in groups:
        if not isinstance(group, dict):
            continue
        for hook in group.get("hooks", []):
            if isinstance(hook, dict) and hook.get("command") == command:
                return True
    return False


def add_handler(obj, event, command, status=None):
    groups = obj.setdefault("hooks", {}).setdefault(event, [])
    if handler_exists(groups, command):
        return
    h = {"type": "command", "command": command, "timeout": 15}
    if status:
        h["statusMessage"] = status
    groups.append({"hooks": [h]})


def main():
    RUNTIME_DST.parent.mkdir(parents=True, exist_ok=True)
    SKILL_DST.parent.mkdir(parents=True, exist_ok=True)
    TRACKER_HOME.mkdir(parents=True, exist_ok=True)

    if RUNTIME_DST.exists():
        shutil.rmtree(RUNTIME_DST)
    if SKILL_DST.exists():
        shutil.rmtree(SKILL_DST)

    shutil.copytree(HERE / "runtime", RUNTIME_DST)
    shutil.copytree(HERE / "skill", SKILL_DST)

    cfg = TRACKER_HOME / "config.json"
    if not cfg.exists():
        shutil.copy2(HERE / "config.example.json", cfg)

    hooks = load_hooks()
    if HOOKS_PATH.exists():
        backup = HOOKS_PATH.with_name(f"hooks.json.bak.{int(time.time())}")
        shutil.copy2(HOOKS_PATH, backup)
        print(f"Backed up hooks to {backup}")

    add_handler(hooks, "UserPromptSubmit", PROMPT_CMD, "Starting agent run tracker")
    add_handler(hooks, "Stop", STOP_CMD, "Scoring agent run")

    HOOKS_PATH.parent.mkdir(parents=True, exist_ok=True)
    HOOKS_PATH.write_text(json.dumps(hooks, indent=2) + "\n", encoding="utf-8")

    print("Installed Agent Run Tracker.")
    print(f"Skill:   {SKILL_DST}")
    print(f"Runtime: {RUNTIME_DST}")
    print(f"Hooks:   {HOOKS_PATH}")
    print(f"Data:    {TRACKER_HOME}")
    print()
    print("Restart Codex, then review/trust the new hooks when prompted.")


if __name__ == "__main__":
    main()
