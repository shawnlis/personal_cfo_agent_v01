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
-> snapshot history
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

## Manual-Only Net Worth Refresh

```powershell
python .\scripts\personal_cfo_agent.py `
  --run-net-worth-refresh `
  --refresh-brokers none `
  --input-file .\private_inputs\personal_cfo_input.local.json `
  --out-dir .\reports\personal_cfo_agent\net_worth_refresh_local
```

Manual-only mode does not run broker reads.

The refresh also writes a redacted data quality summary:

- `data_quality_summary.json`
- `data_quality_warnings.md`
- `DATA_QUALITY_SUMMARY_V064.md`

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

## Safe Output Review

Inspect generated files locally. Do not paste raw report contents into PRs or
docs when they contain real private values.

Useful output folders:

- `manual_layers/`
- `provider_inputs/`
- `merged/`
- `snapshots/`
- `dashboard/`

Useful summary files:

- `merged/merged_account_nav_summary.json`
- `snapshots/snapshot_manifest.json`
- `dashboard/dashboard_v050_summary.json`
- `dashboard/dashboard_v060_summary.json`
- `data_quality_summary.json`
- `net_worth_doctor_summary.json`

## Validation

The main validation gate is:

```powershell
$env:PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION='python'
python .\scripts\dev_validate.py
```

Generated reports and private inputs must remain ignored.
