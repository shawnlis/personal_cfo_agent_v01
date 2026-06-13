# Property And Mortgage Manual Workflow

Residential property and mortgage values are user-supplied manual estimates in Personal CFO Agent v0.1.4.

## Property Values

- Property valuation is user-supplied and must be reviewed.
- Include a `valuation_date` and `valuation_source`.
- Values older than 90 days are marked `STALE_MANUAL_VALUATION`.
- Missing valuation dates are marked `MISSING_VALUATION_DATE` and `NEEDS_REVIEW`.
- Do not treat property values as advice, tax planning, estate planning, or insurance planning.

Example asset type:

```json
{
  "asset_id": "manual-primary-residence",
  "asset_type": "residential_property",
  "provider": "manual",
  "name": "Primary residence estimate",
  "currency": "SGD",
  "estimated_value": 1000000.0,
  "valuation_date": "2026-06-14",
  "valuation_source": "manual valuation estimate",
  "liquidity_bucket": "illiquid",
  "risk_bucket": "real_estate",
  "notes": "User-entered estimate; review before relying on it."
}
```

## Mortgage Values

- Mortgage values are user-supplied and must be reviewed.
- Enter `outstanding_balance` as a positive number. The loader converts it to a liability in the normalized ledger.
- Include `interest_rate`, `monthly_payment`, `repricing_date`, `maturity_date`, and `collateral` when known.
- Do not automate bank portals or browser sessions.

Example liability type:

```json
{
  "liability_id": "manual-primary-mortgage",
  "liability_type": "mortgage",
  "provider": "manual",
  "name": "Primary mortgage",
  "currency": "SGD",
  "outstanding_balance": 400000.0,
  "interest_rate": 3.2,
  "monthly_payment": 2500.0,
  "repricing_date": "2027-01-01",
  "maturity_date": "2045-01-01",
  "collateral": "Primary residence",
  "notes": "User-entered mortgage balance; review before relying on it."
}
```
