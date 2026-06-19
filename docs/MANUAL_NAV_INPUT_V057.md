# Unified Manual NAV Input v0.5.7

v0.5.7 adds a local-only manual account NAV input workflow for brokerage and manual account sources such as Syfe Trade, Webull, uSMART, and other manually reviewed accounts.

This is not a broker connector. It does not call broker APIs, browser sessions, bank systems, CPF, IRAS, HDB, SingPass, or external accounts.

## Workflow

Generate a local static worksheet:

```powershell
python .\scripts\personal_cfo_agent.py `
  --manual-nav-form `
  --out-dir .\reports\personal_cfo_agent\manual_nav_form_v057
```

Initialize a local ignored JSON input file:

```powershell
python .\scripts\personal_cfo_agent.py `
  --init-manual-nav-input `
  --out-file .\private_inputs\manual_nav_input.local.json
```

Validate the local input file:

```powershell
python .\scripts\personal_cfo_agent.py `
  --validate-manual-nav-input `
  --input-file .\private_inputs\manual_nav_input.local.json
```

Convert the input into a provider-bundle-compatible output:

```powershell
python .\scripts\personal_cfo_agent.py `
  --manual-nav-to-provider-bundle `
  --input-file .\private_inputs\manual_nav_input.local.json `
  --out-dir .\reports\personal_cfo_agent\manual_nav_v057_local
```

The generated provider bundle can be consumed by the existing offline merge flow:

```powershell
python .\scripts\personal_cfo_agent.py `
  --merge-provider-bundles `
  --input-root .\reports\personal_cfo_agent `
  --out-dir .\reports\personal_cfo_agent\merged_v057_manual_nav
```

## Input Schema

Top-level fields:

- `schema_version`
- `snapshot_date`
- `base_currency`
- `source_type`
- `review_required`
- `accounts`

Each account uses:

- `provider_label`: `syfe_trade`, `webull`, `usmart`, or `other`
- `account_label`: stable label only, not an account number
- `account_type`: `brokerage`, `robo`, `cash`, `retirement`, or `other`
- `base_currency`
- `account_nav`
- `cash_total` optional
- `securities_market_value` optional
- `margin_or_debt` optional
- `as_of_date`
- `source_type`: `app_manual`, `statement_manual`, `screenshot_manual`, or `other`
- `source_confidence`
- `review_required`
- `notes` optional

## Privacy Rules

Do not enter raw account numbers, raw account IDs, NRIC, FIN, passwords, API keys, tokens, secrets, or login details. The converter derives `account_id_hash` locally from `provider_label`, `account_label`, and `CFO_ACCOUNT_HASH_SALT`. If the hash salt is missing, provider-bundle conversion fails closed.

The provider bundle emits only hashed account IDs. It does not emit account labels or raw identifiers.

## Warning Codes

- `MANUAL_NAV_FORM_GENERATED`
- `MANUAL_NAV_INPUT_INITIALIZED`
- `MANUAL_NAV_INPUT_EXISTS_SKIPPED`
- `MANUAL_NAV_OVERWRITE_USED`
- `MANUAL_NAV_INPUT_MISSING`
- `MANUAL_NAV_SCHEMA_INVALID`
- `MANUAL_NAV_REQUIRED_FIELD_MISSING`
- `MANUAL_NAV_OPTIONAL_SPLIT_MISSING`
- `MANUAL_NAV_HASH_SALT_MISSING`
- `MANUAL_NAV_RAW_IDENTIFIER_DETECTED`
- `MANUAL_NAV_MIXED_CURRENCIES`
- `MANUAL_NAV_VALIDATION_OK`
- `MANUAL_NAV_VALIDATION_WITH_WARNINGS`
- `MANUAL_NAV_VALIDATION_FAILED`
- `MANUAL_NAV_BUNDLE_GENERATED_OK`
- `MANUAL_NAV_BUNDLE_GENERATED_WITH_WARNINGS`
- `MANUAL_NAV_BUNDLE_FAILED`

## Output Files

The provider bundle writes:

- `normalized_asset_ledger.csv`
- `provider_sync_summary.json`
- `manual_nav_warnings.md`
- `MANUAL_NAV_INPUT_V057.md`

Generated outputs remain under ignored local paths and must not be committed.
