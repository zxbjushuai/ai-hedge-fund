# Integrate upstream and isolate the research Web application

## Why

The upstream fc1bf25 removes the old Web app and renames v2 to hedge_fund. Preserve the fork's SQLite simulations and managed connections while restoring an upstream merge path.

## Changes

1. Capture baseline 5fca1b4, consistent SQLite backups, and deterministic fixtures.
2. Reuse the self-developed Web components and backend in research_app, with stable /dashboard APIs and no flow/daemon dependency.
3. Merge fixed upstream fc1bf25, migrate imports to hedge_fund, preserve Web historical semantics and upstream CLI/TUI.
4. Remove approved obsolete code, retaining old data and migration history.
5. Verify both entrypoints and hand over the new development baseline.

## Constraints

No visual redesign, no DB resets, no credential disclosure. File deletion requires approval of exact targets. Commits, final development-branch integration and push require separate authorization.

