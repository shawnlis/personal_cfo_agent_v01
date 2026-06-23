# Data Quality Summary v0.6.4

v0.6.4 adds a redacted data-quality report to `--run-net-worth-refresh`.

The report explains what data was available in a refresh without printing exact
NAV, balances, positions, account IDs, private input values, or secrets.

## Command

Data quality outputs are generated automatically by:

```powershell
python .\scripts\personal_cfo_agent.py `
  --run-net-worth-refresh `
  --refresh-brokers none `
  --input-file .\private_inputs\personal_cfo_input.local.json `
  --out-dir .\reports\personal_cfo_agent\net_worth_refresh_local
```

They are also generated when supervised broker refresh is explicitly requested.
Broker failures are reported as quality warnings rather than hidden.

## Outputs

The refresh output directory now includes:

- `data_quality_summary.json`
- `data_quality_warnings.md`
- `DATA_QUALITY_SUMMARY_V064.md`

## Summary Fields

The JSON report includes redacted statuses and counts only:

- providers requested
- providers succeeded
- providers failed
- provider gate rows with requested/succeeded/failed/status
- source provenance rows for manual, broker, pending snapshot, explicit FX,
  dashboard, and integrity-guard layers
- manual layer availability
- account NAV row count
- position row count
- snapshot generated yes/no
- FX file present yes/no
- FX complete yes/no
- stale or mixed-date warning codes
- dashboard generated yes/no
- source warning codes
- human-readable warning details
- data quality warning codes

## Warning Codes

- `DATA_QUALITY_REFRESH_INCOMPLETE`
- `DATA_QUALITY_BROKER_FAILURES`
- `DATA_QUALITY_FX_INCOMPLETE`
- `DATA_QUALITY_STALE_OR_MIXED_DATES`
- `DATA_QUALITY_GENERATED_OK`
- `DATA_QUALITY_GENERATED_WITH_WARNINGS`

## Safety Boundary

Data quality reporting is offline reporting only. It must not run broker/API
reads, Webull token preflight, Moomoo discovery, browser automation, external
uploads, trading, cash movement, or recommendations.

It must not include exact NAV, balances, positions, raw account IDs, private
input contents, `.env.local` values, API keys, tokens, or secrets.
