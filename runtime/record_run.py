#!/usr/bin/env python3
from __future__ import annotations

import json
import sqlite3
import sys
import uuid
from datetime import datetime, timezone
from typing import Any

from common import expand_path, git_diff_stats, git_snapshot, latest_token_snapshot, load_config, now_iso, pending_path, project_name, read_json, usage_delta

OUTCOMES = {"accepted", "partial", "useful_negative", "rejected", "blocked", "unknown"}
BASES = {"explicit_human", "inferred_human", "objective_evidence", "none"}
HUMAN = {"positive", "negative", "mixed", "none"}
TASK_TYPES = {"implementation", "debug", "research", "benchmark", "refactor", "planning", "review", "infra", "other"}


def connect_db() -> sqlite3.Connection:
    cfg = load_config()
    path = expand_path(str(cfg["database_path"]))
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.execute("""
        CREATE TABLE IF NOT EXISTS runs (
          run_id TEXT PRIMARY KEY, session_id TEXT NOT NULL, turn_id TEXT NOT NULL,
          project TEXT, cwd TEXT, model TEXT, task_type TEXT, goal TEXT, outcome TEXT,
          acceptance_basis TEXT, confidence REAL, human_feedback TEXT, summary TEXT,
          next_step TEXT, started_at TEXT, work_ended_at TEXT, wall_seconds REAL,
          git_start_sha TEXT, git_end_sha TEXT, files_changed INTEGER, insertions INTEGER,
          deletions INTEGER, input_tokens INTEGER, cached_input_tokens INTEGER,
          uncached_input_tokens INTEGER, output_tokens INTEGER, reasoning_output_tokens INTEGER,
          total_tokens INTEGER, tracker_overhead_tokens INTEGER, prompt_excerpt TEXT,
          evidence_json TEXT, metrics_json TEXT, raw_json TEXT, created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        )
    """)
    con.execute("CREATE INDEX IF NOT EXISTS idx_runs_session ON runs(session_id, created_at)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_runs_project ON runs(project, created_at)")
    con.commit()
    return con


def parse_iso(s: str | None):
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except Exception:
        return None


def previous_run(con: sqlite3.Connection, session_id: str, exclude_turn: str | None = None):
    if exclude_turn:
        return con.execute("SELECT run_id, outcome, acceptance_basis, human_feedback FROM runs WHERE session_id=? AND turn_id<>? ORDER BY created_at DESC LIMIT 1", (session_id, exclude_turn)).fetchone()
    return con.execute("SELECT run_id, outcome, acceptance_basis, human_feedback FROM runs WHERE session_id=? ORDER BY created_at DESC LIMIT 1", (session_id,)).fetchone()


def apply_feedback_updates(con: sqlite3.Connection, session_id: str, turn_id: str, updates: list[dict[str, Any]]):
    for upd in updates:
        if not isinstance(upd, dict):
            continue
        target = upd.get("run_id")
        if not target and upd.get("target") == "previous":
            row = previous_run(con, session_id, exclude_turn=turn_id)
            target = row[0] if row else None
        if not target:
            continue
        fields, vals = [], []
        for key in ("outcome", "acceptance_basis", "human_feedback", "confidence", "summary"):
            if key not in upd or upd[key] is None:
                continue
            if key == "outcome" and upd[key] not in OUTCOMES:
                continue
            if key == "acceptance_basis" and upd[key] not in BASES:
                continue
            if key == "human_feedback" and upd[key] not in HUMAN:
                continue
            fields.append(f"{key}=?")
            vals.append(upd[key])
        if fields:
            fields.append("updated_at=?")
            vals.extend([now_iso(), target])
            con.execute(f"UPDATE runs SET {', '.join(fields)} WHERE run_id=?", vals)


def validate(d: dict[str, Any]) -> None:
    outcome = d.get("outcome", "unknown")
    basis = d.get("acceptance_basis", "none")
    human = d.get("human_feedback", "none")
    task_type = d.get("task_type", "other")
    if outcome not in OUTCOMES:
        raise ValueError(f"invalid outcome: {outcome}")
    if basis not in BASES:
        raise ValueError(f"invalid acceptance_basis: {basis}")
    if human not in HUMAN:
        raise ValueError(f"invalid human_feedback: {human}")
    if task_type not in TASK_TYPES:
        raise ValueError(f"invalid task_type: {task_type}")
    if outcome == "accepted" and basis == "none":
        raise ValueError("accepted requires explicit_human, inferred_human, or objective_evidence")


def append_jsonl(row: dict[str, Any]) -> None:
    path = expand_path(str(load_config()["jsonl_path"]))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def main() -> int:
    try:
        d = json.load(sys.stdin)
        if not isinstance(d, dict):
            raise ValueError("input must be one JSON object")
    except Exception as e:
        print(f"agent-run-tracker: invalid JSON: {e}", file=sys.stderr)
        return 2

    action = d.get("action", "create")
    session_id = str(d.get("session_id") or "")
    source_turn_id = str(d.get("source_turn_id") or "")
    if not session_id or not source_turn_id:
        print("agent-run-tracker: session_id and source_turn_id are required", file=sys.stderr)
        return 2

    con = connect_db()
    updates = d.get("feedback_updates") or []
    if isinstance(updates, list):
        apply_feedback_updates(con, session_id, source_turn_id, updates)

    if action == "feedback":
        target = d.get("target_run_id")
        if not target:
            row = previous_run(con, session_id, exclude_turn=source_turn_id)
            target = row[0] if row else None
        if target:
            apply_feedback_updates(con, session_id, source_turn_id, [{"run_id": target, "outcome": d.get("outcome"), "acceptance_basis": d.get("acceptance_basis"), "human_feedback": d.get("human_feedback"), "confidence": d.get("confidence"), "summary": d.get("summary")}])
            con.commit()
        print(json.dumps({"ok": True, "action": "feedback", "updated_run_id": target}))
        return 0

    try:
        validate(d)
    except Exception as e:
        print(f"agent-run-tracker: {e}", file=sys.stderr)
        return 2

    pending = read_json(pending_path(session_id, source_turn_id))
    if not pending:
        print("agent-run-tracker: pending run not found", file=sys.stderr)
        return 2

    cwd = str(pending.get("cwd") or "")
    transcript = pending.get("transcript_path")
    start_usage = pending.get("token_baseline")
    finalizer_baseline = pending.get("finalizer_baseline")
    current_usage = latest_token_snapshot(transcript)
    work_usage = usage_delta(finalizer_baseline or current_usage, start_usage)
    overhead_usage = usage_delta(current_usage, finalizer_baseline) if finalizer_baseline else None

    started = parse_iso(pending.get("started_at"))
    ended = parse_iso(pending.get("finalize_requested_at")) or datetime.now(timezone.utc)
    wall_seconds = max(0.0, (ended - started).total_seconds()) if started else None

    git_start = pending.get("git_start") or {}
    git_end = git_snapshot(cwd) if cwd else {}
    files_changed, insertions, deletions = git_diff_stats(cwd, git_start.get("sha")) if cwd else (None, None, None)

    run_id = str(d.get("run_id") or f"run_{uuid.uuid4().hex[:16]}")
    evidence = d.get("evidence") if isinstance(d.get("evidence"), list) else []
    metrics = d.get("metrics") if isinstance(d.get("metrics"), list) else []
    u = lambda name: work_usage.get(name) if work_usage else None

    row = {
        "run_id": run_id, "session_id": session_id, "turn_id": source_turn_id,
        "project": str(d.get("project") or (project_name(cwd) if cwd else "")),
        "cwd": cwd, "model": pending.get("model"), "task_type": d.get("task_type", "other"),
        "goal": str(d.get("goal") or ""), "outcome": d.get("outcome", "unknown"),
        "acceptance_basis": d.get("acceptance_basis", "none"),
        "confidence": float(d.get("confidence", 0.0) or 0.0),
        "human_feedback": d.get("human_feedback", "none"), "summary": str(d.get("summary") or ""),
        "next_step": str(d.get("next_step") or ""), "started_at": pending.get("started_at"),
        "work_ended_at": pending.get("finalize_requested_at"), "wall_seconds": wall_seconds,
        "git_start_sha": git_start.get("sha"), "git_end_sha": git_end.get("sha"),
        "files_changed": files_changed, "insertions": insertions, "deletions": deletions,
        "input_tokens": u("input_tokens"), "cached_input_tokens": u("cached_input_tokens"),
        "uncached_input_tokens": u("uncached_input_tokens"), "output_tokens": u("output_tokens"),
        "reasoning_output_tokens": u("reasoning_output_tokens"), "total_tokens": u("total_tokens"),
        "tracker_overhead_tokens": overhead_usage.get("total_tokens") if overhead_usage else None,
        "prompt_excerpt": pending.get("prompt_excerpt"),
        "evidence_json": json.dumps(evidence, ensure_ascii=False),
        "metrics_json": json.dumps(metrics, ensure_ascii=False),
        "raw_json": json.dumps(d, ensure_ascii=False), "created_at": now_iso(), "updated_at": now_iso(),
    }
    columns = list(row)
    con.execute(f"INSERT OR REPLACE INTO runs ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})", [row[c] for c in columns])
    con.commit()
    append_jsonl(row)
    print(json.dumps({"ok": True, "action": "create", "run_id": run_id, "outcome": row["outcome"], "total_tokens": row["total_tokens"], "tracker_overhead_tokens": row["tracker_overhead_tokens"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
