#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import sys

from common import TRACKER_MARKER, finalizer_map_path, git_snapshot, latest_token_snapshot, load_config, now_iso, pending_path, read_json, write_json_atomic


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
    prompt = str(payload.get("prompt") or "")
    cwd = str(payload.get("cwd") or "")
    transcript = payload.get("transcript_path")

    if prompt.startswith(TRACKER_MARKER):
        m = re.search(r"source_turn_id=([^\s]+)", prompt)
        source_turn_id = m.group(1) if m else ""
        if source_turn_id:
            pp = pending_path(session_id, source_turn_id)
            pending = read_json(pp) or {}
            pending["finalizer_turn_id"] = turn_id
            pending["finalizer_started_at"] = now_iso()
            pending["finalizer_baseline"] = latest_token_snapshot(transcript)
            write_json_atomic(pp, pending)
            write_json_atomic(finalizer_map_path(session_id, turn_id), {"session_id": session_id, "finalizer_turn_id": turn_id, "source_turn_id": source_turn_id, "created_at": now_iso()})
        return 0

    keep = int(cfg.get("store_prompt_chars", 4000) or 0)
    pending = {
        "session_id": session_id,
        "turn_id": turn_id,
        "cwd": cwd,
        "model": payload.get("model"),
        "permission_mode": payload.get("permission_mode"),
        "transcript_path": transcript,
        "prompt_excerpt": prompt[:keep] if keep > 0 else "",
        "started_at": now_iso(),
        "token_baseline": latest_token_snapshot(transcript),
        "git_start": git_snapshot(cwd) if cwd else {},
    }
    write_json_atomic(pending_path(session_id, turn_id), pending)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
