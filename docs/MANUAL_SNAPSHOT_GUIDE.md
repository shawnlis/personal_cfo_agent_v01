# Manual Snapshot Guide

Personal CFO Agent v0.1.4 supports structured JSON manual snapshots for unsupported or non-API assets. Manual snapshots are for user-entered summary values only.

## Supported Manual Rows

Assets:

- `residential_property`
- `cpf_oa`
- `cpf_sa`
- `cpf_ma`
- `cash`
- `unsupported_broker`
- `insurance_cash_value`
- `other_asset`

Liabilities:

- `mortgage`
- `personal_loan`
- `credit_card`
- `other_liability`

## Commands

Create an empty template:

```powershell
python .\scripts\personal_cfo_agent.py --write-manual-template .\manual_snapshots\manual_snapshot_template.json
```

Validate a snapshot:

```powershell
python .\scripts\personal_cfo_agent.py --validate-manual-snapshot .\manual_snapshots\my_snapshot.json
```

Run aggregation:

```powershell
python .\scripts\personal_cfo_agent.py --manual-snapshot .\manual_snapshots\my_snapshot.json --out-dir .\reports\personal_cfo_agent\manual_v014
```

## Required JSON Shape

```json
{
  "snapshot_date": "2026-06-14",
  "base_currency": "SGD",
  "source_note": "Manual user-entered snapshot.",
  "assets": [],
  "liabilities": [],
  "warnings_acknowledged": false
}
```

Asset rows require `asset_id`, `asset_type`, `provider`, `name`, `currency`, `estimated_value`, `valuation_date`, `valuation_source`, `liquidity_bucket`, `risk_bucket`, and `notes`.

Liability rows require `liability_id`, `liability_type`, `provider`, `name`, `currency`, `outstanding_balance`, `interest_rate`, `monthly_payment`, `repricing_date`, `maturity_date`, `collateral`, and `notes`.

## Validation Rules

- Missing currency fails closed.
- Missing amount fails closed.
- Negative asset value fails closed.
- Negative liability balance fails closed.
- Missing valuation date emits `MISSING_VALUATION_DATE` and `NEEDS_REVIEW`.
- Valuation dates older than 90 days emit `STALE_MANUAL_VALUATION`.
- Webull, POEMS, and other unsupported broker rows must be marked manual.
- CPF, IRAS, and HDB values must be manual or SGFinDex-derived, not scraped.

Manual snapshots are ignored by Git under `manual_snapshots/`. Generated reports remain ignored under `reports/`.

## Safety Boundary

- Do not automate SingPass.
- Do not scrape CPF / IRAS / HDB.
- Do not use unofficial Webull or POEMS APIs.
- Do not use browser sessions, screenshots, or scraping to populate the file.
- Do not include account numbers, passwords, cookies, keys, or screenshots.
