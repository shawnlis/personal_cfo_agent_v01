# Connector Status Matrix

## Supported Candidates

| Platform | Status | Method | Asset Read | Position Read | Cash Read | Priority | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- |
| IBKR | read_only_live_proof_accepted | TWS API / IB Gateway through supervised local session | yes | yes | yes | 1 | v0.2.2 supervised read-only proof and safe local sync workflow; TWS or IB Gateway must be started manually |
| Moomoo | read_only_live_proof_accepted | OpenD + SDK through supervised local session | yes | yes | yes | 1 | v0.3.2 supervised read-only proof; OpenD socket reachability is not enough; redacted `get_acc_list()` account discovery is required before funds/positions/cash; proof generated normalized rows under ignored `reports/` without unlock, orders, transfers, raw IDs, or committed reports |
| Tiger | read_only_live_proof_accepted | TigerOpen Python SDK through supervised local configuration | yes | yes | yes | 2 | v0.3.1 supervised read-only proof; TigerOpen must be configured locally |

## Normalized Ledger Merge

v0.3.3 adds an offline account-NAV-first multi-provider merge layer for already-generated normalized provider bundles from manual snapshots, IBKR, Tiger, and Moomoo. Account NAV is the primary Personal CFO net-worth layer; the position ledger is best-effort drilldown data. It does not run live broker reads, broker API calls, trading workflows, cash movement, or recommendation output. Generated merged bundles stay under ignored `reports/` paths.

## Dashboard v2

v0.4.0 Dashboard v2 is an offline account-NAV-first dashboard over v0.3.3 merged ledger outputs. It consumes `merged_account_nav_ledger.csv` as the primary source and uses `merged_position_ledger.csv` only as optional drilldown. It does not add broker connectivity, live reads, trading workflows, cash movement, scheduler automation, or recommendation output.

## Snapshot Store

v0.4.2 adds an offline snapshot store for local net worth history. It consumes v0.3.3 merged account NAV outputs and optional v0.4.0 Dashboard v2 outputs, then writes immutable local history artifacts under ignored `reports/` paths. It does not add broker connectivity, live reads, trading workflows, cash movement, scheduler automation, or recommendation output.

## Unsupported Until Official API Verified

| Platform | Status | Method | Priority | Notes |
| --- | --- | --- | --- | --- |
| Webull | unsupported_until_official_api_verified | no official retail API confirmed | none | do not use unofficial reverse-engineered APIs |
| POEMS / Phillip | unsupported_until_official_api_verified | no official retail account API confirmed | none | manual snapshot only unless official API is verified |

## Manual Or Indirect Sources

| Platform | Status | Method | Priority | Notes |
| --- | --- | --- | --- | --- |
| CPF / IRAS / HDB | indirect_via_sgfindex_or_manual_snapshot | SGFinDex user-facing aggregation / manual update | manual only | do not automate Singpass or scrape government portals |
| Residential property | manual_snapshot | manual valuation snapshot | manual only | fields: property_name, estimated_value, valuation_date, valuation_source, mortgage_linked, notes |
| Mortgage | manual_snapshot | manual balance snapshot initially | manual only | fields: lender, outstanding_balance, interest_rate, monthly_payment, repricing_date, maturity_date, notes |
