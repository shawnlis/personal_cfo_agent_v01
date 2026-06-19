# Tiger Read-Only Live-Read Setup

Personal CFO Agent v0.3.1 includes a supervised TigerOpen read-only proof harness. It remains off by default.

## Safety Boundary

- TigerOpen must be configured locally by the operator.
- Live sync requires `--provider tiger --allow-live-read`.
- Readiness checks validate environment configuration only and do not connect to TigerOpen.
- Config preflight validates local TigerOpen properties shape without initializing a TigerOpen client.
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
- `CFO_TIGER_BASE_CURRENCY` for read-only reporting when TigerOpen position/cash payloads do not include explicit currency. Use a real account base currency such as `USD`, `HKD`, or `SGD`; do not guess.

Secrets and local TigerOpen configuration must stay outside Git and outside the repository directory. Do not commit local config, account exports, logs with account data, private keys, or generated reports. If a real Tiger config or private key is ever committed, rotate the key before any further live testing.

Expected local config pattern:

- `CFO_TIGER_CONFIG_DIR` should point to an external directory, for example `%USERPROFILE%\tiger_openapi_config`.
- The expected properties filename inside that directory is `tiger_openapi_config.properties`.
- The adapter uses the official TigerOpen directory mode and passes `<CFO_TIGER_CONFIG_DIR>` as TigerOpen `props_path`.
- Do not point `CFO_TIGER_CONFIG_DIR` to the properties file unless a future fallback explicitly supports that.
- Do not use `get_client_config` as the primary adapter path.
- TigerOpen accepts `tiger_id` and `account` properties.
- TigerOpen accepts private-key properties named `private_key_pk1` or `private_key_pk8`; the private-key format must match the field used.
- Current local diagnostics report private-key format category `pkcs1_like`. TigerOpen SDK versions and docs may differ between `private_key_pk1` and `private_key_pk8`; if official directory mode fails, regenerate or export the TigerOpen config according to the current Tiger docs.
- TigerOpen can also use `TIGEROPEN_PRIVATE_KEY` or `private_key_path`, but values must remain local and must not be printed or committed.

Do not put screenshots, config file contents, Tiger IDs, raw account IDs, private keys, tokens, `.env.local` values, or balances in docs or PR comments.

## Readiness Check

Run this before starting a live proof:

```powershell
python .\scripts\personal_cfo_agent.py --provider tiger --readiness-check
```

This validates environment configuration only. It does not import `tigeropen`, open a network connection, or write reports.

## Config Preflight

Run this after readiness and before connection diagnostics or any supervised live attempt:

```powershell
python .\scripts\personal_cfo_agent.py --provider tiger --config-preflight
```

This validates the local config shape without initializing a TigerOpen client, authenticating, calling account APIs, or writing reports. It prints only redacted booleans/categories:

- Expected config filename and pattern.
- Whether `CFO_TIGER_CONFIG_DIR` is configured and points to a directory.
- Whether `tiger_openapi_config.properties` exists and is readable.
- Whether the config file is outside the repository.
- Whether the config file is tracked by Git.
- Whether config-like key files have Git history risk.
- Whether `tiger_id`, account context, and private-key material are present, redacted.
- Private-key format category only: `pkcs1_like`, `pkcs8_like`, `missing`, or `unknown_format`.
- Warning codes such as `TIGER_CONFIG_PREFLIGHT_OK`, `TIGER_CONFIG_FILE_INSIDE_REPO`, or `TIGER_PRIVATE_KEY_FORMAT_UNKNOWN`.

Do not continue to a supervised live attempt if preflight warning codes include `TIGER_CONFIG_PREFLIGHT_FAILED`, `TIGER_CONFIG_FILE_TRACKED`, `TIGER_CONFIG_HISTORY_RISK`, or any missing-key/private-key warning.

## SDK Config Compatibility Probe

Run this after config preflight if TigerOpen config loading or client initialization needs diagnosis:

```powershell
python .\scripts\personal_cfo_agent.py --provider tiger --sdk-config-probe
```

This probe checks TigerOpen SDK config-loading compatibility without account data calls. It does not run a live read, call asset/position/cash APIs, place or preview orders, modify/cancel orders, transfer/withdraw cash, write reports, or print config values.

The probe tests redacted config-loading modes:

- `directory`: `props_path` points at `CFO_TIGER_CONFIG_DIR`.
- `file`: `props_path` points at `<CFO_TIGER_CONFIG_DIR>\tiger_openapi_config.properties`.
- `explicit_props_path`: SDK helper config construction with an explicit `props_path`.
- `sdk_default`: SDK default config loading.

It reports only:

- SDK import status.
- Redacted TigerOpen package path.
- Modes tested and the selected working mode, if any.
- Expected config filename.
- Config file detected yes/no.
- Required-key presence booleans for Tiger ID, account, and private key.
- Private-key format category only.
- SDK config/client construction status.
- Sanitized exception class/category.
- Warning codes.

Do not paste screenshots, config contents, Tiger IDs, raw account IDs, private keys, tokens, `.env.local` values, or balances into docs or PR comments when using the probe.

## Connection Diagnostics

Run this after readiness and config preflight, before any supervised live attempt:

```powershell
python .\scripts\personal_cfo_agent.py --provider tiger --connection-diagnostics
```

The diagnostics output is redacted. It reports only presence and yes/no status for:

- Tiger provider enabled.
- Config directory configured.
- Config directory exists.
- Config file exists.
- Tiger ID configured, redacted.
- Account configured.
- Private key configured, redacted.
- Private key format category, redacted.
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
- Config directory/file status.
- Local config load status.
- Tiger ID/account/private-key presence, redacted.
- Private-key format category, redacted.
- Client init and client auth status.
- Account context observed yes/no.
- Selected account hash.
- Account count redacted.
- Assets query attempted/success.
- Positions query attempted/success.
- Cash query attempted/success.
- Position count.
- Cash currency count.
- Normalized rows.
- Warning codes.
- Sanitized stage failures.

If TigerOpen returns positions without per-row currency and no cash currency rows, downstream account NAV merge cannot safely infer the Tiger base currency. In that case, set `CFO_TIGER_BASE_CURRENCY` locally before the supervised read-only refresh. This value is used only to label read-only normalized rows and account NAV currency; it does not enable orders, transfers, or account writes.

## Output Contract

Successful live reads use the existing normalized asset ledger schema and provider sync summary. Raw account IDs are not written to outputs; `account_id_hash` is used instead.

## v0.3.1 Status

On the first v0.3.1 setup pass, `tigeropen` imported successfully and readiness passed. After pointing `CFO_TIGER_CONFIG_DIR` at the directory containing the local TigerOpen properties file, connection diagnostics passed with no warning codes.

The config preflight command was added to diagnose local properties-file shape before TigerOpen client initialization. The current redacted preflight result is `TIGER_CONFIG_PREFLIGHT_OK`: the config file is outside the repository, untracked, readable, has no detected Git history risk, and reports private-key format category `pkcs1_like`. It does not run a live read and does not call Tiger account APIs.

The SDK config compatibility probe was added after config preflight passed but the prior supervised live attempt failed closed during TigerOpen config load. The probe tests TigerOpen config-loading modes without account, position, cash, order, or transfer calls.

Current redacted probe result:

- Working props path mode: `directory`.
- SDK config constructed: yes.
- SDK client constructed: yes.
- Sanitized exception category: `none`.
- Probe warning codes: `TIGER_SDK_CONFIG_CONSTRUCTED`, `TIGER_SDK_CLIENT_CONSTRUCTED`.
- Account data APIs called by the probe: no.

The adapter now uses official `TigerOpenClientConfig(props_path=<config directory>)` construction as the primary path. It no longer uses the SDK helper path as primary; helper/file modes are fallback-only and are marked in diagnostics when used.

The supervised live read was retried once after official directory-mode config became primary. It succeeded as a supervised read-only proof:

- Config mode selected: `official_directory_props_path`.
- Helper fallback used: no.
- Config constructed: yes.
- Client constructed: yes.
- Account context observed: yes, redacted.
- Account count redacted: 1.
- Position count: 8.
- Cash currency count: 0.
- Normalized rows: 8.
- Warning codes: None.
- Report bundle generated under ignored `reports/personal_cfo_agent/tiger_v031_live_acceptance`.

Generated reports remain local and ignored. Do not commit report contents, exact balances, raw account IDs, `.env.local`, Tiger config, private keys, screenshots, or cookies.
