# Singapore Retirement Tax Snapshot v0.4.4

v0.4.4 adds an offline manual Singapore CPF, SRS, tax, and HDB loan snapshot foundation.

It is manual-input or user-export-derived only. It does not connect to CPF, IRAS, HDB, SingPass, banks, browsers, brokers, or external accounts. It does not file taxes, move money, create scheduler jobs, or produce recommendations.

## Inputs

The command reads four local JSON or CSV files:

- CPF snapshot input
- SRS snapshot input
- tax review input
- HDB loan snapshot input

CPF records use:

- `snapshot_date`
- `oa`
- `sa`
- `ma`
- `ra`
- `total`
- `currency`
- `source_type`
- `source_date`
- `review_required`

SRS records use:

- `snapshot_date`
- `provider_label`
- `cash`
- `investments_value`
- `total`
- `contribution_ytd`
- `currency`
- `source_type`
- `source_date`
- `review_required`

Tax records use availability flags only:

- `year_of_assessment`
- `assessable_income_available`
- `tax_payable_available`
- `tax_paid_available`
- `reliefs_available`
- `source_type`
- `source_date`
- `review_required`

HDB loan records use:

- `snapshot_date`
- `loan_id_hash`
- `linked_property_id_hash`
- `monthly_installment_available`
- `outstanding_balance_available`
- `currency`
- `source_type`
- `source_date`
- `review_required`

Do not put NRIC, FIN, tax reference numbers, raw CPF or HDB account numbers, raw addresses, login details, or secrets in these files. Use labels, availability flags, and hashes only where identifiers are needed.

## Command

Fixture-only smoke path:

```powershell
python .\scripts\personal_cfo_agent.py `
  --sg-manual-snapshot `
  --cpf-input .\tests\fixtures\sg_manual_snapshot\cpf_v044.json `
  --srs-input .\tests\fixtures\sg_manual_snapshot\srs_v044.json `
  --tax-input .\tests\fixtures\sg_manual_snapshot\tax_v044.json `
  --hdb-loan-input .\tests\fixtures\sg_manual_snapshot\hdb_loan_v044.json `
  --out-dir .\reports\personal_cfo_agent\sg_snapshot_v044_fixture
```

The command does not load `.env.local` and does not run broker live reads, Moomoo account discovery, CPF/IRAS/HDB portal automation, bank connectivity, or browser automation.

## Outputs

The command writes under ignored `reports/` paths:

- `cpf_snapshot_ledger.csv`
- `srs_snapshot_ledger.csv`
- `tax_snapshot_ledger.csv`
- `hdb_loan_snapshot_ledger.csv`
- `sg_retirement_tax_summary.json`
- `sg_retirement_tax_warnings.md`
- `SG_RETIREMENT_TAX_SNAPSHOT_V044.md`

Generated reports and local personal finance history must not be committed.

## Rules

- Missing CPF, SRS, or HDB `snapshot_date` fails closed.
- Missing tax `year_of_assessment` fails closed.
- Missing optional CPF or SRS balance fields warn and keep review required.
- Missing tax availability flags warn and keep review required.
- Missing HDB loan availability flags warn.
- Missing HDB linked property hash warns.
- CPF and SRS are retirement and tax-wrapper buckets.
- Tax records are informational and review-only, not filing or advice.
- HDB loan records are manual snapshots, not an HDB connector.

## Warning Codes

- `CPF_SNAPSHOT_MISSING`
- `CPF_BALANCE_MISSING`
- `CPF_REVIEW_REQUIRED`
- `SRS_SNAPSHOT_MISSING`
- `SRS_BALANCE_MISSING`
- `SRS_TAX_WRAPPER_REVIEW`
- `TAX_SNAPSHOT_MISSING`
- `TAX_DATA_INCOMPLETE`
- `TAX_REVIEW_REQUIRED`
- `HDB_LOAN_SNAPSHOT_MISSING`
- `HDB_LOAN_BALANCE_MISSING`
- `HDB_LOAN_PROPERTY_LINK_MISSING`
- `SG_SNAPSHOT_GENERATED_OK`
- `SG_SNAPSHOT_GENERATED_WITH_WARNINGS`
