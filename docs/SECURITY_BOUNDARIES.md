# Security Boundaries

Personal CFO Agent v0.1 is read-only, offline by default, and connector-first.

## Hard Boundaries

- No trading.
- No order placement.
- No cash transfer.
- No password storage.
- No private keys in the repository.
- No browser cookies in the repository.
- No browser automation.
- No Singpass automation.
- No CPF/IRAS/HDB scraping.
- No Webull unofficial API.
- No POEMS unofficial API.
- No recommendation output.
- No buy/sell/hold advice.
- No tax, estate, or insurance advice.
- No PM prompt wiring.
- No AI PM Agent import path.

## Secrets

All connector configuration must come from environment variables. The application must never write secret material to disk or logs. Generated reports, local config, browser session artifacts, screenshots, real account data, and private keys are ignored by Git.

## Live Connector Rule

IBKR, Tiger, and Moomoo now have supervised read-only proof workflows. Each live workflow requires an explicit provider-specific command, manual local setup, and `--allow-live-read`; no live workflow is run by default. Generated live outputs must stay under ignored `reports/` paths.

## Offline Merge Rule

v0.3.3 multi-provider normalized ledger merge is offline only. It reads existing normalized bundles under local ignored `reports/` paths or synthetic fixture inputs, writes merged outputs under ignored `reports/` paths, and must not connect to brokers, call broker SDKs, move cash, place orders, or produce recommendation output.
