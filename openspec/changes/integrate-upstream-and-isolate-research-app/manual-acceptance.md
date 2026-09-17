# Stage 1 manual acceptance

Status: passed, as confirmed by the user in conversation on 2026-09-17.
Browser interactions and Ctrl+C acceptance are user-reported, not automated claims.
The split-sizing blocker has also been fixed and regression-tested.

## Preparation

- Existing ports 8000 and 5173 were occupied during verification; no existing
  processes were stopped. Close the current application with its own launcher first.
- Prefer disposable copies of the backed-up databases. Set FUND_DB_PATH and
  LLM_DB_PATH to the absolute paths of those copies in the launching terminal.
- Set PROMPT_CACHE_DIR to a disposable directory for test runs. Never publish keys.
- Start `.\research_app\run.bat` from the repository root. Do not start old and
  new applications simultaneously on the same ports.

## Checklist

1. Navigation: only Simulation / Data / Model providers; all pages render without
   Flow editor, blank screens or browser console errors.
2. Providers: existing connections/models visible; keys remain masked; on copies,
   save a change with an empty key field and verify the key is retained. Do not use
   Test/Sync if you want to keep acceptance fully offline.
3. Data: search the existing catalog, paginate, select/unselect securities, load
   a saved universe if one exists, and inspect cached prices and their chart.
   Empty saved-universe lists are valid. No catalog sync or fetch is required for
   this read-only check.
4. Simulation: existing history is visible; open sim8 and inspect NAV, benchmark,
   fills and Decision Audit including persona provenance. Confirm preflight reads
   the prepared cache. Real inference is optional and requires an explicit choice
   of connection; offline fake-LLM execution is already covered by tests.
5. State retention: change tabs during a task and return; ensure no task state is
   unexpectedly lost. After editing models, check the simulation selector reflects
   the changes (record whether a full page reload is needed).
6. Shutdown: press Ctrl+C in the launcher terminal. Confirm both services report
   stopping and these ports have no listeners belonging to the new launch:

   ```powershell
   Get-NetTCPConnection -LocalPort 8000,5173 -State Listen -ErrorAction SilentlyContinue
   ```

7. Restart from the same terminal, then repeat Ctrl+C. It should start successfully
   without a port conflict or leaving the terminal unresponsive.

Report pass/fail by item number, with screenshots/error text for failures. Never
include API keys. This does not authorize commits, file deletion or an upstream merge.
