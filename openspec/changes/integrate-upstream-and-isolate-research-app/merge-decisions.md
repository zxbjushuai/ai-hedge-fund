# Fixed-target merge decisions

Stage 1 checkpoint: `5b714d2`; upstream target: `fc1bf25`; merge base: `284a650`.

| Area | Resolution |
| --- | --- |
| Core namespace | Upstream `hedge_fund`; all custom core modules moved and imports mechanically updated. No runtime `v2` imports. |
| FundSpec | Upstream rebalance/benchmark retained. Optional legacy universe and PersonaRefreshPolicy retained. Explicit universe wins. The two upstream no-universe assertions are adapted to this documented compatibility requirement; validation and override tests remain. |
| run_cycle | Upstream fifth positional universe supported; Web-specific execution/valuation/split-sizing and Persona engine stay opt-in. |
| Broker fees | Upstream zero-fee default restored. SQLite runner explicitly passes its existing fee rate, preserving the Web golden NAV/fills. |
| LLM clients | Upstream `llm.client.make_llm(model, ...)` and streaming exports retained. Managed connections use existing `llm.providers.make_llm(provider, model, ...)` and immutable runtime configs; no global credential switching. |
| Model registry | One merged catalog; upstream picker view returns its supported providers and display spelling; managed registry retains all supported vendor/protocol adapters. Legacy GPT-5.5 routing retained for upstream compatibility test. |
| PromptCache | CLI defaults to upstream user-directory cache; Web sets absolute PROMPT_CACHE_DIR. |
| Persistence | Upstream JSON receipts coexist with Web SQLite. No history conversion, renumbering, table drop or live DB migration. |
| Tests | Existing custom tests ported to split route modules. Removed daemon polling test now checks retained cache polling releases sessions. CLI fake-data receipt and Textual home smoke tests added. |
| Dependencies | Upstream project metadata/CLI scripts; custom Web/SQLite/Yahoo requirements added. Lock regenerated with Poetry. NumPy >=2 retained for the current Python 3.14 environment; FastAPI 0.115 with explicit uvicorn. |

## Stage 2 evidence

- Reinstalled new `aihf` environment from regenerated lock.
- Combined suite: 293 passed before adding two entrypoint tests; those two also pass.
- Chrome DevTools tested the new app against disposable DB backup copies: simulation
  history, sim8 result and decision audit, provider list/masked key/model list, and
  cached-security inventory render. No real model/data fetch invoked.
- Known cosmetic issue: old missing font assets and automatic favicon request;
  no business API error observed. Stage 3 will remove unused UI dependencies.
- Source removals are limited to the approved deletion list; ignored local DBs,
  old node_modules, caches and keys remain untouched. Source rollback is possible
  from the stage 1 checkpoint, not by deleting/replacing database files.
