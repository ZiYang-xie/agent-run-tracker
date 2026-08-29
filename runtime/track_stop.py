#!/usr/bin/env python3
from __future__ import annotations

import json
import sys

from common import finalizer_map_path, load_config, now_iso, pending_path, read_json, write_json_atomic


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0
    cfg = load_config()
    if not cfg.get("enabled", True):
        return 0
    session_id = str(payload.get("session_id") or "")
    turn_id = str(payload.get("turn_id") or "")

    if read_json(finalizer_map_path(session_id, turn_id)):
        return 0
    pp = pending_path(session_id, turn_id)
    pending = read_json(pp)
    if not pending or pending.get("finalize_requested_at"):
        return 0

    pending["finalize_requested_at"] = now_iso()
    pending["last_assistant_message"] = payload.get("last_assistant_message")
    write_json_atomic(pp, pending)

    reason = (
        f"[AGENT_TRACKER_FINALIZE] source_turn_id={turn_id} session_id={session_id}\n"
        "Use the $agent-run-tracker skill now. Evaluate the just-finished user task from the conversation and objective evidence, then persist exactly one tracker action. Do not treat this tracker prompt as the task. Do not continue implementation unless a tiny verification step is required for a reliable verdict."
    )
    print(json.dumps({"decision": "block", "reason": reason}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
