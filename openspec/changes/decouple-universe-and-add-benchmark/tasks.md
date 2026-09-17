## 1. Runtime Universe and Price Semantics

- [x] 1.1 Add shared universe normalization and optional FundSpec compatibility default
- [x] 1.2 Pass the effective universe explicitly to `run_cycle` and record it on `CycleRecord`
- [x] 1.3 Skip missing execution opens locally and fail held-but-unpriceable closes

## 2. Benchmark Simulation

- [x] 2.1 Build the market grid exclusively from cached benchmark bars
- [x] 2.2 Persist effective benchmark and benchmark NAV with additive migrations
- [x] 2.3 Return benchmark curve, benchmark return, and excess return compatibly
- [x] 2.4 Update preflight validation and missing-data warnings

## 3. API and Web UI

- [x] 3.1 Add benchmark request validation and price-only benchmark cache acquisition
- [x] 3.2 Add benchmark controls to cache and simulation panels
- [x] 3.3 Render benchmark metrics and a comparison curve, including old-run fallback

## 4. Verification

- [x] 4.1 Add regression coverage for universe, market-grid, missing-price, migration, and API behavior
- [x] 4.2 Run targeted and full non-live v2 tests
- [x] 4.3 Run frontend build and lint
- [x] 4.4 Update this change's handoff with exact results and Git state
