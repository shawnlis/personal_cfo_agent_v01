# Local Workbench v0.6.6

v0.6.6 adds a static local workbench launcher for day-to-day Personal CFO use.

The workbench is not a data processor. It does not read private values, call
brokers, or refresh data. It only points to the expected local files and safe
commands so the workflow is less dependent on remembering paths.

## Command

```powershell
python .\scripts\personal_cfo_agent.py `
  --local-workbench `
  --input-file .\private_inputs\personal_cfo_input.local.json `
  --refresh-dir .\reports\personal_cfo_agent\net_worth_refresh_local `
  --fx-rates-file .\private_inputs\fx_rates.local.json `
  --dashboard-dir .\reports\personal_cfo_agent\dashboard_current `
  --out-dir .\reports\personal_cfo_agent\local_workbench
```

## Outputs

- `local_workbench_summary.json`
- `LOCAL_WORKBENCH_V066.html`
- `LOCAL_WORKBENCH_V066.md`

The HTML is static and local. It contains no external JavaScript, CSS, fetch,
upload, XHR, or beacon behavior. When existing dashboard or snapshot-review
HTML files are present, it links to them with local `file://` links.

## What It Checks

The workbench reports presence only:

- unified private input file present yes/no
- refresh directory present yes/no
- FX rates file present yes/no
- current Dashboard v4 HTML present yes/no
- snapshot review HTML present yes/no
- doctor summary present yes/no

It does not inspect or print exact NAV, balances, positions, raw account IDs,
private input values, `.env.local` values, API keys, tokens, or secrets.

## Warning Codes

- `LOCAL_WORKBENCH_INPUT_MISSING`
- `LOCAL_WORKBENCH_REFRESH_MISSING`
- `LOCAL_WORKBENCH_FX_MISSING`
- `LOCAL_WORKBENCH_GENERATED_OK`
- `LOCAL_WORKBENCH_GENERATED_WITH_WARNINGS`

## Boundaries

The workbench is offline only. It must not run broker reads, Webull token
preflight, Moomoo discovery, account diagnostics, browser automation, external
uploads, trading, cash movement, tax filing, or recommendation output.
