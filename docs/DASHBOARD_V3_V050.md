# Personal CFO Dashboard v3 v0.5.0

Dashboard v3 is an offline integrated net worth dashboard over already-generated Personal CFO outputs.

It does not connect to brokers, banks, CPF, IRAS, HDB, SingPass, browsers, or external accounts. It does not perform market execution, move cash, file taxes, create action instructions, or create scheduler jobs.

## Command

```powershell
python .\scripts\personal_cfo_agent.py `
  --dashboard-v3 `
  --merge-dir .\reports\personal_cfo_agent\merged_v033_fixture `
  --dashboard-dir .\reports\personal_cfo_agent\dashboard_v040_fixture `
  --snapshot-dir .\reports\personal_cfo_agent\snapshots_v042_fixture `
  --property-mortgage-dir .\reports\personal_cfo_agent\property_mortgage_v043_fixture `
  --sg-snapshot-dir .\reports\personal_cfo_agent\sg_snapshot_v044_fixture `
  --fx-rates-input .\reports\personal_cfo_agent\fx_rates_local.json `
  --out-dir .\reports\personal_cfo_agent\dashboard_v050_fixture
```

## Inputs

- v0.3.3 merged account NAV ledger: primary account/provider NAV layer.
- v0.4.0 Dashboard v2 summary: supporting account/provider dashboard context.
- v0.4.2 snapshot history: primary net worth history layer.
- v0.4.3 property/mortgage snapshot: optional offline manual property and liability layer.
- v0.4.4 Singapore manual snapshot: optional offline manual CPF, SRS, tax review, and HDB loan availability layer.

Property and Singapore manual layers are optional. Missing optional layers generate warnings rather than failing the dashboard. Missing snapshot history fails closed because Dashboard v3 is history-first.

Mixed-currency top-level net worth requires an explicit local FX rates JSON. Without FX rates, Dashboard v3 still writes review outputs and native-currency drilldowns, but it fails closed for mixed-currency total net worth instead of silently summing USD, HKD, SGD, or unknown-currency rows.

FX rates use this local JSON shape:

```json
{
  "base_currency": "SGD",
  "rates": {
    "SGD": "1.00",
    "USD": "1.30",
    "HKD": "0.16"
  }
}
```

Rates are local review inputs. They are not fetched automatically, and generated/private real-rate files should stay ignored.

## Outputs

Dashboard v3 writes these files under the requested ignored `reports/` output path:

- `PERSONAL_CFO_DASHBOARD_V050.md`
- `PERSONAL_CFO_DASHBOARD_V050.html`
- `dashboard_v050_summary.json`
- `net_worth_progress.csv`
- `net_worth_history_chart.svg`
- `balance_sheet_summary.csv`
- `asset_liability_breakdown.csv`
- `dashboard_v050_warnings.md`

## Sections

The dashboard includes a CFO cockpit, data source layer status, freshness panel, net worth progress, provider/account NAV summary, balance sheet breakdown, property/mortgage review, Singapore manual snapshot review, warning summary, and position/property/CPF/SRS drilldown counts.

Dashboard v3 also writes a static local SVG chart, `net_worth_history_chart.svg`, and embeds it in the static HTML report. The chart uses the integrated net worth value when available, otherwise it falls back to account NAV history. It does not load external JavaScript, CSS, fonts, or data.

The v0.5.2 readability pass keeps the existing output filenames and core data semantics. It improves the Markdown and static HTML reports so a local review can quickly distinguish:

- Primary local layers: merged account NAV, Dashboard v2 summary, and snapshot history.
- Manual or fixture review layers: property/mortgage and Singapore CPF/SRS/tax/HDB snapshots.
- Review-required warning state and stale/missing layer signals.
- Linked mortgage context versus extra unlinked liabilities, without changing account NAV or snapshot history semantics.

The HTML report remains static/local and dependency-light. It does not load remote assets, upload data, or require a browser automation workflow.

## Local Private Inputs

v0.5.3 adds a local private input kit for preparing real manual property/mortgage and Singapore CPF/SRS/tax/HDB input files without committing them. Use `docs/LOCAL_PRIVATE_INPUT_KIT_V053.md` to initialize ignored local templates, edit them locally, validate them without printing private values, and run the offline manual snapshot chain before feeding those generated layers into Dashboard v3.

## Warning Codes

- `DASHBOARD_V3_INPUT_MISSING`
- `DASHBOARD_V3_MERGE_LEDGER_MISSING`
- `DASHBOARD_V3_SNAPSHOT_HISTORY_MISSING`
- `DASHBOARD_V3_SNAPSHOT_HISTORY_EMPTY`
- `DASHBOARD_V3_DASHBOARD_V2_SUMMARY_MISSING`
- `DASHBOARD_V3_PROPERTY_SNAPSHOT_MISSING`
- `DASHBOARD_V3_SG_SNAPSHOT_MISSING`
- `DASHBOARD_V3_MIXED_CURRENCY_NAV`
- `DASHBOARD_V3_FX_RATE_MISSING`
- `DASHBOARD_V3_FX_NORMALIZATION_APPLIED`
- `DASHBOARD_V3_REVIEW_REQUIRED`
- `DASHBOARD_V3_GENERATED_OK`
- `DASHBOARD_V3_GENERATED_WITH_WARNINGS`

## Boundaries

Dashboard v3 is reporting only. It must not include raw account IDs, NRIC, FIN, raw government identifiers, raw property addresses, secrets, or generated real reports in Git. `account_id_hash`, property hashes, loan hashes, availability flags, counts, and synthetic fixture values are allowed. The dashboard must not create action instructions or tax filing output.

## Dashboard v4 Follow-On

v0.6.0 Dashboard v4 consumes the v0.5.9 refresh directory that includes Dashboard v3 outputs. It adds asset bucket visualization, explicit local FX handling, withdrawal cashflow calculations, and bucketed net worth history charts. See `docs/DASHBOARD_V4_V060.md`.
