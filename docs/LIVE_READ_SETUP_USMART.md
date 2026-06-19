# uSMART Read-Only Setup

v0.5.7 is feasibility/readiness only. It does not perform uSMART live API calls.

uSMART API surfaces may include trading, account, asset, and position services. This project therefore treats uSMART as disabled by default and only supports redacted local readiness checks until a future separately approved supervised read-only live proof.

## Local Configuration Placeholders

```text
CFO_USMART_ENABLED=false
CFO_USMART_API_KEY=
CFO_USMART_API_SECRET=
CFO_USMART_API_HOST=
CFO_USMART_SDK_MODULE=
```

`CFO_USMART_SDK_MODULE` is optional. It lets the readiness check test a locally installed SDK module name without importing unrelated packages. The default readiness probe tries plausible uSMART SDK module names, but it never constructs a client and never sends an API request.

Do not commit real values. Do not print real values in docs, logs, PR bodies, or reports.

## Readiness Check

```powershell
python .\scripts\personal_cfo_agent.py --provider usmart --readiness-check
```

This command checks only local enabled/config presence and SDK importability. It does not connect to uSMART and does not read account, cash, asset, or position data.

Expected statuses:

- `PROVIDER_DISABLED`
- `PROVIDER_CONFIG_MISSING`
- `SDK_NOT_INSTALLED`
- `USMART_READINESS_OK`

## Connection Diagnostics

```powershell
python .\scripts\personal_cfo_agent.py --provider usmart --connection-diagnostics
```

Diagnostics are redacted and offline. They report whether expected config keys are present, whether SDK import succeeded, and whether a live connection was attempted. The live connection attempted field must remain `no` in v0.5.7.

## Explicitly Not Implemented

v0.5.7 does not:

- connect to uSMART
- read accounts, balances, assets, cash, positions, orders, or history
- submit or preview execution instructions
- modify or cancel execution instructions
- transfer, withdraw, or move cash
- store credentials
- print API keys, secrets, tokens, account IDs, or `.env.local` values

Future live read requires separate approval, a new supervised acceptance task, redacted diagnostics, mocked tests, and explicit `--allow-live-read` gating.
