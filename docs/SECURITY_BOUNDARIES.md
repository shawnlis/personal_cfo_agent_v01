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

## Webull Feasibility Rule

v0.5.4 Webull support is readiness/config diagnostics only. It may inspect redacted environment presence and SDK importability, but it must not connect to Webull, construct a live API client, read account data, move cash, or expose execution workflows. Webull live-read work requires a separate explicit approval and a new supervised acceptance task.

## Offline Merge Rule

v0.3.3 multi-provider normalized ledger merge is offline only and account-NAV-first. It reads existing normalized bundles under local ignored `reports/` paths or synthetic fixture inputs, writes account NAV and best-effort position outputs under ignored `reports/` paths, and must not connect to brokers, call broker SDKs, move cash, place orders, or produce recommendation output.

## Dashboard v2 Rule

v0.4.0 Dashboard v2 is offline only. It reads existing v0.3.3 merged account NAV outputs under ignored `reports/` paths, writes dashboard artifacts under ignored `reports/` paths, and must not connect to brokers, call broker SDKs, run Moomoo account discovery, move cash, place orders, create scheduler jobs, or produce recommendation output. Position rows are optional drilldown and not the acceptance gate.

## Snapshot Store Rule

v0.4.2 snapshot store is offline only. It reads existing merged account NAV and Dashboard v2 outputs under ignored `reports/` paths, appends local net worth history artifacts under ignored `reports/` paths, and must not connect to brokers, call broker SDKs, run Moomoo account discovery, move cash, place orders, create scheduler jobs, or produce recommendation output. Raw account IDs are forbidden; `account_id_hash` is allowed.

## Property Mortgage Snapshot Rule

v0.4.3 property and mortgage snapshots are offline manual-input only. They read local property and mortgage JSON/CSV files, write generated ledgers under ignored `reports/` paths, and must not connect to banks, HDB, SingPass, browsers, brokers, or external accounts. Raw addresses, loan account numbers, login details, secrets, exact local values in docs, and generated reports must not be committed. Labels and hashes are allowed.

## Singapore Retirement Tax Snapshot Rule

v0.4.4 Singapore CPF, SRS, tax, and HDB loan snapshots are offline manual-input or user-export-derived only. They read local JSON/CSV files, write generated ledgers under ignored `reports/` paths, and must not connect to CPF, IRAS, HDB, SingPass, banks, browsers, brokers, or external accounts. Tax records are informational and review-only, not filing or advice. NRIC, FIN, raw government identifiers, raw account numbers, login details, secrets, exact local values in docs, and generated reports must not be committed. Labels, availability flags, and hashes are allowed.

## Dashboard v3 Rule

v0.5.0 Dashboard v3 is offline reporting only. It reads existing v0.3.3 merged account NAV outputs, v0.4.0 Dashboard v2 summary, v0.4.2 snapshot history, optional v0.4.3 property/mortgage outputs, and optional v0.4.4 Singapore manual snapshot outputs under ignored `reports/` paths. It must not connect to brokers, banks, CPF, IRAS, HDB, SingPass, browsers, or external accounts; must not perform market execution, move cash, file taxes, create scheduler jobs, or produce action instructions; and must not commit generated reports or raw identifiers. The v0.5.2 polish layer is a presentation/readability pass only and must not change account NAV merge or snapshot history semantics.

## Local Private Input Kit Rule

v0.5.3 local private input kit is template, validation, and offline manual snapshot-chain tooling only. It writes placeholder input files to ignored local directories such as `private_inputs/`, `local_private_inputs/`, or `reports/personal_cfo_agent/private_inputs/`; validates file presence, schema shape, required fields, labels/hashes, and warning codes without printing private values; and can run the existing offline property/mortgage and Singapore manual snapshot generators. It must not overwrite existing local files unless `--overwrite` is explicitly supplied, and it must not connect to brokers, banks, CPF, IRAS, HDB, SingPass, browsers, or external accounts. Real local input values, generated reports, raw addresses, NRIC/FIN, raw government identifiers, account numbers, secrets, and exact private values must not be committed.

## Manual NAV Input Rule

v0.5.7 unified manual NAV input is local-only. It generates a static HTML worksheet, initializes an ignored local JSON file, validates schema/warnings without printing private values, and converts account NAV rows into a provider-bundle-compatible output for the offline merge pipeline. It must not connect to brokers, banks, CPF, IRAS, HDB, SingPass, browsers, or external accounts. Raw account IDs, raw account numbers, NRIC/FIN, login details, secrets, exact local values in docs, and generated reports must not be committed. The provider bundle must emit `account_id_hash` only.

## Unified Private Input Center Rule

v0.5.8 unified private input center is local-only and is the preferred manual input workflow for manual NAV, property/mortgage, CPF, SRS, tax, and HDB loan sections. It generates a static local HTML worksheet, initializes one ignored JSON file, validates counts/warnings without printing private values, and reuses existing offline snapshot modules. The worksheet may use local inline JavaScript only to build and save local JSON; it must not use external scripts, remote styles, network requests, browser automation, credential material, raw account IDs, raw account numbers, raw addresses, NRIC/FIN, government identifiers, exact local values in docs, generated report commits, money movement, tax filing, or recommendation output. It must not connect to banks, CPF, IRAS, HDB, SingPass, browsers, or external accounts.

## Local Net Worth Refresh Rule

v0.5.9 local net worth refresh is an orchestration layer over existing private input conversion, optional supervised read-only provider refresh, account NAV merge, snapshot history, and Dashboard v3 generation. Manual-only mode must use no external provider reads. Broker refresh mode must require explicit `--allow-live-read` and must reuse only the existing read-only provider paths. It must not print exact NAV, balances, positions, raw account IDs, credentials, private inputs, or secrets. Generated outputs must stay ignored under `reports/`, private inputs must stay ignored under local private input folders, and failed broker refreshes must surface warning codes rather than being reported as clean results.

## Dashboard v4 Rule

v0.6.0 Dashboard v4 is an offline visual reporting layer over an already-generated v0.5.9 refresh directory. It reads local merged account NAV, snapshot history, Dashboard v3 history, property/mortgage, and Singapore manual snapshot outputs; it writes Markdown, HTML, CSV, JSON, and inline SVG artifacts under ignored `reports/` paths. It must not connect to brokers, banks, CPF, IRAS, HDB, SingPass, browsers, Webull token flows, or external accounts. It must not perform market execution, move cash, file taxes, create scheduler jobs, upload data, load external chart services, or produce action instructions. Mixed-currency display requires explicit local FX rates and must warn instead of silently converting when FX is missing.
