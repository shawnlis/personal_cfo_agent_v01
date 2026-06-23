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

## Local Net Worth Doctor Rule

v0.6.2 local net worth doctor is an offline health-check layer only. It inspects unified private input validity, existing refresh output completeness, explicit local FX coverage, and broker config presence as redacted yes/no status. It may load `.env.local` through the existing redacted local environment loader, but it must never print values. It must not run broker reads, readiness checks, Webull token preflight, Moomoo discovery, account diagnostics, browser automation, external uploads, trading, cash movement, or recommendation output. Generated doctor outputs must stay under ignored `reports/` paths and must not include exact NAV, balances, positions, raw account IDs, private input values, `.env.local` values, API keys, tokens, or secrets.

## Data Quality Summary Rule

v0.6.4 data quality summary is an offline report produced by local net worth refresh. It records provider requested/succeeded/failed status, manual layer availability, account NAV row count, position row count, snapshot and dashboard generation status, FX completeness, and warning codes. It must not run broker reads, Webull token preflight, Moomoo discovery, account diagnostics, browser automation, external uploads, trading, cash movement, tax filing, or recommendation output. It must not include exact NAV, balances, positions, raw account IDs, private input contents, `.env.local` values, API keys, tokens, or secrets. Generated data quality outputs must stay under ignored `reports/` paths.

## Net Worth Integrity Guard Rule

v0.6.5 net worth integrity guard is an offline confirmation gate for local net worth refresh. It reads only already-generated local refresh artifacts, checks requested broker coverage, provider-reported NAV availability, FX completeness, mixed/stale date warnings, total availability, and large changes versus confirmed history, then reports whether `--confirm-snapshot-history-write` may proceed. It must not run broker reads, Webull token preflight, Moomoo discovery, account diagnostics, browser automation, external uploads, trading, cash movement, tax filing, or recommendation output. It must not include exact NAV, balances, positions, raw account IDs, account hashes, private input contents, `.env.local` values, API keys, tokens, or secrets. Generated guard outputs must stay under ignored `reports/` paths.

## Snapshot Review Rule

v0.6.6 snapshot review is an offline review page generated from local refresh,
data quality, and integrity-guard artifacts. It reports confirmation readiness,
provider gate status, row counts, FX completeness, warning explanations, and the
next safe action. It must not run broker reads, Webull token preflight, Moomoo
discovery, account diagnostics, browser automation, external uploads, trading,
cash movement, tax filing, or recommendation output. It must not include exact
NAV, balances, positions, raw account IDs, account hashes, private input
contents, `.env.local` values, API keys, tokens, or secrets.

## Local Workbench Rule

v0.6.6 local workbench is a static local launcher and path/status checklist. It
may link to existing local dashboard and snapshot review HTML files, but it must
not read private values, run broker reads, call Webull token preflight, run
Moomoo discovery, use browser automation, upload data, move cash, trade, file
taxes, or generate recommendations. It reports path presence only and all
generated workbench outputs must stay under ignored `reports/` paths.

## Dashboard v4 Rule

v0.6.0 Dashboard v4 is an offline visual reporting layer over an already-generated v0.5.9 refresh directory. It reads local merged account NAV, snapshot history, Dashboard v3 history, property/mortgage, and Singapore manual snapshot outputs; it writes Markdown, HTML, CSV, JSON, and inline SVG artifacts under ignored `reports/` paths. It must not connect to brokers, banks, CPF, IRAS, HDB, SingPass, browsers, Webull token flows, or external accounts. It must not perform market execution, move cash, file taxes, create scheduler jobs, upload data, load external chart services, or produce action instructions. Mixed-currency display requires explicit local FX rates and must warn instead of silently converting when FX is missing.
