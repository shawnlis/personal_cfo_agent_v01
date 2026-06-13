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
- `CFO_ACCOUNT_HASH_SALT`

Secrets must stay in environment variables only. Do not commit local config, account exports, logs with account data, or generated reports.

## Readiness Check

Run this before starting a live proof:

```powershell
python .\scripts\personal_cfo_agent.py --provider ibkr --readiness-check
```

This validates environment configuration only. It does not import `ibapi`, open a network connection, or write reports.

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

## Output Contract

Successful live reads use the existing normalized asset ledger schema and provider sync summary. Raw account IDs are not written to outputs; `account_id_hash` is used instead.
