# Moomoo Read-Only Live-Read Setup

Personal CFO Agent v0.1.2 adds a supervised Moomoo / Futu OpenD read-only proof harness. It remains off by default.

## Safety Boundary

- OpenD must be started manually by the operator.
- Live sync requires `--provider moomoo --allow-live-read`.
- Readiness checks do not connect to OpenD.
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

## Supervised Live Proof

After manually starting OpenD:

```powershell
python .\scripts\personal_cfo_agent.py --provider moomoo --allow-live-read --out-dir .\reports\personal_cfo_agent\moomoo_v012_live_smoke
```

The CLI prints:

```text
Read-only Moomoo sync only. No order methods are exposed.
```

If `futu` is not installed, the provider fails closed with `SDK_NOT_INSTALLED`. If OpenD is not reachable, it fails closed with `PROVIDER_CONNECTION_FAILED`. If read requests fail, it reports `PROVIDER_FETCH_FAILED`.

## Output Contract

Successful live reads use the existing normalized asset ledger schema and provider sync summary. Raw account IDs are not written to outputs; `account_id_hash` is used instead.
