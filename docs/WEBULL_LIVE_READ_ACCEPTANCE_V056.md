# Webull Live Read Acceptance v0.5.6

v0.5.6 starts the supervised Webull read-only live proof. This is not enabled by default.

## Scope

Allowed read-only surfaces:

- Account list: `GET /openapi/account/list`
- Account balance/assets: `GET /openapi/assets/balance`
- Account positions: `GET /openapi/assets/positions`

The implementation normalizes available account NAV, cash summary, and positions into the existing provider bundle schema with `provider=webull` and `account_id_hash` only.

## Required Command

```powershell
python .\scripts\personal_cfo_agent.py --provider webull --allow-live-read --webull-data-diagnostics --out-dir .\reports\personal_cfo_agent\webull_v056_live_acceptance
```

Readiness and diagnostics should be run first:

```powershell
python .\scripts\personal_cfo_agent.py --provider webull --readiness-check
python .\scripts\personal_cfo_agent.py --provider webull --connection-diagnostics
```

## Redaction

The CLI output and committed documentation must not include:

- API keys, app secrets, tokens, or `.env.local` values
- raw account identifiers
- exact balances, account NAV, cash values, or position values
- generated report contents

The redacted diagnostics may include only:

- SDK import status
- client init status
- account query success/failure
- account count redacted
- selected account hash
- asset/NAV query success/failure
- position query success/failure
- position count
- normalized row count
- warning codes

## Safety Boundary

The Webull OpenAPI surface includes execution-capable APIs. v0.5.6 does not add execution, cancellation, instruction preview, instruction modification, cash movement, transaction history, browser login, cookie/session scraping, or credential storage.

Generated report bundles must stay under ignored `reports/` paths and must not be committed.

## Current Acceptance Result

Readiness and diagnostics were rerun after the user installed the official Webull Python SDK and configured local Webull credentials. Credential presence is redacted and no values were printed.

- SDK import result: OK
- SDK module detected: `webull`
- Readiness result: `WEBULL_READINESS_OK`
- Diagnostics result: redacted/offline, `WEBULL_READINESS_OK`
- Live connection attempted by diagnostics: no
- Supervised live read attempted: yes, exactly once
- Supervised live read success: no
- Client constructed: yes
- Auth/session ready: unknown
- Account query attempted: yes
- Account query success: no
- Account count redacted: 0
- Account selector present: no
- Sanitized account exception class: `ServerException`
- Sanitized account exception category: `exception_sanitized`
- Sanitized account failure stage: `account_query`
- Asset/NAV query attempted: no, skipped after account-query failure
- Position query attempted: no, skipped after account-query failure
- Position count: 0
- Normalized rows: 0
- Report path generated: no
- Warning codes: `WEBULL_ACCOUNT_LIST_QUERY_ATTEMPTED`, `WEBULL_ACCOUNT_QUERY_FAILED`, `PROVIDER_FETCH_FAILED`, `WEBULL_ACCOUNT_QUERY_EXCEPTION_SANITIZED`, `WEBULL_ASSET_QUERY_SKIPPED`, `WEBULL_POSITION_QUERY_SKIPPED`, `WEBULL_LIVE_READ_FAILED`

The SDK and client initialized successfully, but the supervised read-only proof failed closed at the account-query stage with a sanitized SDK exception category. Raw SDK error text was not recorded in docs or PR metadata. Asset/NAV and position queries were not attempted after the account-query failure. No generated report bundle was produced.
