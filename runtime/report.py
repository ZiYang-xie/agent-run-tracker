#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sqlite3
from datetime import datetime, timedelta, timezone

from common import expand_path, load_config


def fmt_tokens(n):
    if n is None:
        return "-"
    n = float(n)
    if n >= 1_000_000_000:
        return f"{n/1_000_000_000:.2f}B"
    if n >= 1_000_000:
        return f"{n/1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n/1_000:.1f}K"
    return str(int(n))


def fmt_duration(seconds):
    if seconds is None:
        return "-"
    seconds = max(0.0, float(seconds))
    if seconds < 60:
        return f"{seconds:.0f}s"
    if seconds < 3600:
        return f"{seconds/60:.1f}m"
    return f"{seconds/3600:.1f}h"


def parse_iso(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except Exception:
        return None


def interaction_metrics(con, where, params, days):
    records = con.execute(
        f"SELECT session_id, started_at, work_ended_at, wall_seconds FROM runs WHERE {where} ORDER BY session_id, started_at",
        params,
    ).fetchall()

    turnaround = [float(r[3]) for r in records if r[3] is not None]
    feedback_latencies = []
    previous_by_session = {}
    for session_id, started_at, work_ended_at, _ in records:
        started = parse_iso(started_at)
        previous_end = previous_by_session.get(session_id)
        if started and previous_end and started >= previous_end:
            feedback_latencies.append((started - previous_end).total_seconds())
        ended = parse_iso(work_ended_at)
        if ended:
            previous_by_session[session_id] = ended

    return {
        "avg_agent_turnaround": sum(turnaround) / len(turnaround) if turnaround else None,
        "median_agent_turnaround": sorted(turnaround)[len(turnaround) // 2] if turnaround else None,
        "avg_human_feedback_latency": sum(feedback_latencies) / len(feedback_latencies) if feedback_latencies else None,
        "feedback_cycles_per_day": len(records) / max(days, 1),
        "feedback_latency_samples": len(feedback_latencies),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--project")
    args = ap.parse_args()

    path = expand_path(str(load_config()["database_path"]))
    if not path.exists():
        print("No tracker database yet.")
        return

    since = (datetime.now(timezone.utc) - timedelta(days=args.days)).isoformat()
    con = sqlite3.connect(path)
    where = "created_at >= ?"
    params = [since]
    if args.project:
        where += " AND project = ?"
        params.append(args.project)

    rows = con.execute(f"""
        SELECT project, COUNT(*) AS runs, COALESCE(SUM(total_tokens),0) AS tokens,
               COALESCE(SUM(tracker_overhead_tokens),0) AS overhead,
               SUM(CASE WHEN outcome='accepted' THEN 1 ELSE 0 END) AS accepted,
               SUM(CASE WHEN outcome='partial' THEN 1 ELSE 0 END) AS partial,
               SUM(CASE WHEN outcome='useful_negative' THEN 1 ELSE 0 END) AS useful_negative,
               SUM(CASE WHEN outcome='rejected' THEN 1 ELSE 0 END) AS rejected,
               SUM(CASE WHEN acceptance_basis='explicit_human' THEN 1 ELSE 0 END) AS human_confirmed,
               COALESCE(SUM(CASE WHEN outcome='rejected' THEN total_tokens ELSE 0 END),0) AS waste_tokens
        FROM runs WHERE {where} GROUP BY project ORDER BY tokens DESC
    """, params).fetchall()

    total_tokens = sum(r[2] or 0 for r in rows)
    total_overhead = sum(r[3] or 0 for r in rows)
    total_runs = sum(r[1] or 0 for r in rows)
    total_waste = sum(r[9] or 0 for r in rows)
    interaction = interaction_metrics(con, where, params, args.days)

    print(f"Agent Run Tracker · last {args.days} days")
    print(f"Work tokens: {fmt_tokens(total_tokens)} | Tracker overhead: {fmt_tokens(total_overhead)} | Runs: {total_runs}")
    if total_tokens:
        print(f"Strict waste rate (rejected only): {100*total_waste/total_tokens:.1f}%")
    print(
        "Interaction efficiency: "
        f"agent turnaround {fmt_duration(interaction['avg_agent_turnaround'])} avg | "
        f"human feedback latency {fmt_duration(interaction['avg_human_feedback_latency'])} avg | "
        f"feedback cycles/day {interaction['feedback_cycles_per_day']:.1f}"
    )
    if interaction["feedback_latency_samples"] == 0:
        print("Human feedback latency: no consecutive same-session run pairs in this window.")
    print()
    print("| Project | Tokens | Runs | Accepted | Partial | Useful neg. | Rejected | Human confirmed | Waste |")
    print("|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    for r in rows:
        project, runs, tokens, overhead, accepted, partial, useful_negative, rejected, human_confirmed, waste = r
        wr = (100*waste/tokens) if tokens else 0
        print(f"| {project or '-'} | {fmt_tokens(tokens)} | {runs} | {accepted} | {partial} | {useful_negative} | {rejected} | {human_confirmed} | {wr:.1f}% |")

    print("\nLatest runs:")
    latest = con.execute(f"SELECT project, outcome, acceptance_basis, total_tokens, goal FROM runs WHERE {where} ORDER BY created_at DESC LIMIT 12", params).fetchall()
    for project, outcome, basis, tokens, goal in latest:
        print(f"- [{outcome}/{basis}] {project}: {fmt_tokens(tokens)} · {goal[:100]}")


if __name__ == "__main__":
    main()
