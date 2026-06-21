# Local Net Worth Doctor v0.6.2

`--net-worth-doctor` is a local-only health check for the Personal CFO workflow. It
does not connect to brokers, banks, CPF, IRAS, HDB, SingPass, Webull token flows,
browser automation, or external accounts.

## Command

```powershell
python .\scripts\personal_cfo_agent.py `
  --net-worth-doctor `
  --input-file .\private_inputs\personal_cfo_input.local.json `
  --refresh-dir .\reports\personal_cfo_agent\net_worth_refresh_local `
  --fx-rates-file .\private_inputs\fx_rates.local.json `
  --out-dir .\reports\personal_cfo_agent\net_worth_doctor_v062_local
```

## What It Checks

- Unified private input center file presence and schema validity.
- Refresh directory presence and required output files.
- FX rates file presence and coverage for SGD, USD, CNY, and currencies found in
  the merged account NAV ledger.
- Broker configuration presence from environment variables, redacted to yes/no
  status only.

The doctor may load `.env.local` through the existing local environment loader,
but it never prints values.

## Outputs

All outputs are written under the requested ignored reports directory:

- `net_worth_doctor_summary.json`
- `net_worth_doctor_warnings.md`
- `NET_WORTH_DOCTOR_V062.md`

## Warning Codes

- `NET_WORTH_DOCTOR_INPUT_MISSING`
- `NET_WORTH_DOCTOR_INPUT_INVALID`
- `NET_WORTH_DOCTOR_REFRESH_MISSING`
- `NET_WORTH_DOCTOR_REFRESH_INCOMPLETE`
- `NET_WORTH_DOCTOR_FX_MISSING`
- `NET_WORTH_DOCTOR_FX_INCOMPLETE`
- `NET_WORTH_DOCTOR_BROKER_CONFIG_MISSING`
- `NET_WORTH_DOCTOR_GENERATED_OK`
- `NET_WORTH_DOCTOR_GENERATED_WITH_WARNINGS`

## Safety Boundary

The doctor is a diagnostic report only. It must not run provider refresh,
readiness checks, Webull token preflight, Moomoo discovery, broker diagnostics,
live reads, trading, cash movement, browser automation, or external uploads.

The report must not include exact NAV, balances, positions, raw account IDs,
private input values, `.env.local` values, API keys, tokens, or secrets.
