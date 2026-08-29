---
name: agent-run-tracker
description: Finalize and score an engineering or research agent run from the current conversation, objective evidence, tests, benchmarks, git state, and human feedback. Use when an AGENT_TRACKER_FINALIZE prompt appears or when asked to assess whether a coding/research run succeeded.
---

# Agent Run Tracker

Finalize the work that happened immediately before the tracker prompt. The tracker prompt itself is not the task.

## Core rule

Do not equate "the agent says it is done" with success.

A run may be marked `accepted` only when at least one of these is true:

1. The human explicitly accepted the result.
2. Human behavior clearly implies acceptance and there is no later contradictory feedback.
3. Objective acceptance criteria were clear and verifiable evidence shows they were met.

If none applies, use `partial`, `useful_negative`, `rejected`, `blocked`, or `unknown`.

Human negative feedback overrides agent self-assessment. A passing test only proves the behavior that test covers. Do not claim broader success than the evidence supports.

## Outcome labels

- `accepted`: requested result is supported by human acceptance or objective evidence.
- `partial`: useful progress exists, but one or more requested criteria remain unresolved.
- `useful_negative`: a hypothesis or approach failed, but the run produced concrete reusable evidence that narrows the search space.
- `rejected`: the result failed or was reverted and produced no meaningful reusable result.
- `blocked`: progress stopped due to an external dependency, permission, environment, unavailable data, or another blocker.
- `unknown`: evidence is too weak to judge.

## Acceptance basis

Use exactly one:

- `explicit_human`: the human directly accepted, approved, or confirmed the result.
- `inferred_human`: the conversation strongly implies acceptance, but the human did not state it directly.
- `objective_evidence`: tests, benchmarks, artifact inspection, or another explicit criterion establishes success.
- `none`: no sufficient acceptance signal exists.

Agent self-report is never an acceptance basis.

## Human feedback

Use one of `positive`, `negative`, `mixed`, `none`.

Inspect the whole relevant conversation, especially messages after earlier agent results. If the latest human message says the earlier result is broken, wrong, reverted, worse, or otherwise rejected, reflect that even if the agent previously claimed success.

## Feedback-only turns

If the source user turn only evaluates earlier work and requests no substantive new work, do not create a fake new engineering run.

Instead call the recorder with:

```json
{
  "action": "feedback",
  "session_id": "<from tracker prompt>",
  "source_turn_id": "<from tracker prompt>",
  "outcome": "accepted",
  "acceptance_basis": "explicit_human",
  "human_feedback": "positive",
  "confidence": 0.99,
  "summary": "Human confirmed the previous result."
}
```

The recorder updates the previous run in the same session.

## New work turns

For substantive implementation, debugging, research, benchmark, review, refactor, infrastructure, or planning work, create one run.

Before recording:

1. Recover the actual user goal from the source turn.
2. Identify any explicit acceptance criteria.
3. Review evidence already produced in the conversation.
4. If a very small verification check is needed for a reliable verdict, run it. Do not start a new large implementation loop.
5. Check whether the user's later messages in the same conversation accept or reject earlier claims.
6. Give a conservative verdict.
7. If the current user turn also contains direct feedback on the previous run, add a `feedback_updates` entry.

Use this schema:

```json
{
  "action": "create",
  "session_id": "<from tracker prompt>",
  "source_turn_id": "<from tracker prompt>",
  "project": "optional-project-name",
  "task_type": "implementation",
  "goal": "One concise sentence describing the requested outcome.",
  "outcome": "accepted",
  "acceptance_basis": "objective_evidence",
  "confidence": 0.92,
  "human_feedback": "none",
  "summary": "What actually changed or was learned.",
  "next_step": "Empty if no next step is needed.",
  "evidence": [
    {"type": "test", "summary": "Relevant tests passed."},
    {"type": "benchmark", "summary": "FPS improved from 18.4 to 27.1 without exceeding the stated quality loss."}
  ],
  "metrics": [
    {"name": "fps", "before": 18.4, "after": 27.1, "unit": "fps"}
  ],
  "feedback_updates": [
    {
      "target": "previous",
      "outcome": "rejected",
      "acceptance_basis": "explicit_human",
      "human_feedback": "negative",
      "confidence": 0.99,
      "summary": "Human reported that the prior result did not work in the real target environment."
    }
  ]
}
```

Valid `task_type` values:

`implementation`, `debug`, `research`, `benchmark`, `refactor`, `planning`, `review`, `infra`, `other`.

`feedback_updates` is optional.

## Record exactly once

Pipe one JSON object to the local recorder:

```bash
python3 "$HOME/.codex/agent-run-tracker/record_run.py" <<'JSON'
{ ... }
JSON
```

If the recorder rejects the schema, correct the JSON and retry once. Do not create multiple run records for the same source turn.

After a successful recorder response, finish the tracker turn with a short statement only. Do not expose internal tracker details unless the user asked for them.
