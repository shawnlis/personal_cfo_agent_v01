# uSMART Read-Only Feasibility v0.5.7

v0.5.7 adds a uSMART readiness/config scaffold only. It is not a live reader.

## Scope

Implemented:

- `src/personal_cfo_agent/providers/usmart_connection_diagnostics.py`
- `src/personal_cfo_agent/providers/usmart_provider.py`
- `src/personal_cfo_agent/providers/usmart_readonly_adapter.py`
- `python .\scripts\personal_cfo_agent.py --provider usmart --readiness-check`
- `python .\scripts\personal_cfo_agent.py --provider usmart --connection-diagnostics`

The readiness path checks local environment/config presence and SDK importability. It reports only redacted field presence, SDK status, and warning codes.

## Safety Boundary

uSMART APIs may include trading and account-service capabilities. This version does not connect to uSMART, construct a live API client, read accounts, read balances, read positions, read cash, inspect order history, place orders, preview orders, modify orders, cancel orders, transfer cash, withdraw cash, or store credentials.

Future live-read work requires separate explicit approval and a supervised acceptance PR.

## Warning Codes

- `PROVIDER_DISABLED`
- `PROVIDER_CONFIG_MISSING`
- `SDK_NOT_INSTALLED`
- `USMART_READINESS_OK`

## Acceptance Status

Default local readiness is expected to return `PROVIDER_DISABLED` or `PROVIDER_CONFIG_MISSING` unless the user explicitly enables uSMART configuration locally. Connection diagnostics remain offline and redacted.

Generated reports are not part of v0.5.7 and must not be committed.
