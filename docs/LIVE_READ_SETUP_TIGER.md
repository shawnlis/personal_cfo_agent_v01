# Tiger Read-Only Live-Read Setup

Personal CFO Agent v0.1.3 adds a supervised TigerOpen read-only proof harness. It remains off by default.

## Safety Boundary

- TigerOpen must be configured locally by the operator.
- Live sync requires `--provider tiger --allow-live-read`.
- Readiness checks validate environment configuration only and do not connect to TigerOpen.
- No order, preview, modify, cancel, submit, cash-transfer, or withdrawal methods are exposed on the provider object.
- First live read should be supervised.
- Generated outputs may contain sensitive financial information and must remain under ignored `reports/` paths.

## Environment Variables

Required for readiness or live sync:

- `CFO_TIGER_ENABLED=true`
- `CFO_TIGER_CONFIG_DIR`
- `CFO_TIGER_ACCOUNT`

Optional:

- `CFO_ACCOUNT_HASH_SALT`

Secrets and local TigerOpen configuration must stay outside Git. Do not commit local config, account exports, logs with account data, or generated reports.

## Readiness Check

Run this before starting a live proof:

```powershell
python .\scripts\personal_cfo_agent.py --provider tiger --readiness-check
```

This validates environment configuration only. It does not import `tigeropen`, open a network connection, or write reports.

## Supervised Live Proof

After TigerOpen is configured locally:

```powershell
python .\scripts\personal_cfo_agent.py --provider tiger --allow-live-read --out-dir .\reports\personal_cfo_agent\tiger_v013_live_smoke
```

The CLI prints:

```text
Read-only Tiger sync only. No order methods are exposed.
```

If `tigeropen` is not installed, the provider fails closed with `SDK_NOT_INSTALLED`. If the local configuration cannot initialize the client, it fails closed with `PROVIDER_CONNECTION_FAILED`. If read requests fail, it reports `PROVIDER_FETCH_FAILED`.

## Output Contract

Successful live reads use the existing normalized asset ledger schema and provider sync summary. Raw account IDs are not written to outputs; `account_id_hash` is used instead.
