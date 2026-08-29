from __future__ import annotations

import json
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

TRACKER_MARKER = "[AGENT_TRACKER_FINALIZE]"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def tracker_home() -> Path:
    raw = os.environ.get("AGENT_TRACKER_HOME", "~/.agent-tracker")
    p = Path(os.path.expanduser(raw))
    p.mkdir(parents=True, exist_ok=True)
    (p / "pending").mkdir(exist_ok=True)
    (p / "finalizers").mkdir(exist_ok=True)
    return p


def load_config() -> dict[str, Any]:
    path = tracker_home() / "config.json"
    cfg = {
        "enabled": True,
        "store_prompt_chars": 4000,
        "database_path": "~/.agent-tracker/tracker.sqlite3",
        "jsonl_path": "~/.agent-tracker/runs.jsonl",
        "require_evidence_for_accept": True,
    }
    if path.exists():
        try:
            user = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(user, dict):
                cfg.update(user)
        except Exception:
            pass
    return cfg


def expand_path(raw: str) -> Path:
    return Path(os.path.expandvars(os.path.expanduser(raw)))


def safe_id(value: str | None) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value or "unknown")


def pending_path(session_id: str, turn_id: str) -> Path:
    return tracker_home() / "pending" / f"{safe_id(session_id)}--{safe_id(turn_id)}.json"


def finalizer_map_path(session_id: str, turn_id: str) -> Path:
    return tracker_home() / "finalizers" / f"{safe_id(session_id)}--{safe_id(turn_id)}.json"


def read_json(path: Path) -> dict[str, Any] | None:
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
        return obj if isinstance(obj, dict) else None
    except Exception:
        return None


def write_json_atomic(path: Path, obj: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def run_git(cwd: str, *args: str) -> str | None:
    try:
        p = subprocess.run(["git", "-C", cwd, *args], capture_output=True, text=True, timeout=3)
        if p.returncode == 0:
            return p.stdout.strip()
    except Exception:
        pass
    return None


def git_snapshot(cwd: str) -> dict[str, Any]:
    return {
        "root": run_git(cwd, "rev-parse", "--show-toplevel"),
        "sha": run_git(cwd, "rev-parse", "HEAD"),
        "branch": run_git(cwd, "branch", "--show-current"),
    }


def _usage_from_obj(obj: dict[str, Any]) -> dict[str, int] | None:
    if obj.get("type") != "event_msg":
        return None
    payload = obj.get("payload")
    if not isinstance(payload, dict) or payload.get("type") != "token_count":
        return None
    info = payload.get("info")
    if not isinstance(info, dict):
        return None
    usage = info.get("total_token_usage") or info.get("last_token_usage")
    if not isinstance(usage, dict):
        return None
    keys = ["input_tokens", "cached_input_tokens", "cache_write_input_tokens", "output_tokens", "reasoning_output_tokens", "total_tokens"]
    out: dict[str, int] = {}
    for k in keys:
        try:
            out[k] = int(usage.get(k, 0) or 0)
        except Exception:
            out[k] = 0
    if not out.get("total_tokens"):
        out["total_tokens"] = out.get("input_tokens", 0) + out.get("output_tokens", 0)
    return out


def latest_token_snapshot(transcript_path: str | None) -> dict[str, int] | None:
    if not transcript_path:
        return None
    p = Path(transcript_path)
    if not p.exists() or not p.is_file():
        return None
    try:
        size = p.stat().st_size
        n = min(size, 8 * 1024 * 1024)
        with p.open("rb") as f:
            if size > n:
                f.seek(size - n)
                f.readline()
            data = f.read()
        for raw in reversed(data.splitlines()):
            try:
                obj = json.loads(raw)
            except Exception:
                continue
            usage = _usage_from_obj(obj)
            if usage is not None:
                return usage
    except Exception:
        pass
    latest = None
    try:
        with p.open("r", encoding="utf-8", errors="replace") as f:
            for line in f:
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                usage = _usage_from_obj(obj)
                if usage is not None:
                    latest = usage
    except Exception:
        return None
    return latest


def usage_delta(end: dict[str, int] | None, start: dict[str, int] | None) -> dict[str, int] | None:
    if end is None or start is None:
        return None
    keys = set(end) | set(start)
    d = {k: max(0, int(end.get(k, 0)) - int(start.get(k, 0))) for k in keys}
    if not d.get("total_tokens"):
        d["total_tokens"] = d.get("input_tokens", 0) + d.get("output_tokens", 0)
    d["uncached_input_tokens"] = max(0, d.get("input_tokens", 0) - d.get("cached_input_tokens", 0))
    return d


def parse_shortstat(text: str | None) -> tuple[int | None, int | None, int | None]:
    if not text:
        return (0, 0, 0)
    files = insertions = deletions = 0
    m = re.search(r"(\d+)\s+files?\s+changed", text)
    if m:
        files = int(m.group(1))
    m = re.search(r"(\d+)\s+insertions?\(\+\)", text)
    if m:
        insertions = int(m.group(1))
    m = re.search(r"(\d+)\s+deletions?\(-\)", text)
    if m:
        deletions = int(m.group(1))
    return files, insertions, deletions


def git_diff_stats(cwd: str, start_sha: str | None) -> tuple[int | None, int | None, int | None]:
    if not start_sha:
        return (None, None, None)
    return parse_shortstat(run_git(cwd, "diff", "--shortstat", start_sha))


def project_name(cwd: str) -> str:
    root = run_git(cwd, "rev-parse", "--show-toplevel")
    return Path(root or cwd).name
