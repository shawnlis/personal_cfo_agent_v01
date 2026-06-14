# Tiger Read-Only Live-Read Setup

Personal CFO Agent v0.3.1 includes a supervised TigerOpen read-only proof harness. It remains off by default.

## Safety Boundary

- TigerOpen must be configured locally by the operator.
- Live sync requires `--provider tiger --allow-live-read`.
- Readiness checks validate environment configuration only and do not connect to TigerOpen.
- Connection diagnostics check local SDK/config readiness without printing config values.
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

## Connection Diagnostics

Run this after readiness and before any supervised live attempt:

```powershell
python .\scripts\personal_cfo_agent.py --provider tiger --connection-diagnostics
```

The diagnostics output is redacted. It reports only presence and yes/no status for:

- Tiger provider enabled.
- Config directory configured.
- Config directory exists.
- Config file exists.
- Account configured.
- Account hash salt configured.
- `tigeropen` import status.
- Warning codes.

Do not proceed to live read unless diagnostic warning codes are `None`.

## Supervised Live Proof

After TigerOpen is configured locally:

```powershell
python .\scripts\personal_cfo_agent.py `
  --provider tiger `
  --allow-live-read `
  --tiger-data-diagnostics `
  --out-dir .\reports\personal_cfo_agent\tiger_v031_live_acceptance
```

The CLI prints:

```text
Read-only Tiger sync only. No order methods are exposed.
```

If `tigeropen` is not installed, the provider fails closed with `SDK_NOT_INSTALLED`. If the local configuration cannot initialize the client, it fails closed with `PROVIDER_CONNECTION_FAILED`. If read requests fail, it reports `PROVIDER_FETCH_FAILED`.

With `--tiger-data-diagnostics`, the CLI prints only redacted data-path diagnostics:

- SDK import status.
- Local config/client load status.
- Account context observed yes/no.
- Selected account hash.
- Account count redacted.
- Asset query attempted/success.
- Position query attempted/success.
- Position count.
- Cash currency count.
- Normalized rows.
- Warning codes.
- Sanitized stage failures.

## Output Contract

Successful live reads use the existing normalized asset ledger schema and provider sync summary. Raw account IDs are not written to outputs; `account_id_hash` is used instead.

## v0.3.1 Status

On the first v0.3.1 setup pass, `tigeropen` imported successfully and readiness passed. After pointing `CFO_TIGER_CONFIG_DIR` at the directory containing the local TigerOpen properties file, connection diagnostics passed with no warning codes.

The supervised live read was then attempted once. It failed closed during TigerOpen config/client initialization with `PROVIDER_CONNECTION_FAILED`. No asset query, position query, cash query, normalized rows, or report bundle was produced.
