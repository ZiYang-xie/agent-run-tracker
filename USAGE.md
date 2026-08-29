# Agent Run Tracker

Agent Run Tracker is a lightweight local tracking layer for agentic software and research work in Codex.

Its goal is simple:

> Measure how much useful engineering progress each agent run produces, instead of only counting tokens, commits, or lines of code.

The tracker connects a Codex task to its goal, token usage, git state, tests or benchmarks, human feedback, and final outcome. It then stores a structured record that can be analyzed across projects and over time.

## Why this exists

With long-running coding agents, raw token usage becomes hard to interpret. A run that consumes 100M tokens may be excellent if it solves a hard problem, or wasteful if it loops on the wrong implementation.

The tracker focuses on questions such as:

- How many accepted tasks do I get per 100M tokens?
- Which projects consume the most tokens?
- How much work is later rejected by a human?
- How often does an agent claim success but turn out to be wrong?
- How much useful progress comes from failed experiments?
- How much extra token cost does the tracker itself add?

The intended north-star metric is not token count. It is useful engineering progress per unit of human attention.

## Core design

The tracker uses two Codex hooks and one global skill.

```text
Human prompt
    |
    v
UserPromptSubmit hook
    |
    |-- token baseline
    |-- git SHA
    |-- timestamp
    |-- original prompt
    v
Normal Codex work
    |
    v
Stop hook
    |
    v
Finalizer turn
    |
    v
$agent-run-tracker skill
    |
    |-- read the conversation
    |-- inspect tests / benchmarks / git state
    |-- inspect human feedback
    |-- classify the outcome
    v
SQLite + JSONL
```

The finalizer is intentionally separate from the normal work. Its own token usage is recorded as tracker overhead so it does not pollute the work-token number.

## Outcome model

A run receives one of the following outcomes.

| Outcome | Meaning |
| --- | --- |
| `accepted` | The requested result is supported by human acceptance or objective evidence. |
| `partial` | Useful progress exists, but one or more requested criteria remain unresolved. |
| `useful_negative` | An approach failed, but produced reusable evidence that narrows the search space. |
| `rejected` | The result failed or was reverted and produced no meaningful reusable result. |
| `blocked` | Work stopped because of an external dependency, permission issue, unavailable data, or another blocker. |
| `unknown` | There is not enough evidence to judge the result. |

### Acceptance is not self-reported

An agent saying `done` is not enough to mark a run as accepted.

Every accepted run must also record an acceptance basis:

| Basis | Meaning |
| --- | --- |
| `explicit_human` | The human directly approved or confirmed the result. |
| `inferred_human` | The conversation strongly implies acceptance, with no later contradiction. |
| `objective_evidence` | Tests, benchmarks, artifact inspection, or another explicit criterion shows that the goal was met. |
| `none` | No sufficient acceptance signal exists. This cannot be used with `accepted`. |

This separation is important because agent self-assessment can be overconfident.

## Human feedback correction

A later human message can revise an earlier run.

Example:

```text
Agent: Implemented the new on-device path. Tests pass.
Tracker: accepted / objective_evidence

Human: This actually looks much worse on the iPhone. Fix it.
```

The next tracker pass can update the earlier run to:

```text
outcome = rejected
acceptance_basis = explicit_human
human_feedback = negative
```

The new fix is then tracked as a separate run.

A feedback-only message such as:

```text
Yep, this works now.
```

updates the previous run instead of creating a fake engineering run.

## What gets recorded

Each substantive run can contain:

- project name
- task type
- original goal
- model
- start and end timestamps
- wall time
- git start SHA
- git end SHA
- files changed
- insertions and deletions
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
- summary
- suggested next step

## Task types

Supported task types are:

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

## Installation

Run the installer from the project directory:

```bash
python3 install.py
```

The installer places the runtime and skill in the standard user-level locations:

```text
~/.agents/skills/agent-run-tracker/
~/.codex/agent-run-tracker/
~/.codex/hooks.json
~/.agent-tracker/
```

It also merges the required hook handlers into your existing Codex hooks file and backs up that file first.

Restart Codex after installation. Review and trust the new local hooks when Codex asks.

## Installed data layout

By default, local tracker data lives here:

```text
~/.agent-tracker/
├── config.json
├── tracker.sqlite3
└── runs.jsonl
```

The SQLite database is intended for analysis and dashboards. The JSONL file is useful for inspection, backup, and custom pipelines.

## Normal usage

After installation, there is no extra command required for a normal Codex task.

Just work as usual:

```text
Implement a sparse tracking path and keep quality loss below 0.3 dB.
```

The tracker records the task start automatically. When Codex is about to stop, the tracker asks for one short finalizer pass. The skill then evaluates the result and persists one structured record.

The finalizer should not restart a large implementation loop. It may run a small verification step if that is needed for a reliable verdict.

## Example run

A successful benchmark-oriented run might be stored conceptually as:

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
    {
      "name": "fps",
      "before": 18.4,
      "after": 27.1,
      "unit": "fps"
    },
    {
      "name": "psnr",
      "before": 24.60,
      "after": 24.51,
      "unit": "dB"
    }
  ]
}
```

A run that only reports success without enough evidence should not be accepted:

```text
Agent: Implemented it. It should work now.

Tracker:
outcome = partial or unknown
acceptance_basis = none
```

## Reporting

Show the last seven days:

```bash
python3 ~/.codex/agent-run-tracker/report.py --days 7
```

Filter to one project:

```bash
python3 ~/.codex/agent-run-tracker/report.py --days 30 --project mnema
```

Example output:

```text
Agent Run Tracker · last 7 days

Work tokens: 2.96B
Tracker overhead: 14.2M
Runs: 87
Strict waste rate: 17.4%
```

The report also summarizes each project by token usage and outcome counts.

## Recommended metrics

### Accepted runs per 100M tokens

```text
accepted_runs / (total_tokens / 100M)
```

This is a simple first-order measure of token efficiency.

### Strict waste rate

```text
rejected_run_tokens / total_tokens
```

Only rejected runs count as strict waste. `useful_negative` is intentionally excluded because a failed research hypothesis can still produce useful information.

### Agent false-positive rate

One of the most useful long-term metrics is how often an agent initially appears successful but is later rejected by human feedback.

Conceptually:

```text
human_rejected_after_agent_success / apparent_agent_successes
```

This helps measure how much trust should be placed in the agent's own completion claims.

### Tracker overhead

```text
tracker_overhead_tokens / work_tokens
```

The finalizer itself uses tokens. These are tracked separately so productivity estimates use work tokens rather than work plus measurement cost.

### Benchmark gain per token

For research and systems work, project-specific metrics are often more useful than generic task counts.

Examples:

```text
PSNR gain / 100M tokens
FPS gain / 100M tokens
latency reduction / 100M tokens
memory reduction / 100M tokens
```

### Human leverage

A future extension can combine agent runtime with human review time:

```text
agent_active_time / human_active_time
```

A stronger version weights this by accepted outcomes.

## Research runs and negative results

Research work should not be forced into a binary success/failure label.

For example, a run may test the hypothesis:

```text
Sparse tracking can replace dense optical flow without reducing reconstruction quality.
```

If a clean benchmark disproves the hypothesis, the run can be marked:

```text
outcome = useful_negative
```

This lets the tracker distinguish useful scientific information from unproductive agent loops.

## Token accounting

The tracker records cached input separately from total input.

`cached_input_tokens` is treated as a subset of `input_tokens`, not an additional quantity. Do not add it to `input_tokens` again when calculating total work.

The tracker also records its finalizer usage separately:

```text
total_tokens = tokens used by the actual task
tracker_overhead_tokens = tokens added by the tracking finalizer
```

This makes it possible to measure whether the tracking system itself is cheap enough to keep enabled all the time.

## Configuration

The default configuration is stored at:

```text
~/.agent-tracker/config.json
```

Example:

```json
{
  "enabled": true,
  "store_prompt_chars": 4000,
  "database_path": "~/.agent-tracker/tracker.sqlite3",
  "jsonl_path": "~/.agent-tracker/runs.jsonl",
  "require_evidence_for_accept": true
}
```

## Privacy

The tracker is local by default.

Its scripts write to local SQLite and JSONL files. No separate API key or external model request is required for the tracker judgment. The finalizer uses the Codex conversation that already contains the task context.

The prompt excerpt stored in the database is configurable. Set `store_prompt_chars` to `0` if you do not want prompt text saved.

## Limitations

### Codex transcript format

Codex hook input exposes a `transcript_path`, but the transcript representation is not a stable public data format.

Token parsing is therefore isolated in the runtime and should fail open. If Codex changes the rollout format, outcome tracking can continue while token fields may temporarily be unavailable until the parser is updated.

### Automatic acceptance is still an estimate

The tracker reduces self-report bias, but it cannot perfectly measure engineering value.

A passing test may cover only part of the requested behavior. A benchmark may miss a production failure mode. Human feedback can also arrive much later.

Treat the tracker as an observability layer, not as an oracle.

### Cross-session feedback

The strongest correction path is feedback that appears in the same tracked conversation. Cross-session or cross-repository feedback may require an additional identity/linking layer in a future version.

## Uninstall

Run:

```bash
python3 uninstall.py
```

This removes the installed runtime, skill, and tracker hook handlers.

The historical tracker database is kept by default. Delete `~/.agent-tracker/` manually if you also want to erase the stored history.

## Suggested workflow

For high-volume agent use, a practical loop is:

1. Give each task a measurable goal when possible.
2. Let Codex work normally.
3. Let the tracker classify the run automatically.
4. Correct the result naturally in chat when the agent was wrong.
5. Review project-level token efficiency weekly.
6. Look for repeated causes of rejected runs.
7. Improve prompts, repository instructions, tests, and stop criteria based on those patterns.

The purpose is not to minimize token usage at all costs. The purpose is to spend more tokens only when they produce more useful work with less human supervision.