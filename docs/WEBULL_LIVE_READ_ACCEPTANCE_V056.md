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

Readiness and diagnostics were rerun after the user configured local Webull credentials. Credential presence is redacted and no values were printed. The provider is enabled and app key/app secret are present, but the local Webull SDK module is not installed/importable, so the supervised live read was not attempted.

- Readiness result: `SDK_NOT_INSTALLED`
- Diagnostics result: redacted/offline
- Live connection attempted by diagnostics: no
- Supervised live read attempted: no
- Supervised live read success: no
- Account count redacted: 0
- Position count: 0
- Normalized rows: 0
- Report path generated: no
- Warning codes: `SDK_NOT_INSTALLED`

If a supported Webull SDK module is installed later, rerun readiness and diagnostics first. Only if those pass should the supervised read-only command be run once, then this section should be updated with only redacted status, counts, warning codes, and report path.
