# Tiger Supervised Read-Only Live-Read Acceptance v0.3.1

## Purpose

This records the TigerOpen SDK setup and readiness gate for the v0.3.1 supervised read-only proof.

The goal is to prepare Tiger read-only diagnostics without exposing local credentials, account identifiers, account balances, reports, screenshots, cookies, or local SDK configuration content.

## Safety Boundary

- No order placement.
- No order preview.
- No order modification or cancellation.
- No cash transfer or withdrawal.
- No recommendation output.
- No raw account IDs in committed docs.
- No secrets or local TigerOpen config content in committed docs.
- No `.env.local` values in committed docs.
- No generated reports committed.
- No screenshots or cookies committed.

## SDK Check

Commands run:

```powershell
python -m pip install tigeropen
python -c "import tigeropen; print('tigeropen import OK')"
```

Result:

- `tigeropen` package: already installed.
- Import check: OK.

## Local Config Presence Check

Only boolean/redacted checks were printed.

Config hygiene check:

- Tracked Tiger config files: no.
- Tracked `.pem` private-key files: no.
- Tracked `.key` private-key files: no.
- Tiger config/private-key history hits: no.
- Repo-root Tiger config file after hygiene cleanup: no.
- Local TigerOpen config location: outside the repository.
- If a real Tiger config or private key is ever committed, rotate the key before any further live testing.

Initial environment value:

- `CFO_TIGER_ENABLED` present and true: yes.
- `CFO_TIGER_CONFIG_DIR` present: yes.
- Config dir exists: no.
- Config file exists: no.
- `CFO_TIGER_ACCOUNT` present: yes, redacted.
- `CFO_ACCOUNT_HASH_SALT` present: yes, redacted.

After pointing `CFO_TIGER_CONFIG_DIR` at the directory containing the local TigerOpen properties file:

- `CFO_TIGER_ENABLED` present and true: yes.
- `CFO_TIGER_CONFIG_DIR` present: yes.
- Config dir exists: yes.
- Config file exists: yes.
- `CFO_TIGER_ACCOUNT` present: yes, redacted.
- `CFO_ACCOUNT_HASH_SALT` present: yes, redacted.

No Tiger ID, raw account, credential, SDK config content, or `.env.local` value was printed in the committed record.

## Readiness Gate

Command:

```powershell
python .\scripts\personal_cfo_agent.py --provider tiger --readiness-check
```

Result:

- Readiness command exited 0.
- Provider mode: `api_contract_stub`.
- Warning codes: None.
- No reports generated.

This readiness gate validates environment variable presence only. It does not prove the local TigerOpen config directory or config file exists.

## Config Preflight Gate

Command:

```powershell
python .\scripts\personal_cfo_agent.py --provider tiger --config-preflight
```

Result:

- Config preflight command added: yes.
- Live read attempted by preflight: no.
- TigerOpen client initialized by preflight: no.
- Tiger account APIs called by preflight: no.
- Expected config file pattern: `<CFO_TIGER_CONFIG_DIR>\tiger_openapi_config.properties`.
- Expected config filename: `tiger_openapi_config.properties`.
- Adapter `props_path` expectation: directory path.
- Config dir exists: yes.
- Config dir is directory: yes.
- Adapter `props_path` shape valid: yes.
- Config file exists: yes.
- Config file readable: yes.
- Config file outside repository: yes.
- Config file tracked by Git: no.
- Config history risk detected: no.
- Tiger ID present: yes, redacted.
- `CFO_TIGER_ACCOUNT` present: yes, redacted.
- Config account present: yes, redacted.
- Private key field present: yes, redacted.
- Private key path/env present: no, redacted.
- Private key format category: `pkcs1_like`.
- Warning codes: `TIGER_CONFIG_PREFLIGHT_OK`.

No Tiger ID, raw account, private key, config value, config path, `.env.local` value, or balance was printed in this committed record.

## SDK Config Compatibility Probe

Command:

```powershell
python .\scripts\personal_cfo_agent.py --provider tiger --sdk-config-probe
```

Purpose:

- Diagnose TigerOpen SDK config-loading compatibility after config preflight passed but the prior supervised live attempt failed closed during SDK config load.
- Test `props_path` modes without account data calls: `directory`, `file`, `explicit_props_path`, and `sdk_default`.
- Report SDK config/client construction status with sanitized exception class/category only.

Safety:

- No account, position, cash, order, order preview, order modification/cancellation, cash transfer, or withdrawal API call is made by the probe.
- No Tiger ID, raw account, private key, config contents, local config path, `.env.local` value, exact balance, screenshot, or cookie is printed or committed.

Result:

- Probe result: passed.
- Props path modes tested: `directory`, `file`, `explicit_props_path`, `sdk_default`.
- Working props path mode selected: `directory`.
- SDK import OK: yes.
- Config file detected: yes.
- Required keys present: Tiger ID yes, account yes, private key yes; all redacted.
- Private key format category: `pkcs1_like`.
- SDK config constructed: yes.
- SDK client constructed: yes.
- SDK exception class sanitized: `None`.
- SDK exception category: `none`.
- `directory` mode: config yes, client yes.
- `file` mode: config yes, client yes.
- `explicit_props_path` mode: config no, client no, sanitized exception class `TypeError`, category `unknown`.
- `sdk_default` mode: config no, client no, category `required_key_missing`.
- Probe warning codes: `TIGER_SDK_CONFIG_CONSTRUCTED`, `TIGER_SDK_CLIENT_CONSTRUCTED`.
- Tiger account data APIs called: no.
- Tiger order/cash-transfer APIs called: no.

Adapter update:

- The adapter now uses official `TigerOpenClientConfig(props_path=<config directory>)` construction as the primary path.
- `CFO_TIGER_CONFIG_DIR` should point to the directory containing `tiger_openapi_config.properties`, not the file.
- The SDK helper path is not used as the primary path; helper/file modes are fallback-only and marked in diagnostics if used.
- Current local diagnostics report private-key format category `pkcs1_like`. TigerOpen SDK versions and docs may differ between `private_key_pk1` and `private_key_pk8`; if official directory mode still fails, regenerate or export the TigerOpen config according to the current Tiger docs.
- Account/position/cash live-read acceptance was attempted once after validation, config preflight, connection diagnostics, and SDK config probe passed.

## Connection Diagnostics Gate

Command:

```powershell
python .\scripts\personal_cfo_agent.py --provider tiger --connection-diagnostics
```

Result:

- TigerOpen import status: OK.
- Tiger provider enabled: yes.
- Tiger config directory configured: yes.
- Config dir exists: yes.
- Config file exists: yes.
- Tiger ID present: redacted yes/no only.
- Account configured: yes, redacted.
- Private key present: redacted yes/no only.
- Private key format: redacted category only.
- Account hash salt configured: yes, redacted.
- Warning codes: None.

## Diagnostic Stage Table

| Stage | Redacted status fields |
| --- | --- |
| SDK import | `sdk_import_ok` |
| Config dir/file | `config_dir_exists`, `config_file_exists` |
| Config load | `config_loaded`, `tiger_config_mode_selected`, `tiger_config_constructed`, `tiger_config_warning_codes`, `stage_failures.config_load` |
| Client construction | `tiger_client_constructed`, `client_init_attempted`, `client_init_success` |
| Private key | `private_key_present_redacted`, `private_key_format_detected_redacted` |
| Client init | `client_init_attempted`, `client_init_success`, `stage_failures.client_init` |
| Client auth | `client_auth_success`, `stage_failures.client_auth` |
| Account context | `account_context_observed`, `account_count_redacted`, `selected_account_hash` |
| Assets | `assets_query_attempted`, `assets_query_success` |
| Positions | `positions_query_attempted`, `positions_query_success`, `position_count` |
| Cash | `cash_query_attempted`, `cash_query_success`, `cash_currency_count` |
| Normalization | `normalized_rows`, `stage_failures.normalization` |

## Supervised Live Attempt

The supervised live read was attempted once after readiness, config preflight, SDK config probe, and connection diagnostics passed.

Command run:

```powershell
python .\scripts\personal_cfo_agent.py `
  --provider tiger `
  --allow-live-read `
  --tiger-data-diagnostics `
  --out-dir .\reports\personal_cfo_agent\tiger_v031_live_acceptance
```

Result:

- SDK import OK: yes.
- Config dir exists: yes.
- Config file exists: yes.
- Config loaded: yes.
- Official directory-mode config selected: yes.
- Helper fallback used: no.
- Config constructed: yes.
- Client constructed: yes.
- Tiger ID present: yes, redacted.
- Account present: yes, redacted.
- Private key present: yes, redacted.
- Private key format detected: `pkcs1`, redacted category only.
- Client init attempted: yes.
- Client init success: yes.
- Client auth success: yes.
- Account context observed: yes.
- Account count redacted: 1.
- Assets query attempted: yes.
- Assets query success: yes.
- Positions query attempted: yes.
- Positions query success: yes.
- Position count: 8.
- Cash query attempted: yes.
- Cash query success: yes.
- Cash currency count: 0.
- Normalized rows: 8.
- SDK output suppressed: yes.
- Warning codes: None.
- Stage failure: None.
- Report bundle generated: yes, under ignored `reports/personal_cfo_agent/tiger_v031_live_acceptance`.
- Raw account IDs in committed docs: no.
- Secrets/private keys in committed docs: no.
- Order/cash-transfer methods used: no.

## Acceptance Status

Acceptance success: yes for supervised Tiger read-only live-read proof.

Current counts:

- Account context observed: yes.
- Account count redacted: 1.
- Position count: 8.
- Cash currency count: 0.
- Normalized rows: 8.
- Live read success: yes.
- Report bundle generated: yes, ignored and not committed.

## Next Manual Step

Review the ignored local report bundle manually if needed. Do not commit generated reports, `.env.local`, Tiger config, private keys, screenshots, cookies, raw account IDs, exact balances, or any write/order/transfer method.
