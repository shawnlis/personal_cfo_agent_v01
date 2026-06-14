# Moomoo Read-Only Live-Read Setup

Personal CFO Agent v0.3.0 adds a supervised Moomoo / Futu OpenD read-only proof harness with redacted connection and data-path diagnostics. It remains off by default.

## Safety Boundary

- OpenD must be started manually by the operator.
- Live sync requires `--provider moomoo --allow-live-read`.
- Readiness checks do not connect to OpenD.
- Connection diagnostics are explicit and redacted; they do not send live read requests.
- No order, preview, modify, cancel, submit, cash-transfer, or withdrawal methods are exposed on the provider object.
- First live read should be supervised.
- Generated outputs may contain sensitive financial information and must remain under ignored `reports/` paths.

## Environment Variables

Required for readiness or live sync:

- `CFO_MOOMOO_ENABLED=true`
- `CFO_MOOMOO_HOST`
- `CFO_MOOMOO_PORT`

Optional:

- `CFO_ACCOUNT_HASH_SALT`

Secrets must stay in environment variables only. Do not commit local config, account exports, logs with account data, or generated reports.

## Readiness Check

Run this before starting a live proof:

```powershell
python .\scripts\personal_cfo_agent.py --provider moomoo --readiness-check
```

This validates environment configuration only. It does not import `futu`, open a network connection, or write reports.

## Local SDK Dependency

Moomoo live-read proof requires the local Python package for Futu OpenD:

```powershell
python -m pip install futu-api
```

Do not commit virtualenv folders, user site-packages, SDK caches, account exports, or generated report outputs. Installing the SDK does not bypass the live-read gates: `.env.local` or OS environment configuration, manually started OpenD, explicit `--provider moomoo`, and explicit `--allow-live-read` are still required.

## Redacted Connection Diagnostics

Before a supervised live-read attempt, run:

```powershell
python .\scripts\personal_cfo_agent.py --provider moomoo --connection-diagnostics
```

Diagnostics report only redacted presence, Python executable, `futu` import status, OpenD socket reachability, and warning codes. They do not print host, port, salts, account identifiers, balances, or `.env.local` values.

## Supervised Live Proof

After manually starting OpenD:

```powershell
python .\scripts\personal_cfo_agent.py `
  --provider moomoo `
  --allow-live-read `
  --moomoo-data-diagnostics `
  --out-dir .\reports\personal_cfo_agent\moomoo_v030_live_acceptance
```

The CLI prints:

```text
Read-only Moomoo sync only. No order methods are exposed.
```

If `futu` is not installed, the provider fails closed with `MOOMOO_SDK_NOT_INSTALLED` and `SDK_NOT_INSTALLED`. If OpenD is not reachable, it fails closed with `MOOMOO_OPEND_UNREACHABLE` or `PROVIDER_CONNECTION_FAILED`. If read requests fail, it reports `PROVIDER_FETCH_FAILED`.

## Redacted Data-Path Diagnostics

The `--moomoo-data-diagnostics` mode still requires `--allow-live-read`. It reports only redacted data-path state:

- OpenD connection observed
- account-list or equivalent account context observed
- account count redacted
- positions observed and position count
- cash or balance observed and cash currency count
- normalized rows count
- warning codes

It does not print raw account IDs, exact balances, host, port, salts, passwords, screenshots, cookies, or local environment values.

Zero-row outcomes are not accepted as a successful live proof unless the diagnostic state explains them safely.

## Output Contract

Successful live reads use the existing normalized asset ledger schema and provider sync summary. Raw account IDs are not written to outputs; `account_id_hash` is used instead.
