# Design: Add Ops Retention and Observability

## Managed Artifacts

Only three ignored log roots are managed:

- `logs/simulations/*.log`: per-run JSONL telemetry.
- `logs/ops/*.json` and `*.md`: on-demand simulation, analysis, and matrix output.
- `logs/daily/*.json` and `*.md`: legacy manual daily-pipeline output.

Agent logs, service logs, databases, caches, and user configuration are outside
the managed set.

## Retention Policy

The planner evaluates regular files by modification time. Symlinks are reported
and skipped. A file is age-eligible when it is older than both `keep_days`
(default 30) and `min_age_days` (default 1), so lowering `keep_days` cannot
bypass the recent-evidence floor. The planner also keeps the newest file in each
managed directory, so sparse installations retain a recent example.

If the managed total still exceeds `max_total_mb` (default 512 MiB), the oldest
remaining files are selected until the projected total fits, but only when they
are older than `min_age_days` (default 1). This protects logs from an active
run while still bounding long-running installations. If too much recent data
remains, the plan is marked `over_budget` rather than deleting active evidence.

## Execution Safety

Planning is side-effect free. The `retention` command prints the plan by default
and can persist that exact target set with `--plan-file`. `--apply` requires the
saved plan file and does not rescan: it deletes only files named in the reviewed
snapshot. A file that becomes eligible after the dry run therefore needs another
reviewed plan. Loading rejects an unsupported schema, a plan from another root,
duplicate entries, and unsafe or pattern-mismatched paths.

Before each unlink, the path must still be a regular, non-symlink file under its
managed root, its first path component must be one of the managed directories,
and its size and `mtime_ns` must match the saved snapshot. Files changed after
planning are reported as `changed_since_planning` and left in place. Failures
are returned per file and make the command exit nonzero. A symlinked `logs`
root or symlinked managed directory (for example `logs/ops`) is rejected rather
than followed.

## Observability

`aihf_ops.py status` reads `/dashboard/system/status` and the recent-run list,
then prints:

- runtime simulation/cache counts and startup recovery;
- the latest run and a compact failure summary with the newest error;
- managed-log bytes, file count, retention candidates, and current budget state
  (not the projected post-cleanup state). If aggregate counts show failed or
  cancelled runs but none appear in the capped recent-run page, the failure line
  says so instead of claiming there was no failure.

No API or database schema changes are required.
