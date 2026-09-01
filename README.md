# Agent Run Tracker

A local Codex tracker that turns agent chats into measurable engineering and research runs.

The goal is simple: measure useful progress, not just token usage, commits, or lines of code.

For every substantive Codex task, the tracker connects:

- the original user goal
- token usage
- git state and code changes
- tests and benchmark evidence
- human feedback
- the final task outcome

It then stores a structured record in SQLite and JSONL so you can compare projects, spot wasted agent loops, and estimate how much useful work you get per 100M tokens.

## Why

A 100M-token run can be excellent if it solves a hard problem. It can also be waste if the agent spends hours on the wrong path.

Raw token count does not tell you which case happened.

Agent Run Tracker is built to answer questions such as:

- How many accepted tasks do I get per 100M tokens?
- Which projects consume the most tokens?
- What fraction of tokens go to rejected work?
- How often does an agent report success and get rejected later by a human?
- How much useful information comes from failed experiments?
- How much token overhead does the tracker itself add?
- How long does one human-agent iteration take?
- How quickly do I test an agent result and send the next useful correction?
- How many substantive feedback cycles do I complete per day?

The main idea is that the scarce resource is human attention. More tokens are useful when they produce more accepted work with less human supervision.

## How it works

```text
Human prompt
    |
    v
UserPromptSubmit hook
    |
    |-- token baseline
    |-- git SHA
    |-- timestamp
    |-- prompt excerpt
    v
Normal Codex work
    |
    v
Stop hook
    |
    v
One short finalizer turn
    |
    v
$agent-run-tracker skill
    |
    |-- read conversation context
    |-- inspect tests / benchmarks / git state
    |-- inspect human feedback
    |-- classify the outcome
    v
SQLite + JSONL
```

The finalizer is separate from the actual work. Its token usage is recorded as `tracker_overhead_tokens`, so tracker cost does not get mixed into the task's work-token count.

No second API key or external model request is needed. The finalizer uses the Codex conversation that already contains the task context.

## Outcome model

Every substantive run gets one outcome:

| Outcome | Meaning |
| --- | --- |
| `accepted` | The requested result is supported by human acceptance or objective evidence. |
| `partial` | Useful progress exists, but one or more requested criteria remain unresolved. |
| `useful_negative` | An approach failed, but produced reusable evidence that narrows the search space. |
| `rejected` | The result failed or was reverted and produced no meaningful reusable result. |
| `blocked` | Work stopped because of an external dependency, permission issue, unavailable data, or similar blocker. |
| `unknown` | There is not enough evidence to judge the result. |

### An agent cannot accept its own work

`Agent: Done` is not enough to mark a run as `accepted`.

Accepted runs require one of these bases:

| Acceptance basis | Meaning |
| --- | --- |
| `explicit_human` | The human directly approved or confirmed the result. |
| `inferred_human` | The conversation strongly implies acceptance and contains no later contradiction. |
| `objective_evidence` | Tests, benchmarks, artifact inspection, or another explicit criterion shows that the goal was met. |
| `none` | No sufficient acceptance signal exists. This cannot be paired with `accepted`. |

This keeps agent self-confidence separate from evidence.

## Human feedback can revise old runs

A later message can correct an earlier classification.

```text
Agent: Implemented the new on-device path. Tests pass.
Tracker: accepted / objective_evidence

Human: This actually looks much worse on the iPhone. Fix it.
```

The next finalizer can revise the earlier run to:

```text
outcome = rejected
acceptance_basis = explicit_human
human_feedback = negative
```

The new fix is then tracked as a separate run. A feedback-only message such as `Yep, this works now.` updates the previous run instead of creating a fake engineering run.

## What gets recorded

A run can contain:

- project name and task type
- user goal
- model
- start and end timestamps
- wall time
- git start and end SHA
- files changed, insertions, and deletions
- input tokens
- cached input tokens
- uncached input tokens
- output tokens
- reasoning output tokens
- total work tokens
- tracker-overhead tokens
- outcome
- acceptance basis
- confidence
- human feedback
- evidence
- benchmark metrics
- summary and next step

Supported task types:

```text
implementation
debug
research
benchmark
refactor
planning
review
infra
other
```

## Install

Clone the repo and run:

```bash
python3 install.py
```

The installer:

- installs the skill to `~/.agents/skills/agent-run-tracker`
- installs runtime scripts to `~/.codex/agent-run-tracker`
- merges `UserPromptSubmit` and `Stop` handlers into `~/.codex/hooks.json`
- backs up an existing `hooks.json`
- creates `~/.agent-tracker/config.json` if needed

Restart Codex after installation. Review and trust the new local hooks when Codex asks.

## Normal usage

After installation, use Codex normally. There is no extra command for each task.

For example:

```text
Replace dense flow with sparse tracking and keep PSNR loss below 0.3 dB.
```

The tracker records the task start automatically. When Codex is about to stop, the `Stop` hook requests one short finalizer pass. The skill evaluates the run and writes exactly one structured record.

The finalizer should not start another large implementation loop. It may run a small verification step if that is needed for a reliable verdict.

## Example record

```json
{
  "project": "on-device-4dgs",
  "task_type": "benchmark",
  "goal": "Reach more than 25 FPS with less than 0.3 dB PSNR loss.",
  "outcome": "accepted",
  "acceptance_basis": "objective_evidence",
  "confidence": 0.95,
  "human_feedback": "none",
  "summary": "Sparse tracking increased throughput while staying inside the quality target.",
  "metrics": [
    {"name": "fps", "before": 18.4, "after": 27.1, "unit": "fps"},
    {"name": "psnr", "before": 24.60, "after": 24.51, "unit": "dB"}
  ]
}
```

If the agent only says `Implemented it. It should work now.`, that should not become accepted without human acceptance or objective evidence.

## Reports

Show the last seven days:

```bash
python3 ~/.codex/agent-run-tracker/report.py --days 7
```

Filter to one project:

```bash
python3 ~/.codex/agent-run-tracker/report.py --days 30 --project mnema
```

Example:

```text
Agent Run Tracker · last 7 days
Work tokens: 2.96B | Tracker overhead: 14.2M | Runs: 87
Strict waste rate (rejected only): 17.4%
Interaction efficiency: agent turnaround 31.8m avg | human feedback latency 9.6m avg | feedback cycles/day 12.4
```

## Useful metrics

### Accepted runs per 100M tokens

```text
accepted_runs / (total_tokens / 100M)
```

### Strict waste rate

```text
rejected_run_tokens / total_tokens
```

Only rejected work counts as strict waste. `useful_negative` stays separate because a failed research hypothesis can still produce useful information.

### Agent false-positive rate

```text
human_rejected_after_apparent_success / apparent_agent_successes
```

This estimates how much trust to place in agent completion claims.

### Tracker overhead

```text
tracker_overhead_tokens / work_tokens
```

### Agent turnaround latency

```text
run.work_ended_at - run.started_at
```

This is already stored as `wall_seconds`. It approximates the time from a substantive human instruction until the agent returns a result that can be judged.

### Human feedback latency

```text
next_run.started_at - previous_run.work_ended_at
```

The report computes this only between consecutive tracked runs in the same session. It approximates the time spent inspecting, testing, thinking, and sending the next substantive correction. Long breaks, meals, sleep, or context switches can therefore raise it, so use it as an interaction metric rather than a pure cognitive-speed metric.

### Feedback cycles per day

```text
tracked_substantive_runs / report_window_days
```

This is iteration throughput. It should be read together with accepted outcomes, useful negatives, and waste rate. Maximizing cycles while quality falls is not useful.

### Project-specific benchmark gain

```text
PSNR gain / 100M tokens
FPS gain / 100M tokens
latency reduction / 100M tokens
memory reduction / 100M tokens
```

## Research and negative results

Research should not be forced into a binary success/failure label. If a clean experiment disproves a hypothesis but reduces uncertainty and prevents repeated work, mark it `useful_negative` instead of `rejected`.

## Token accounting

`cached_input_tokens` is treated as a subset of `input_tokens`. Do not add it to input a second time when calculating total usage.

The tracker separates actual task usage from its own finalizer cost:

```text
total_tokens = tokens used by the task
tracker_overhead_tokens = tokens added by the tracking finalizer
```

## Local data

```text
~/.agent-tracker/
├── config.json
├── tracker.sqlite3
└── runs.jsonl
```

The SQLite database is useful for analysis and dashboards. JSONL is useful for inspection, backup, and custom pipelines.

No tracker data is sent anywhere by these scripts.

## Configuration

Default configuration lives at `~/.agent-tracker/config.json`.

```json
{
  "enabled": true,
  "store_prompt_chars": 4000,
  "database_path": "~/.agent-tracker/tracker.sqlite3",
  "jsonl_path": "~/.agent-tracker/runs.jsonl",
  "require_evidence_for_accept": true
}
```

Set `store_prompt_chars` to `0` if you do not want prompt text saved in the tracker database.

## Repo layout

```text
agent-run-tracker/
├── README.md
├── install.py
├── uninstall.py
├── config.example.json
├── hooks.template.json
├── runtime/
│   ├── common.py
│   ├── record_run.py
│   ├── report.py
│   ├── track_prompt.py
│   └── track_stop.py
└── skill/
    └── SKILL.md
```

## Implementation notes

Codex hook input exposes `transcript_path`, but the transcript representation is not a stable public data format.

The token parser is isolated in `runtime/common.py` and fails open. If the rollout format changes, outcome tracking can continue while token fields may temporarily be unavailable until the parser is updated.

Automatic acceptance is still an estimate. A passing test may cover only part of the requested behavior, a benchmark can miss production failure modes, and human feedback may arrive later. Treat the tracker as an observability layer, not an oracle.

The strongest feedback correction path is within the same tracked conversation. Cross-session feedback may need a stronger run-linking layer in a future version.

## Uninstall

```bash
python3 uninstall.py
```

This removes the runtime, skill, and tracker hook handlers. Historical tracker data is kept by default. Delete `~/.agent-tracker/` manually if you also want to erase the stored history.
