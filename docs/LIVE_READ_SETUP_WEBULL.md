# Webull Read-Only Setup

Personal CFO Agent v0.5.4 adds a Webull OpenAPI feasibility scaffold only. It does not run a live read, connect to Webull, request account data, or enable execution workflows.

Official Webull OpenAPI documentation describes programmatic market data, account management, and execution-capable APIs. The Singapore documentation also requires signed requests using an app key and app secret. Because the same API surface can support execution, this project treats Webull as readiness-only until a later supervised read-only live-read task is separately approved.

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

## Boundaries

v0.5.4 does not:

- connect to Webull
- read balances, cash, positions, holdings, account identifiers, or transaction history
- submit or preview execution instructions
- change or revoke execution instructions
- move cash
- store credentials
- print API keys, app secrets, tokens, account IDs, or `.env.local` values

Future Webull live-read work must be a separate PR with explicit approval, mocked tests first, redaction tests, and a supervised read-only acceptance run.
