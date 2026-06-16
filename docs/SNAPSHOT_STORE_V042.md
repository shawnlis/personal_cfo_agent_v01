# Snapshot Store v0.4.2

The v0.4.2 snapshot store records local Personal CFO net worth history over time.

It is offline only. It consumes already-generated v0.3.3 merged account NAV outputs and optional v0.4.0 Dashboard v2 outputs. It does not connect to brokers, run live reads, run Moomoo account discovery, move money, place orders, create scheduler jobs, or produce investment recommendations.

## Inputs

The snapshot recorder reads:

- `merged_account_nav_ledger.csv`
- `merged_account_nav_summary.json`
- `merged_provider_summary.json` when available
- `account_source_map.json` when available
- `dashboard_v040_summary.json` when a Dashboard v2 directory is provided
- `dashboard_warnings.md` when a Dashboard v2 directory is provided

`merged_account_nav_ledger.csv` is required. Missing dashboard or provider summaries produce warning codes but do not block snapshot generation.

## Command

Record a snapshot from existing offline local outputs:

```powershell
python .\scripts\personal_cfo_agent.py `
  --record-snapshot `
  --merge-dir .\reports\personal_cfo_agent\merged_v041_local_e2e `
  --dashboard-dir .\reports\personal_cfo_agent\dashboard_v041_local_e2e `
  --out-dir .\reports\personal_cfo_agent\snapshots_v042
```

Fixture-only smoke path:

```powershell
python .\scripts\personal_cfo_agent.py `
  --merge-provider-bundles `
  --fixture-mode `
  --out-dir .\reports\personal_cfo_agent\merged_v042_snapshot_fixture

python .\scripts\personal_cfo_agent.py `
  --dashboard-v2 `
  --input-dir .\reports\personal_cfo_agent\merged_v042_snapshot_fixture `
  --out-dir .\reports\personal_cfo_agent\dashboard_v042_snapshot_fixture

python .\scripts\personal_cfo_agent.py `
  --record-snapshot `
  --merge-dir .\reports\personal_cfo_agent\merged_v042_snapshot_fixture `
  --dashboard-dir .\reports\personal_cfo_agent\dashboard_v042_snapshot_fixture `
  --out-dir .\reports\personal_cfo_agent\snapshots_v042_fixture
```

## Outputs

The snapshot store writes under ignored `reports/` paths:

- `snapshot_manifest.json`
- `net_worth_history.csv`
- `account_nav_history.csv`
- `provider_nav_history.csv`
- `snapshot_warnings.md`
- `SNAPSHOT_STORE_V042.md`

Generated history is local and ignored unless the user explicitly exports it. Do not commit generated snapshot history.

## Immutability

By default, each run creates or appends a new immutable snapshot. If the requested `snapshot_id` already exists, the recorder fails closed with `SNAPSHOT_ID_DUPLICATE`.

## Privacy

Raw account IDs are forbidden. `account_id_hash` is allowed. The snapshot store does not include raw account IDs, card numbers, login accounts, secrets, `.env.local` values, or broker credentials.

## Warning Codes

- `SNAPSHOT_INPUT_MISSING`
- `SNAPSHOT_ACCOUNT_NAV_LEDGER_MISSING`
- `SNAPSHOT_ACCOUNT_NAV_EMPTY`
- `SNAPSHOT_ID_DUPLICATE`
- `SNAPSHOT_HISTORY_CREATED`
- `SNAPSHOT_HISTORY_APPENDED`
- `SNAPSHOT_DASHBOARD_SUMMARY_MISSING`
- `SNAPSHOT_PROVIDER_SUMMARY_MISSING`
- `SNAPSHOT_WARNINGS_PRESENT`
- `SNAPSHOT_MIXED_AS_OF_DATES`
- `SNAPSHOT_STALE_INPUT_WARNING`
- `SNAPSHOT_GENERATED_OK`
- `SNAPSHOT_GENERATED_WITH_WARNINGS`
