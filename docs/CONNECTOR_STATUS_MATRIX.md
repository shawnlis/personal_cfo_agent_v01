# Connector Status Matrix

## Supported Candidates

| Platform | Status | Method | Asset Read | Position Read | Cash Read | Priority | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- |
| IBKR | read_only_live_proof_accepted | TWS API / IB Gateway through supervised local session | yes | yes | yes | 1 | v0.2.2 supervised read-only proof and safe local sync workflow; TWS or IB Gateway must be started manually |
| Moomoo | read_only_live_proof_accepted | OpenD + SDK through supervised local session | yes | yes | yes | 1 | v0.3.2 supervised read-only proof; OpenD socket reachability is not enough; redacted `get_acc_list()` account discovery is required before funds/positions/cash; proof generated normalized rows under ignored `reports/` without unlock, orders, transfers, raw IDs, or committed reports |
| Tiger | read_only_live_proof_accepted | TigerOpen Python SDK through supervised local configuration | yes | yes | yes | 2 | v0.3.1 supervised read-only proof; TigerOpen must be configured locally |
| Webull | readiness_feasibility_only | Official OpenAPI readiness/config diagnostics only | no | no | no | none | v0.5.4 verifies redacted config and SDK importability only; no live read, execution workflow, or cash movement |

## Normalized Ledger Merge

v0.3.3 adds an offline account-NAV-first multi-provider merge layer for already-generated normalized provider bundles from manual snapshots, IBKR, Tiger, and Moomoo. Account NAV is the primary Personal CFO net-worth layer; the position ledger is best-effort drilldown data. It does not run live broker reads, broker API calls, trading workflows, cash movement, or recommendation output. Generated merged bundles stay under ignored `reports/` paths.

## Dashboard v2

v0.4.0 Dashboard v2 is an offline account-NAV-first dashboard over v0.3.3 merged ledger outputs. It consumes `merged_account_nav_ledger.csv` as the primary source and uses `merged_position_ledger.csv` only as optional drilldown. It does not add broker connectivity, live reads, trading workflows, cash movement, scheduler automation, or recommendation output.

## Snapshot Store

v0.4.2 adds an offline snapshot store for local net worth history. It consumes v0.3.3 merged account NAV outputs and optional v0.4.0 Dashboard v2 outputs, then writes immutable local history artifacts under ignored `reports/` paths. It does not add broker connectivity, live reads, trading workflows, cash movement, scheduler automation, or recommendation output.

## Property And Mortgage Snapshot

v0.4.3 adds an offline manual property and mortgage snapshot foundation. It consumes user-supplied local JSON/CSV files with labels and hashes only, writes property asset, mortgage liability, and equity summary outputs under ignored `reports/` paths, and does not add bank, HDB, SingPass, browser, broker, trading, cash movement, scheduler, or recommendation workflows.

## Singapore Retirement Tax Snapshot

v0.4.4 adds an offline manual Singapore CPF, SRS, tax, and HDB loan snapshot foundation. It consumes user-supplied local JSON/CSV files or user-export-derived files, writes CPF, SRS, tax review, HDB loan, summary, and warning outputs under ignored `reports/` paths, and does not add CPF, IRAS, HDB, SingPass, bank, browser, broker, trading, tax filing, cash movement, scheduler, or recommendation workflows.

## Dashboard v3

v0.5.0 adds an integrated offline net worth dashboard over v0.3.3 account NAV merge outputs, v0.4.2 snapshot history, v0.4.3 property/mortgage snapshots, and v0.4.4 Singapore manual snapshots. Account NAV and snapshot history remain primary. Property, CPF, SRS, tax, and HDB loan data are offline manual review layers. It does not add broker, bank, CPF, IRAS, HDB, SingPass, browser, trading, tax filing, cash movement, scheduler, or recommendation workflows.

## Webull Readiness Feasibility

v0.5.4 adds Webull OpenAPI readiness/config diagnostics only. Webull API documentation includes execution-capable surfaces, so this foundation is deliberately not a live reader. It does not connect to Webull, read account data, move cash, or enable execution workflows. Future Webull live-read work requires separate approval.

## Unsupported Until Official API Verified

| Platform | Status | Method | Priority | Notes |
| --- | --- | --- | --- | --- |
| POEMS / Phillip | unsupported_until_official_api_verified | no official retail account API confirmed | none | manual snapshot only unless official API is verified |

## Manual Or Indirect Sources

| Platform | Status | Method | Priority | Notes |
| --- | --- | --- | --- | --- |
| CPF / IRAS / HDB | indirect_via_sgfindex_or_manual_snapshot | SGFinDex user-facing aggregation / manual update | manual only | do not automate Singpass or scrape government portals |
| Residential property | manual_snapshot | manual valuation snapshot | manual only | v0.4.3 supports local JSON/CSV manual snapshots with labels and hashes only; no raw address required |
| Mortgage | manual_snapshot | manual balance snapshot initially | manual only | v0.4.3 supports local JSON/CSV manual snapshots with hashed loan id and optional hashed property link |
| CPF / SRS / tax / HDB loan | manual_snapshot | local manual or user-export-derived snapshot | manual only | v0.4.4 supports local JSON/CSV manual snapshots; no CPF/IRAS/HDB/SingPass/browser automation, tax filing, or advice |
