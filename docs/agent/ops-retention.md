# Ops retention and failure visibility

`scripts/aihf_ops.py` manages local simulation telemetry and on-demand run
artifacts. Cleanup is opt-in and never runs as part of a simulation or daily
agent loop.

## Managed files

- `logs/simulations/*.log`: per-run JSONL telemetry.
- `logs/ops/*.json` and `logs/ops/*.md`: simulation, analysis, and matrix output.
- `logs/daily/*.json` and `logs/daily/*.md`: legacy manual daily-pipeline output.

Agent logs, service logs, `fund.db`, `.v2_cache/`, and provider state are outside
the managed set.

## Inspect pressure

```bash
.venv/bin/python scripts/aihf_ops.py retention
.venv/bin/python scripts/aihf_ops.py retention --json
.venv/bin/python scripts/aihf_ops.py status
```

The default policy keeps files for 30 days and caps the managed total at 512
MiB. It always preserves the newest file in each managed directory, skips
symlinks, and will not budget-prune files newer than one day. If recent logs
alone exceed the cap, the report says `OVER BUDGET` rather than deleting active
evidence.

The planner also reads `sim_run` state from `fund.db` in read-only mode and
protects `logs/simulations/sim-{id}.log` while run `{id}` is `pending`, `running`,
or `cancelling`. These files are listed as `active_simulation` and cannot be
selected by age or size-budget pruning. If an existing database cannot be read,
the command fails closed instead of assuming that no runs are active.
`FUND_DB_PATH` is resolved from the repository `.env` with the same relative-path,
home-directory, and override semantics as the backend, so the command checks the
database used by the running service.

`status` prints the latest simulation, aggregated simulation/cache counts, the
newest failed run with a clipped error, startup recovery counts, and the current
retention plan. It does not print provider credentials.

## Apply cleanup

Review the dry-run plan first. Deleting files requires explicit user approval
for that specific target set. Save the reviewed target list, then apply it:

```bash
.venv/bin/python scripts/aihf_ops.py retention --plan-file /tmp/aihf-retention-plan.json
# review the printed targets and approve them explicitly
.venv/bin/python scripts/aihf_ops.py retention --apply --plan-file /tmp/aihf-retention-plan.json
```

`--apply` never rescans. It deletes only the targets recorded in the saved plan,
so a file that becomes eligible after the dry run is left in place until a new
plan is reviewed. The plan records its `logs` root; applying it against another
root is rejected, as are unsupported schemas, duplicate entries, and unsafe or
pattern-mismatched paths.

Immediately before unlinking, `--apply` revalidates each path. It refuses
symlinks (including a symlinked `logs` root or managed directory), paths outside
`logs/{simulations,ops,daily}`, and non-regular files. It also requires the file
size and nanosecond modification time to match the saved snapshot; a file
written after planning is skipped as `changed_since_planning`. Any per-file
failure is printed and makes the command exit nonzero.

Run state is loaded again at apply time. If a run becomes pending, running, or
cancelling after the plan was approved, its log is skipped as
`active_simulation` even though the saved snapshot selected it. Terminal run
states do not block cleanup.
