# Webull Read-Only Setup

Personal CFO Agent v0.5.6 adds a supervised Webull OpenAPI read-only proof path. It is disabled by default and requires an explicit `--provider webull --allow-live-read` command.

Official Webull OpenAPI documentation describes programmatic market data, account management, assets, and execution-capable APIs. The Singapore documentation also requires signed requests using an app key and app secret. Because the same API surface can support execution, this project implements only a narrow read-only allowlist for account list, account balance/assets, and account positions.

Sources:

- https://developer.webull.com.sg/apis/docs/
- https://developer.webull.com.sg/apis/docs/authentication/signature/
- https://developer.webull.com/apis/docs/getting-started/

## Local Configuration

Configuration is environment-only and redacted in all CLI output:

```text
CFO_WEBULL_ENABLED=false
CFO_WEBULL_APP_KEY=
CFO_WEBULL_APP_SECRET=
CFO_WEBULL_API_HOST=
CFO_WEBULL_SDK_MODULE=
```

`CFO_WEBULL_SDK_MODULE` is optional. It lets the readiness check test a locally installed SDK module name without importing unrelated packages. The default readiness probe tries documented/plausible Webull OpenAPI Python module names, but it never constructs a client and never sends an API request.

## Commands

Readiness check:

```powershell
python .\scripts\personal_cfo_agent.py --provider webull --readiness-check
```

Connection diagnostics:

```powershell
python .\scripts\personal_cfo_agent.py --provider webull --connection-diagnostics
```

Both commands are local-only. They check redacted config presence and SDK importability. Expected warning/status codes are:

- `PROVIDER_DISABLED`
- `PROVIDER_CONFIG_MISSING`
- `SDK_NOT_INSTALLED`
- `WEBULL_READINESS_OK`

Supervised read-only data diagnostics:

```powershell
python .\scripts\personal_cfo_agent.py --provider webull --allow-live-read --webull-data-diagnostics --out-dir .\reports\personal_cfo_agent\webull_v056_live_acceptance
```

This command may construct a local SDK client and call only the read/query surfaces that correspond to:

- `GET /openapi/account/list`
- `GET /openapi/assets/balance`
- `GET /openapi/assets/positions`

The report bundle is written only under ignored `reports/` paths. Console diagnostics are redacted and include counts, stage status, selected account hash, and warning codes only.

## Boundaries

v0.5.6 does not:

- run without `--allow-live-read`
- print raw account identifiers
- submit or preview execution instructions
- change or revoke execution instructions
- move cash
- store credentials
- print API keys, app secrets, tokens, account IDs, or `.env.local` values
- read transaction history
- commit generated reports

## v0.5.6 Warning Codes

- `WEBULL_CONFIG_MISSING`
- `WEBULL_SDK_NOT_INSTALLED`
- `WEBULL_CLIENT_INIT_FAILED`
- `WEBULL_AUTH_FAILED`
- `WEBULL_ACCOUNT_QUERY_FAILED`
- `WEBULL_ASSET_QUERY_FAILED`
- `WEBULL_POSITION_QUERY_FAILED`
- `WEBULL_NO_DATA_RETURNED`
- `WEBULL_READ_ONLY_FETCH_OK`
- `WEBULL_LIVE_READ_SUCCEEDED`
- `WEBULL_LIVE_READ_FAILED`
