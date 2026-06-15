# Personal CFO Dashboard v2 v0.4.0

Dashboard v2 is an offline, account-NAV-first dashboard layer for v0.3.3 merged ledger outputs.

It consumes the v0.3.3 multi-provider merge bundle:

- `merged_account_nav_ledger.csv`
- `merged_account_nav_summary.json`
- `merged_position_ledger.csv` when available
- `merged_provider_summary.json`
- `account_source_map.json`
- `merge_warnings.md`

Account NAV is the primary dashboard source of truth. The position ledger is optional best-effort drilldown data and is not the acceptance gate.

## Command

Generate from an existing v0.3.3 fixture merge bundle:

```powershell
python .\scripts\personal_cfo_agent.py `
  --dashboard-v2 `
  --input-dir .\reports\personal_cfo_agent\merged_v033_fixture `
  --out-dir .\reports\personal_cfo_agent\dashboard_v040_fixture
```

Generate the synthetic v0.3.3 fixture merge bundle first:

```powershell
python .\scripts\personal_cfo_agent.py `
  --merge-provider-bundles `
  --fixture-mode `
  --out-dir .\reports\personal_cfo_agent\merged_v033_dashboard_v2_fixture

python .\scripts\personal_cfo_agent.py `
  --dashboard-v2 `
  --input-dir .\reports\personal_cfo_agent\merged_v033_dashboard_v2_fixture `
  --out-dir .\reports\personal_cfo_agent\dashboard_v040_fixture
```

Local real report bundles, if used later by the operator, must stay under ignored `reports/` paths and must not be committed.

## Outputs

Dashboard v2 writes:

- `PERSONAL_CFO_DASHBOARD_V040.md`
- `dashboard_v040_summary.json`
- `account_nav_dashboard.csv`
- `provider_nav_summary.csv`
- `position_drilldown.csv` when a position ledger exists
- `dashboard_warnings.md`

## Dashboard Scope

Dashboard v2 summarizes:

- total account NAV by provider
- total account NAV by account hash
- account count
- provider count
- base currency values where available
- provider-reported NAV versus derived NAV status
- accounts with missing NAV
- stale or mixed as-of-date warnings
- reconciliation warnings
- provider import status
- position ledger availability as drilldown only

## Warning Codes

- `DASHBOARD_V2_INPUT_MISSING`
- `DASHBOARD_V2_ACCOUNT_NAV_LEDGER_MISSING`
- `DASHBOARD_V2_ACCOUNT_NAV_EMPTY`
- `DASHBOARD_V2_PROVIDER_SUMMARY_MISSING`
- `DASHBOARD_V2_POSITION_LEDGER_MISSING`
- `DASHBOARD_V2_POSITION_LEDGER_BEST_EFFORT`
- `DASHBOARD_V2_NAV_RECONCILIATION_WARNINGS`
- `DASHBOARD_V2_STALE_DATA_WARNING`
- `DASHBOARD_V2_MIXED_AS_OF_DATES`
- `DASHBOARD_V2_GENERATED_OK`
- `DASHBOARD_V2_GENERATED_WITH_WARNINGS`

## Safety Boundaries

Dashboard v2 is offline only. It does not connect to brokers, call broker SDKs, run live reads, run Moomoo account discovery, move money, place orders, create scheduler jobs, or produce recommendations. It is an audit dashboard over already-generated local merge outputs.
