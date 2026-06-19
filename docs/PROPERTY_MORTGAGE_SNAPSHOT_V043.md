# Property Mortgage Snapshot v0.4.3

v0.4.3 adds an offline manual property and mortgage snapshot layer.

It is manual-input only. It does not connect to banks, HDB, SingPass, browsers, brokers, or external accounts. It does not move money, place orders, create scheduler jobs, or produce recommendations.

## Inputs

The command reads two local JSON or CSV files:

- property input containing property assets
- mortgage input containing mortgage liabilities

Property records use:

- `property_id_hash`
- `label`
- `type`
- `country`
- `area`
- `ownership_pct`
- `valuation_amount`
- `currency`
- `valuation_date`
- `source`
- `confidence`
- `review_required`

Mortgage records use:

- `loan_id_hash`
- `linked_property_id_hash`
- `lender_label`
- `outstanding_balance`
- `currency`
- `interest_rate`
- `rate_type`
- `monthly_payment`
- `repricing_date`
- `maturity_date`
- `snapshot_date`
- `review_required`

Do not put raw addresses, bank account numbers, NRIC values, loan account numbers, login details, or secrets in these files. Use labels and hashes only.

## Command

Fixture-only smoke path:

```powershell
python .\scripts\personal_cfo_agent.py `
  --property-mortgage-snapshot `
  --property-input .\tests\fixtures\property_mortgage\property_v043.json `
  --mortgage-input .\tests\fixtures\property_mortgage\mortgage_v043.json `
  --out-dir .\reports\personal_cfo_agent\property_mortgage_v043_fixture
```

The command does not load `.env.local` and does not run broker live reads or Moomoo account discovery.

## Outputs

The command writes under ignored `reports/` paths:

- `property_asset_ledger.csv`
- `mortgage_liability_ledger.csv`
- `property_equity_summary.json`
- `property_mortgage_warnings.md`
- `PROPERTY_MORTGAGE_SNAPSHOT_V043.md`

Generated reports and local property/mortgage history must not be committed.

## Equity Rule

For each property:

```text
equity = valuation_amount * ownership_pct - linked mortgage balance
```

`ownership_pct` accepts either a decimal fraction such as `0.50` or a percent string such as `50%`. The generated ledger stores the normalized decimal value.

Mortgages without `linked_property_id_hash` remain in the mortgage liability ledger and generate `MORTGAGE_UNLINKED`.

## Validation Rules

- Missing property ownership fails closed with `PROPERTY_OWNERSHIP_MISSING`.
- Missing property valuation fails closed with `PROPERTY_VALUATION_MISSING`.
- Missing required property fields fail closed with `PROPERTY_REQUIRED_FIELD_MISSING`.
- Missing required mortgage fields fail closed with `MORTGAGE_REQUIRED_FIELD_MISSING`.
- Valuation dates older than 90 days generate `PROPERTY_VALUATION_STALE`.
- User-marked review rows generate `PROPERTY_MORTGAGE_REVIEW_REQUIRED`.

## Warning Codes

- `PROPERTY_MORTGAGE_INPUT_MISSING`
- `PROPERTY_INPUT_EMPTY`
- `PROPERTY_REQUIRED_FIELD_MISSING`
- `PROPERTY_OWNERSHIP_MISSING`
- `PROPERTY_VALUATION_MISSING`
- `PROPERTY_VALUATION_STALE`
- `PROPERTY_MORTGAGE_REVIEW_REQUIRED`
- `MORTGAGE_INPUT_EMPTY`
- `MORTGAGE_REQUIRED_FIELD_MISSING`
- `MORTGAGE_UNLINKED`
- `MORTGAGE_PROPERTY_LINK_MISSING`
- `PROPERTY_MORTGAGE_GENERATED_OK`
- `PROPERTY_MORTGAGE_GENERATED_WITH_WARNINGS`
- `PROPERTY_MORTGAGE_FAILED`
