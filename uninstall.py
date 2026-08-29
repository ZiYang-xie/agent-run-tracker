#!/usr/bin/env python3
from __future__ import annotations

import json
import shutil
from pathlib import Path

HOME = Path.home()
RUNTIME_DST = HOME / ".codex" / "agent-run-tracker"
SKILL_DST = HOME / ".agents" / "skills" / "agent-run-tracker"
HOOKS_PATH = HOME / ".codex" / "hooks.json"


def main():
    if HOOKS_PATH.exists():
        try:
            obj = json.loads(HOOKS_PATH.read_text(encoding="utf-8"))
            hooks = obj.get("hooks", {})
            for event in ("UserPromptSubmit", "Stop"):
                groups = hooks.get(event, [])
                new_groups = []
                for group in groups:
                    hs = []
                    for h in group.get("hooks", []):
                        cmd = str(h.get("command", ""))
                        if "agent-run-tracker/track_" not in cmd:
                            hs.append(h)
                    if hs:
                        ng = dict(group)
                        ng["hooks"] = hs
                        new_groups.append(ng)
                hooks[event] = new_groups
            HOOKS_PATH.write_text(json.dumps(obj, indent=2) + "\n", encoding="utf-8")
        except Exception as e:
            print(f"Warning: could not edit hooks.json: {e}")

    if RUNTIME_DST.exists():
        shutil.rmtree(RUNTIME_DST)
    if SKILL_DST.exists():
        shutil.rmtree(SKILL_DST)

    print("Removed tracker runtime, skill, and hook handlers.")
    print("Kept ~/.agent-tracker data. Delete it manually if you want to erase history.")


if __name__ == "__main__":
    main()
