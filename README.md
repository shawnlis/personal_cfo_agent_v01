# Personal CFO Agent

Local-first Personal CFO tooling for private net worth refreshes, account NAV
normalization, manual asset snapshots, snapshot history, and offline dashboards.

The project is designed for private local use. Generated outputs belong under
ignored `reports/` paths, and real inputs belong under ignored local input paths.
Do not commit real balances, raw account identifiers, private inputs, reports, or
credentials.

## Current Workflow

The current v0.6.x flow is:

```text
unified private input center
+ optional supervised read-only broker refresh
+ manual NAV / property / mortgage / CPF / SRS / tax / HDB layers
-> merged account NAV
-> pending snapshot review
-> integrity guard
-> expected source contract gate
-> confirmed snapshot history after explicit approval
-> snapshot history manager for correcting reviewed history mistakes
-> Dashboard v3 / Dashboard v4
-> local net worth doctor
```

## Initialize The Private Input Center

```powershell
python .\scripts\personal_cfo_agent.py `
  --init-private-input-center `
  --out-file .\private_inputs\personal_cfo_input.local.json

python .\scripts\personal_cfo_agent.py `
  --private-input-center-form `
  --out-dir .\reports\personal_cfo_agent\private_input_center_local
```

Existing local files are not overwritten unless `--overwrite` is passed
explicitly. The generated HTML form is static and local.

## Validate Private Input

```powershell
python .\scripts\personal_cfo_agent.py `
  --validate-private-input-center `
  --input-file .\private_inputs\personal_cfo_input.local.json
```

Validation prints presence, counts, provider labels, currencies, and warning
codes only. It must not print exact private values.

## Expected Source Contract

The unified private input can declare which broker and manual sources are
required for a refresh. Required sources appear in the data quality provider
gate and block confirmed history writes when missing. Optional sources are
reported but do not block history.

The current template includes `expected_sources` with manual NAV required and
IBKR/Moomoo/Tiger optional by default. Edit it locally when a run must include a
specific live broker NAV.

## Manual-Only Net Worth Refresh

```powershell
python .\scripts\personal_cfo_agent.py `
  --run-net-worth-refresh `
  --refresh-brokers none `
  --input-file .\private_inputs\personal_cfo_input.local.json `
  --out-dir .\reports\personal_cfo_agent\net_worth_refresh_local
```

Manual-only mode does not run broker reads.

By default this creates a pending review snapshot under `snapshots/`; it does
not append to confirmed long-term history. After reviewing the dashboard and
data quality summary, rerun with explicit confirmation to write history. The
v0.6.5 integrity guard must also pass before confirmed history is written:

```powershell
python .\scripts\personal_cfo_agent.py `
  --run-net-worth-refresh `
  --refresh-brokers none `
  --confirm-snapshot-history-write `
  --input-file .\private_inputs\personal_cfo_input.local.json `
  --out-dir .\reports\personal_cfo_agent\net_worth_refresh_local
```

Confirmed history is written under `snapshots_confirmed/`.

The refresh also writes a redacted data quality summary:

- `data_quality_summary.json`
- `data_quality_warnings.md`
- `DATA_QUALITY_SUMMARY_V064.md`

It also writes a redacted integrity guard report:

- `integrity_guard/net_worth_integrity_summary.json`
- `integrity_guard/net_worth_integrity_warnings.md`
- `integrity_guard/NET_WORTH_INTEGRITY_GUARD_V065.md`

## Snapshot History Manager

If a bad refresh has already been written to confirmed history, inspect history
offline before applying any cleanup:

```powershell
python .\scripts\personal_cfo_agent.py `
  --snapshot-history-manager `
  --snapshot-dir .\reports\personal_cfo_agent\net_worth_refresh_local\snapshots_confirmed `
  --out-dir .\reports\personal_cfo_agent\snapshot_history_manager_v068_local
```

To prune history, rerun with an explicit keep date or snapshot ID and an explicit
apply flag. The manager creates a backup under the output folder before
rewriting history CSVs:

```powershell
python .\scripts\personal_cfo_agent.py `
  --snapshot-history-manager `
  --snapshot-dir .\reports\personal_cfo_agent\net_worth_refresh_local\snapshots_confirmed `
  --keep-snapshot-date 2026-06-21 `
  --apply-snapshot-history-changes `
  --out-dir .\reports\personal_cfo_agent\snapshot_history_manager_v068_local
```

Snapshot history manager outputs are redacted and documented in
`docs/SNAPSHOT_HISTORY_MANAGER_V068.md`.

## Supervised Read-Only Broker Refresh

Broker refresh is opt-in and must be explicitly approved for the run:

```powershell
python .\scripts\personal_cfo_agent.py `
  --run-net-worth-refresh `
  --allow-live-read `
  --refresh-brokers ibkr,moomoo,tiger `
  --input-file .\private_inputs\personal_cfo_input.local.json `
  --out-dir .\reports\personal_cfo_agent\net_worth_refresh_live
```

This uses only existing read-only provider paths. It must not place orders,
preview orders, modify orders, move cash, unlock trade flows, or print secrets.
Do not add `--confirm-snapshot-history-write` until the generated dashboard has
been reviewed for missing broker rows or warning codes.

## Snapshot Review Gate

Every local net worth refresh now writes a redacted review folder:

- `snapshot_review/snapshot_review_summary.json`
- `snapshot_review/SNAPSHOT_REVIEW_V066.md`
- `snapshot_review/snapshot_review.html`

You can regenerate it directly without running brokers or recomputing the
refresh:

```powershell
python .\scripts\personal_cfo_agent.py `
  --snapshot-review `
  --refresh-dir .\reports\personal_cfo_agent\net_worth_refresh_local `
  --out-dir .\reports\personal_cfo_agent\net_worth_refresh_local\snapshot_review
```

Only write confirmed history after this page says the refresh is ready and the
dashboard has been reviewed.

## Dashboard v4

Dashboard v4 reads an existing refresh directory and optional explicit local FX
rates:

```powershell
python .\scripts\personal_cfo_agent.py `
  --dashboard-v4 `
  --refresh-dir .\reports\personal_cfo_agent\net_worth_refresh_local `
  --fx-rates-file .\private_inputs\fx_rates.local.json `
  --out-dir .\reports\personal_cfo_agent\dashboard_v4_local
```

Dashboard outputs stay under ignored `reports/` paths. HTML and SVG outputs are
static/local.

The current Dashboard v4 cockpit shows total assets and liquid investment assets
first, then source coverage, data quality, integrity status, asset buckets,
withdrawal cashflow, FIRE target math, and bucketed history.

## Local Net Worth Doctor

Use the doctor when you want to check local readiness without any live reads:

```powershell
python .\scripts\personal_cfo_agent.py `
  --net-worth-doctor `
  --input-file .\private_inputs\personal_cfo_input.local.json `
  --refresh-dir .\reports\personal_cfo_agent\net_worth_refresh_local `
  --fx-rates-file .\private_inputs\fx_rates.local.json `
  --out-dir .\reports\personal_cfo_agent\net_worth_doctor_v062_local
```

The doctor checks private input validity, refresh completeness, FX coverage, and
broker config presence as redacted yes/no status only.

## Local Workbench

Use the static workbench as the local entry page for the current input, refresh,
dashboard, doctor, and snapshot review paths:

```powershell
python .\scripts\personal_cfo_agent.py `
  --local-workbench `
  --input-file .\private_inputs\personal_cfo_input.local.json `
  --refresh-dir .\reports\personal_cfo_agent\net_worth_refresh_local `
  --fx-rates-file .\private_inputs\fx_rates.local.json `
  --dashboard-dir .\reports\personal_cfo_agent\dashboard_current `
  --out-dir .\reports\personal_cfo_agent\local_workbench
```

The workbench is a static local launcher. It does not read private values or run
broker refreshes.

## Safe Output Review

Inspect generated files locally. Do not paste raw report contents into PRs or
docs when they contain real private values.

Useful output folders:

- `manual_layers/`
- `provider_inputs/`
- `merged/`
- `snapshots/`
- `dashboard/`
- `snapshot_review/`

Useful summary files:

- `merged/merged_account_nav_summary.json`
- `snapshots/snapshot_manifest.json`
- `integrity_guard/net_worth_integrity_summary.json`
- `dashboard/dashboard_v050_summary.json`
- `dashboard/dashboard_v060_summary.json`
- `data_quality_summary.json`
- `snapshot_review/snapshot_review_summary.json`
- `net_worth_doctor_summary.json`

The stabilization checklist for this local-first workflow is documented in
`docs/LOCAL_WORKFLOW_STABILIZATION_V066.md`.
Expected source contract behavior is documented in
`docs/EXPECTED_SOURCE_CONTRACT_V067.md`.
Snapshot history cleanup is documented in
`docs/SNAPSHOT_HISTORY_MANAGER_V068.md`.
Dashboard/input UX polish is documented in
`docs/DASHBOARD_INPUT_UX_POLISH_V069.md`.

## Validation

The main validation gate is:

```powershell
$env:PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION='python'
python .\scripts\dev_validate.py
```

Generated reports and private inputs must remain ignored.
