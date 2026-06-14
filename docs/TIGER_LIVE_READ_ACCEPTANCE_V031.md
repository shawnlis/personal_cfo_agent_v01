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
- Account configured: yes, redacted.
- Account hash salt configured: yes, redacted.
- Warning codes: None.

## Supervised Live Attempt

The supervised live read was attempted once after readiness and connection diagnostics passed.

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
- Config loaded: no.
- Account context observed: yes.
- Account count redacted: 1.
- Asset query attempted: no.
- Asset query success: no.
- Position query attempted: no.
- Position query success: no.
- Position count: 0.
- Cash currency count: 0.
- Normalized rows: 0.
- SDK output suppressed: yes.
- Warning codes: `PROVIDER_CONNECTION_FAILED`.
- Stage failure: `config_load=TigerOpen config/client initialization failed`.
- Report bundle generated: no.

## Acceptance Status

Acceptance success: no.

Current counts:

- Account context observed: yes.
- Account count redacted: 1.
- Position count: 0.
- Cash currency count: 0.
- Normalized rows: 0.
- Report bundle generated: no.

## Next Manual Step

Review local TigerOpen client configuration outside Git, then rerun:

```powershell
python .\scripts\personal_cfo_agent.py `
  --provider tiger `
  --allow-live-read `
  --tiger-data-diagnostics `
  --out-dir .\reports\personal_cfo_agent\tiger_v031_live_acceptance
```

Do not add any write, order, unlock, or transfer method while investigating the config/client initialization failure.
