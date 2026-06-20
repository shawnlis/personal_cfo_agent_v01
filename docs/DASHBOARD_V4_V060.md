# Personal CFO Dashboard v4 v0.6.0

Dashboard v4 is an offline visual reporting layer over a completed v0.5.9 local net worth refresh directory.

It reads already-generated local files only. It does not connect to brokers, banks, CPF, IRAS, HDB, SingPass, browsers, or external accounts. It does not move cash, file taxes, create scheduler jobs, or create action instructions.

## Command

```powershell
python .\scripts\personal_cfo_agent.py `
  --dashboard-v4 `
  --refresh-dir .\reports\personal_cfo_agent\net_worth_refresh_v059_finalize `
  --fx-rates-file .\tmp\fx_rates_v060_fixture.json `
  --out-dir .\reports\personal_cfo_agent\dashboard_v060_fixture
```

## Input Contract

`--refresh-dir` must point to a v0.5.9 refresh output with these local subfolders:

- `merged/`
- `snapshots/`
- `dashboard/`
- `manual_layers/property_mortgage/`
- `manual_layers/sg_retirement_tax/`

Dashboard v4 uses:

- merged account NAV as the liquid investment asset layer
- property equity summary as the fixed asset layer
- CPF and SRS snapshot ledgers as the retirement account layer
- snapshot and Dashboard v3 history outputs for bucketed net worth history

The property and Singapore manual layers remain offline/manual layers. Missing or unclear values are surfaced as review warnings rather than silently filled.

## FX Rates

Dashboard v4 never fetches FX rates. Mixed-currency aggregation requires an explicit local JSON file:

```json
{
  "base_currency": "SGD",
  "rates_to_base": {
    "SGD": "1.00",
    "USD": "1.30",
    "HKD": "0.16",
    "CNY": "0.18"
  }
}
```

If required FX rates are missing, Dashboard v4 keeps native-currency totals and emits `DASHBOARD_V4_FX_RATES_MISSING` plus `DASHBOARD_V4_FX_CONVERSION_SKIPPED`.

## Outputs

Dashboard v4 writes these files under the requested ignored `reports/` output path:

- `PERSONAL_CFO_DASHBOARD_V060.md`
- `PERSONAL_CFO_DASHBOARD_V060.html`
- `dashboard_v060_summary.json`
- `asset_bucket_summary.csv`
- `liquid_withdrawal_cashflow.csv`
- `net_worth_bucket_history.csv`
- `dashboard_v060_warnings.md`
- `asset_bucket_chart.svg`
- `withdrawal_cashflow_chart.svg`
- `net_worth_bucket_history_chart.svg`

The HTML and SVG outputs are static/local. They do not load external JavaScript, remote CSS, remote fonts, uploaded data, or web services.

## Sections

Dashboard v4 focuses on visual readability:

- CFO cockpit
- fixed assets, retirement accounts, liquid investment assets, and review bucket
- explicit FX status
- liquid-asset withdrawal cashflow ladder at 3.0%, 3.5%, and 4.0%
- bucketed net worth history
- review queue for unclassified assets and missing FX

The withdrawal cashflow rows are deterministic calculations from the liquid investment asset bucket only. They are planning math for local review, not recommendations.

## Warning Codes

- `DASHBOARD_V4_INPUT_MISSING`
- `DASHBOARD_V4_BUCKET_CLASSIFICATION_WARNING`
- `DASHBOARD_V4_UNCLASSIFIED_ASSETS`
- `DASHBOARD_V4_FX_RATES_MISSING`
- `DASHBOARD_V4_FX_CONVERSION_SKIPPED`
- `DASHBOARD_V4_BUCKET_HISTORY_LIMITED`
- `DASHBOARD_V4_WITHDRAWAL_CASHFLOW_GENERATED`
- `DASHBOARD_V4_GENERATED_OK`
- `DASHBOARD_V4_GENERATED_WITH_WARNINGS`

## Boundaries

Dashboard v4 is reporting only. It must not include raw account IDs, NRIC, FIN, raw government identifiers, raw property addresses, credentials, private input contents, or generated real reports in Git.

Generated reports stay ignored under `reports/`. Local FX files with real rates should stay local or ignored.
