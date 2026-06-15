# Connector Status Matrix

## Supported Candidates

| Platform | Status | Method | Asset Read | Position Read | Cash Read | Priority | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- |
| IBKR | read_only_live_proof_candidate | TWS API / IB Gateway through supervised local session | yes | yes | yes | 1 | v0.1.1 guarded read-only proof; TWS or IB Gateway must be started manually |
| Moomoo | draft_read_only_live_proof_candidate | OpenD + SDK through supervised local session | not accepted yet | not accepted yet | not accepted yet | 1 | PR #11 remains draft; OpenD socket reachability is not enough; redacted `get_acc_list()` account discovery succeeded and is required before funds/positions/cash; read-context probe added for HK/US/SG/NONE after data fetch failure; live-read acceptance remains no until normalized rows are produced |
| Tiger | read_only_live_proof_candidate | TigerOpen Python SDK through supervised local configuration | yes | yes | yes | 2 | v0.1.3 guarded read-only proof; TigerOpen must be configured locally |

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
