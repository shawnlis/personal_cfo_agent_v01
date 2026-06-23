# Snapshot History Manager v0.6.8

The snapshot history manager is an offline safety utility for inspecting and
pruning local snapshot history CSV files after a bad refresh has been reviewed.

It is designed for cases where a broker read, manual input, or FX issue polluted
local history and the operator wants to keep only known-good snapshot dates or
snapshot IDs.

## Safety Boundary

- No broker reads.
- No Webull token preflight.
- No Moomoo discovery.
- No browser automation.
- No private input values printed.
- No exact NAV, balances, positions, or raw account IDs printed.
- Generated reports and backups stay under ignored local paths.

## Dry-Run Inspect

Dry-run is the default. This writes redacted reports and does not mutate history
files.

```powershell
python .\scripts\personal_cfo_agent.py `
  --snapshot-history-manager `
  --snapshot-dir .\reports\personal_cfo_agent\net_worth_refresh_local\snapshots_confirmed `
  --out-dir .\reports\personal_cfo_agent\snapshot_history_manager_v068_local
```

Outputs:

- `snapshot_history_manager_summary.json`
- `snapshot_history_manager_warnings.md`
- `SNAPSHOT_HISTORY_MANAGER_V068.md`

## Prune With Backup

Applying changes is explicit. You must provide at least one keep date or keep
snapshot ID. The manager creates a timestamped backup under the output folder
before rewriting history CSVs.

```powershell
python .\scripts\personal_cfo_agent.py `
  --snapshot-history-manager `
  --snapshot-dir .\reports\personal_cfo_agent\net_worth_refresh_local\snapshots_confirmed `
  --keep-snapshot-date 2026-06-21 `
  --apply-snapshot-history-changes `
  --out-dir .\reports\personal_cfo_agent\snapshot_history_manager_v068_local
```

The manager rewrites only:

- `net_worth_history.csv`
- `account_nav_history.csv`
- `provider_nav_history.csv`

It does not edit broker bundles, private inputs, dashboards, or source reports.

## Warning Codes

- `SNAPSHOT_HISTORY_MANAGER_INPUT_MISSING`
- `SNAPSHOT_HISTORY_MANAGER_NO_HISTORY_ROWS`
- `SNAPSHOT_HISTORY_MANAGER_KEEP_SET_EMPTY`
- `SNAPSHOT_HISTORY_MANAGER_DRY_RUN`
- `SNAPSHOT_HISTORY_MANAGER_BACKUP_CREATED`
- `SNAPSHOT_HISTORY_MANAGER_APPLIED`
- `SNAPSHOT_HISTORY_MANAGER_GENERATED_OK`
- `SNAPSHOT_HISTORY_MANAGER_GENERATED_WITH_WARNINGS`

## Operating Guidance

Use this utility only after reviewing the dashboard, data quality summary,
integrity guard, and snapshot review page. Prefer dry-run first. Apply only when
the keep dates or snapshot IDs are known-good and have been checked by the
operator.
