# Local Net Worth Refresh v0.5.9

v0.5.9 adds a repeatable local refresh command for the Personal CFO workflow.

It does not change provider adapter semantics. It orchestrates existing modules in a fixed order:

1. Convert one unified private input center JSON into manual layers.
2. Optionally run explicitly approved read-only broker refreshes.
3. Merge provider bundles into account NAV.
4. Record a snapshot history row.
5. Generate Dashboard v3 and its static net worth history chart.

## Local Input Form

Generate the local HTML form:

```powershell
python .\scripts\personal_cfo_agent.py `
  --private-input-center-form `
  --out-dir .\reports\personal_cfo_agent\private_input_center_local
```

Open `personal_cfo_input_form.html` locally. The form is intentionally compact:

- one global snapshot date
- one base currency
- manual NAV for Syfe Trade, Webull, uSMART, and other manual accounts
- property value and mortgage balance
- CPF and SRS totals
- tax year of assessment
- HDB loan availability

The form can preview, download, or save `personal_cfo_input.local.json` locally. It has no external script, stylesheet, network request, beacon, or remote data dependency. Raw account IDs, raw account numbers, NRIC/FIN, raw addresses, and government identifiers are not requested.

## Manual-Only Offline Refresh

Use this when you want to test the chain without broker reads:

```powershell
python .\scripts\personal_cfo_agent.py `
  --run-net-worth-refresh `
  --refresh-brokers none `
  --input-file .\private_inputs\personal_cfo_input.local.json `
  --out-dir .\reports\personal_cfo_agent\net_worth_refresh_local
```

This writes:

- `manual_layers/`
- `provider_inputs/manual_nav/`
- `merged/`
- `snapshots/`
- `dashboard/`
- `data_quality_summary.json`
- `data_quality_warnings.md`
- `DATA_QUALITY_SUMMARY_V064.md`

## Read-Only Broker Refresh

Broker refresh is never implicit. To include existing supervised read-only broker adapters, use:

```powershell
python .\scripts\personal_cfo_agent.py `
  --run-net-worth-refresh `
  --allow-live-read `
  --refresh-brokers ibkr,moomoo,tiger `
  --input-file .\private_inputs\personal_cfo_input.local.json `
  --out-dir .\reports\personal_cfo_agent\net_worth_refresh_live
```

This requires local broker config to be present and uses only the existing read-only provider paths. If a requested broker returns no provider bundle, the command generates whatever offline outputs it safely can, records warning codes, and exits non-zero so the refresh is not mistaken for a clean live result.

## Dashboard History Chart

Dashboard v3 now writes:

- `net_worth_progress.csv`
- `net_worth_history_chart.svg`

The SVG is static/local and is embedded in `PERSONAL_CFO_DASHBOARD_V050.html`. It charts integrated net worth where available, otherwise account NAV history.

## Warning Codes

- `NET_WORTH_REFRESH_GENERATED_OK`
- `NET_WORTH_REFRESH_GENERATED_WITH_WARNINGS`
- `NET_WORTH_REFRESH_FAILED`
- `NET_WORTH_REFRESH_LIVE_READ_SKIPPED`
- `NET_WORTH_REFRESH_BROKER_READ_FAILED`

Underlying modules may also surface provider, merge, snapshot, dashboard, private input, property/mortgage, Singapore snapshot, and manual NAV warning codes.

## Data Quality Summary

v0.6.4 adds a redacted data-quality summary to every net worth refresh. It
records provider success/failure status, manual layer availability, row counts,
snapshot generation status, FX completeness, and dashboard generation status.

It does not include exact NAV, balances, positions, raw account IDs, private
input values, `.env.local` values, API keys, tokens, or secrets.

## Boundaries

This workflow must not print private values, raw account IDs, credentials, secrets, raw addresses, NRIC/FIN, or government identifiers. Generated outputs stay under ignored `reports/` paths. Private inputs stay under ignored local paths such as `private_inputs/`.

It must not place orders, move cash, file taxes, create scheduler jobs, use browser automation, or create recommendations.
