# Proposal: Add Ops Retention and Observability

## Why

Simulation telemetry and on-demand ops artifacts accumulate without a retention
policy. Operators can see recent runs, but there is no compact view of failed
work or disk pressure. This is acceptable while the installation is small, but
it makes long-running maintenance and failure triage unnecessarily manual.

## What Changes

- Add a retention planner for simulation JSONL logs, ops reports, and legacy
  daily-pipeline artifacts.
- Make cleanup dry-run by default. Reviewers can persist the exact target set;
  `--apply --plan-file` removes only that saved snapshot, and files that become
  eligible later require a new reviewed plan.
- Keep the newest artifact in each managed directory and never prune files newer
  than the configured minimum age.
- Extend `scripts/aihf_ops.py status` with runtime counts, last-run status,
  failure summaries, and retention pressure.
- Add focused tests for age pruning, size budgeting, symlink safety, dry-run
  behavior, and the status summary.

## Non-goals

- Deleting logs automatically during a daily run.
- Managing agent audit logs or systemd service logs.
- Adding an in-process scheduler, metrics server, or external monitoring stack.
- Resetting or deleting `fund.db`, `.v2_cache/`, or provider state.
