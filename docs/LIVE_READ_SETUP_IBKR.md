# IBKR Read-Only Live-Read Setup

Personal CFO Agent v0.1.1 adds a supervised IBKR read-only proof harness. It remains off by default.

## Safety Boundary

- TWS or IB Gateway must be started manually by the operator.
- Live sync requires `--provider ibkr --allow-live-read`.
- Readiness checks do not connect to TWS or IB Gateway.
- No order, preview, modify, cancel, submit, cash-transfer, or withdrawal methods are exposed on the provider object.
- First live read should be supervised.
- Generated outputs may contain sensitive financial information and must remain under ignored `reports/` paths.

## Environment Variables

Required for readiness or live sync:

- `CFO_IBKR_ENABLED=true`
- `CFO_IBKR_HOST`
- `CFO_IBKR_PORT`
- `CFO_IBKR_CLIENT_ID`

Optional:

- `CFO_IBKR_ACCOUNT`
- `CFO_IBKR_SESSION_TYPE=gateway` or `CFO_IBKR_SESSION_TYPE=tws`
- `CFO_ACCOUNT_HASH_SALT`

Secrets must stay in environment variables only. Do not commit local config, account exports, logs with account data, or generated reports.

## TWS vs IB Gateway

The adapter uses the official IB API socket client and is compatible with either
TWS or IB Gateway when the local host, port, and client ID match the manually
started session. `CFO_IBKR_SESSION_TYPE` is optional, but setting it helps the
redacted diagnostics identify likely port/session mismatches without printing the
actual port value.

Typical local port classes:

- IB Gateway paper: `4002`
- IB Gateway live: `4001`
- TWS paper: `7497`
- TWS live: `7496`

If connection diagnostics show the TCP socket is reachable but data-path
diagnostics later report `IBKR_API_HANDSHAKE_NOT_COMPLETED`,
`IBKR_GATEWAY_CALLBACK_TIMEOUT`, or
`IBKR_GATEWAY_API_SETTINGS_REVIEW_REQUIRED`, review the local TWS or Gateway API
settings: socket clients enabled, read-only API access enabled, trusted local IP
allowed, no modal login/API prompt pending, and no client-ID collision with
another API session.

## Readiness Check

Run this before starting a live proof:

```powershell
python .\scripts\personal_cfo_agent.py --provider ibkr --readiness-check
```

This validates environment configuration only. It does not import `ibapi`, open a network connection, or write reports.

## Local SDK Dependency

IBKR live-read proof requires the local Python package `ibapi`:

```powershell
python -m pip install ibapi
```

Do not commit virtualenv folders, user site-packages, broker SDK caches, account exports, or generated report outputs. Installing `ibapi` does not bypass the live-read gates: `.env.local` or OS environment configuration, manually started TWS or IB Gateway, API access enabled in TWS or Gateway, explicit `--provider ibkr`, and explicit `--allow-live-read` are still required.

## Redacted Connection Diagnostics

Before a live-read attempt, run:

```powershell
python .\scripts\personal_cfo_agent.py --provider ibkr --connection-diagnostics
```

Diagnostics report only redacted presence, Python executable, `ibapi` import status, TCP socket reachability, and warning codes. They do not print host, port, client ID, account ID, salts, or `.env.local` values. The TCP probe opens a socket only and sends no IBKR API messages.

Diagnostics also report a redacted session type category and port class, such as
`gateway_paper_port` or `tws_live_port`, plus
`IBKR_PORT_SESSION_TYPE_MISMATCH` when `CFO_IBKR_SESSION_TYPE` conflicts with the
known port class. The exact port value is not printed.

## Supervised Live Proof

After manually starting TWS or IB Gateway:

```powershell
python .\scripts\personal_cfo_agent.py --provider ibkr --allow-live-read --out-dir .\reports\personal_cfo_agent\ibkr_v011_live_smoke
```

The CLI prints:

```text
Read-only IBKR sync only. No order methods are exposed.
```

If `ibapi` is not installed, the provider fails closed with `SDK_NOT_INSTALLED`. If TWS or IB Gateway is not reachable, it fails closed with `PROVIDER_CONNECTION_FAILED`. If read requests fail or time out, it reports `PROVIDER_FETCH_FAILED`.

IBKR supervised live reads are isolated in a short-lived local subprocess. This
prevents a stuck TWS or IB Gateway callback loop from hanging the main CLI. If
the child process does not return before the hard timeout, the parent process
terminates it and returns an empty, redacted provider snapshot with
`PROVIDER_FETCH_FAILED`, `IBKR_CALLBACK_TIMEOUT`, and handshake or Gateway review
warnings where applicable. No order, transfer, or account-write APIs are called
by this watchdog path.

## Redacted Data-Path Diagnostics

When TWS or IB Gateway is reachable but no rows are returned, run one supervised diagnostic read:

```powershell
python .\scripts\personal_cfo_agent.py `
  --provider ibkr `
  --allow-live-read `
  --ibkr-data-diagnostics `
  --out-dir .\reports\personal_cfo_agent\ibkr_v021_live_acceptance
```

This mode still requires all live-read gates and still prints the read-only warning. It reports only redacted data-path state:

- socket connection observed
- session type category
- API handshake observed
- managed-accounts callback observed and redacted count
- requested account hash and whether that account was observed
- positions callback observed and row count
- account-summary callback observed and cash currency count
- timeout seconds
- diagnostic warning codes

It does not print raw account IDs, balances, host, port, client ID, salts, passwords, or local environment values.

Zero-row outcomes are not accepted as a successful live proof unless the diagnostic state explains them safely. Common causes include TWS or IB Gateway not fully authorizing the API session, no managed accounts returned, a configured account filter that does not match the managed-account list, callbacks timing out, or account-summary and position callbacks completing with no rows.

## Output Contract

Successful live reads use the existing normalized asset ledger schema and provider sync summary. Raw account IDs are not written to outputs; `account_id_hash` is used instead.
