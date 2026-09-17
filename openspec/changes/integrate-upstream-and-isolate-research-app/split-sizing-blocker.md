# Acceptance blocker: split-adjusted holdings valued at pre-split marks

## Resolution

Fixed with user authorization: runner passes effective-day split ratios to
`run_cycle`; sizing divides prior signal marks by those ratios, while retaining
the original marks for analysts. The audit now includes `sizing_marks` (default
empty for legacy payloads). No database migration is required.

The corrected fixture buys only 8 extra shares with the $40 dividend, has no
negative cash and no corrective sale the next day. Forward/reverse/fractional
split tests also verify unchanged equity and cash-in-lieu behavior.
The JSON fixture now records the corrected result. The history below describes
the original failure; its acceptance test is retained and now passes.
Raw-price valuation_change after a split is unchanged and remains a separate
event-policy question; this fix does not silently redefine Persona triggers.

Discovered by the integrated offline migration fixture. Confirmed in baseline
`5fca1b4` using `git show`: this is not introduced by route extraction.

Reproduction:

```powershell
poetry run pytest research_app/backend/test_migration_events.py -q
```

The fixture buys 100 shares at $10 on January 9. On January 10 a 2:1 split makes
that 200 shares at $5; a $0.20 dividend credits $40. Correct book equity is $1040.
However, the runner applies corporate actions before `run_cycle`, and the latter
values the updated 200 shares at the previous signal day's $10 close. It sizes
orders from $2040, buys another 208 shares and leaves cash at -$1000. The following
cycle sells 200 shares. NAV remains $1040 in the constant-price fixture, hiding
the unwanted leverage and turnover.

The event engine also observes the raw price halving and triggers valuation_change;
that is recorded as current behavior, not certified as the desired future policy.

Before the fix, `migration-events.json` recorded the erroneous behavior and the
separate economic invariant `test_split_does_not_create_unlevered_overdraft`
failed. That assertion was not skipped or xfailed; it is the regression gate.

Recommended follow-up: separate signal-time prices from portfolio-sizing marks
after corporate actions; specify split handling for the event price anchor. Keep
the T/T+1 contract and verify no artificial leverage, cash-in-lieu and dividends.
Do not make an incidental blanket switch of all signal marks to execution prices.
Resolve this behavior decision before approving the stage gate.
