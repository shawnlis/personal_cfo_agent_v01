# Local Environment Setup

Project-local environment files are for local convenience only. They do not bypass provider safety gates and they do not enable live reads by themselves.

## Setup

From the project root:

```powershell
Copy-Item .env.example .env.local
```

Edit `.env.local` locally. Never commit `.env.local`.

Existing OS environment variables take precedence over `.env.local` values. If the same key is already present in the OS environment, the local file value is ignored.

## Sensitive Values

Account IDs and hash salts are sensitive. Keep them only in the OS environment or ignored local files such as `.env.local`.

The committed `.env.example` file contains placeholders only:

- `CFO_IBKR_ACCOUNT=` is intentionally blank.
- `CFO_ACCOUNT_HASH_SALT=` is intentionally blank.
- Provider enable flags default to `false`.

## Readiness And Live Reads

When `.env.local` is present, the CLI prints:

```text
Loaded local environment from .env.local; values redacted
```

Readiness checks and other CLI output must not print raw host values, account IDs, salts, passwords, private keys, or tokens.

Live read remains gated. `.env.local` does not bypass these requirements:

- The provider must be selected explicitly, for example `--provider ibkr`.
- The command must include `--allow-live-read`.
- The relevant provider enable flag must be true.
- Required provider config values must be present.
- The user must manually start the broker gateway or local SDK service.

No trading, order preview, order modification, order cancellation, cash transfer, browser automation, SingPass automation, scraping, or recommendation output is enabled by `.env.local`.
