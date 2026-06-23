# Unified Private Input Center v0.5.8

v0.5.8 adds a single local-only input workflow for the manual Personal CFO layers.

It is the preferred local input workflow when you want one file for:

- manual account NAVs for Syfe Trade, Webull, uSMART, other manual accounts, and unvested shares
- property and mortgage snapshots
- CPF
- SRS
- tax review snapshot
- HDB loan snapshot
- explicit local FX rates for dashboard conversion

This is not a connector. It does not connect to brokers, banks, CPF, IRAS, HDB, SingPass, browsers, or external accounts. It does not file taxes, provide advice, move cash, trade, schedule jobs, or generate recommendations.

## What Is Committed

Only safe placeholders are committed:

- `templates/private_inputs/personal_cfo_input.example.json`
- `templates/private_inputs/personal_cfo_input_form.html`

Real values belong only in ignored local files such as:

- `private_inputs/personal_cfo_input.local.json`
- `local_private_inputs/personal_cfo_input.local.json`
- files under `reports/personal_cfo_agent/private_inputs/`

Generated outputs stay under ignored `reports/` paths and must not be committed.

## Generate The Local Form

```powershell
python .\scripts\personal_cfo_agent.py `
  --private-input-center-form `
  --out-dir .\reports\personal_cfo_agent\private_input_center_v058
```

The generated form is static and local. It has no external scripts, styles, browser beacon calls, or external data transmission.
It includes only local inline JavaScript for building an advanced JSON preview or posting to the optional localhost save app described below. The user-facing form intentionally keeps one main save path: `Save to local JSON`.

As of v0.6.9, the JSON textarea is inside an `Advanced JSON preview` panel so
the day-to-day form stays focused on the values the user edits.

The form intentionally keeps the visible inputs short: one global snapshot date, one base currency, optional local FX rates, manual NAV rows, unvested shares, property value, mortgage balance, CPF IA, CPF Balance, SRS total, tax year, and income tax payable availability. CPF IA and CPF Balance are automatically summed into the downstream CPF `total` field so existing snapshot and dashboard schemas remain compatible. Internal hashes required by the JSON schema are generated automatically from local labels/dates; raw account IDs, raw addresses, NRIC/FIN, and government identifiers are not requested.

FX values are optional. Blank or zero FX entries are not treated as valid rates.
When positive explicit rates are present in the unified input file,
`--run-net-worth-refresh` can extract them into a local generated FX file for
Dashboard v3/v4 and integrity checks.

## Open A Local Save App

For day-to-day editing, use the local save app so the form can write the ignored JSON file without making you find the file path in the browser:

```powershell
python .\scripts\personal_cfo_agent.py `
  --private-input-center-local-app `
  --input-file .\private_inputs\personal_cfo_input.local.json `
  --out-dir .\reports\personal_cfo_agent\private_input_center_local
```

Open the printed `http://127.0.0.1:8765/` URL, edit the form, and click `Save to local JSON`.
The app binds to localhost only, validates the JSON before writing, and returns only save status plus warning codes. It does not print values, connect to brokers, or use external services.

## Initialize One Local Input File

```powershell
python .\scripts\personal_cfo_agent.py `
  --init-private-input-center `
  --out-file .\private_inputs\personal_cfo_input.local.json
```

Existing local files are not overwritten by default. Use `--overwrite` only after backing up or intentionally replacing the existing local file.

## Validate Without Printing Values

```powershell
python .\scripts\personal_cfo_agent.py `
  --validate-private-input-center `
  --input-file .\private_inputs\personal_cfo_input.local.json
```

Validation reports only field presence, row counts, provider labels, currencies, and warning codes. It does not print exact private values.

Validation fails closed for missing required dates, missing manual account NAV, missing required section shape, raw identifiers, NRIC/FIN-like identifiers, or raw account/government identifier fields.

Optional cash/security split fields warn only. Mixed manual NAV currencies warn and are not silently converted.

## Generate Existing Compatible Outputs

```powershell
python .\scripts\personal_cfo_agent.py `
  --private-input-center-to-snapshots `
  --input-file .\private_inputs\personal_cfo_input.local.json `
  --out-dir .\reports\personal_cfo_agent\private_input_center_v058_local
```

The converter reuses existing modules and writes:

- `manual_nav/normalized_asset_ledger.csv`
- `manual_nav/provider_sync_summary.json`
- `manual_nav/manual_nav_warnings.md`
- `manual_nav/MANUAL_NAV_INPUT_V057.md`
- `property_mortgage/property_asset_ledger.csv`
- `property_mortgage/mortgage_liability_ledger.csv`
- `property_mortgage/property_equity_summary.json`
- `property_mortgage/property_mortgage_warnings.md`
- `property_mortgage/PROPERTY_MORTGAGE_SNAPSHOT_V043.md`
- `sg_retirement_tax/cpf_snapshot_ledger.csv`
- `sg_retirement_tax/srs_snapshot_ledger.csv`
- `sg_retirement_tax/tax_snapshot_ledger.csv`
- `sg_retirement_tax/hdb_loan_snapshot_ledger.csv`
- `sg_retirement_tax/sg_retirement_tax_summary.json`
- `sg_retirement_tax/sg_retirement_tax_warnings.md`
- `sg_retirement_tax/SG_RETIREMENT_TAX_SNAPSHOT_V044.md`

The manual NAV provider bundle remains compatible with the existing merge flow:

```powershell
python .\scripts\personal_cfo_agent.py `
  --merge-provider-bundles `
  --input-root .\reports\personal_cfo_agent `
  --out-dir .\reports\personal_cfo_agent\merged_v058_private_input_center
```

## Existing Split Commands Still Work

The v0.5.3 and v0.5.7 split workflows remain supported:

- `--init-private-input-kit`
- `--validate-private-inputs`
- `--run-manual-snapshot-chain`
- `--init-manual-nav-input`
- `--validate-manual-nav-input`
- `--manual-nav-to-provider-bundle`

Use the unified input center when you want one human-friendly file and one HTML form. Use split commands only when you intentionally want separate JSON files or are debugging one layer. The old dedicated manual NAV HTML form is no longer a user-facing entrypoint.

## Warning Codes

- `PRIVATE_INPUT_CENTER_FORM_GENERATED`
- `PRIVATE_INPUT_CENTER_INITIALIZED`
- `PRIVATE_INPUT_CENTER_EXISTS_SKIPPED`
- `PRIVATE_INPUT_CENTER_OVERWRITE_USED`
- `PRIVATE_INPUT_CENTER_INPUT_MISSING`
- `PRIVATE_INPUT_CENTER_SCHEMA_INVALID`
- `PRIVATE_INPUT_CENTER_REQUIRED_FIELD_MISSING`
- `PRIVATE_INPUT_CENTER_OPTIONAL_FIELD_MISSING`
- `PRIVATE_INPUT_CENTER_RAW_IDENTIFIER_DETECTED`
- `PRIVATE_INPUT_CENTER_VALIDATION_OK`
- `PRIVATE_INPUT_CENTER_VALIDATION_WITH_WARNINGS`
- `PRIVATE_INPUT_CENTER_VALIDATION_FAILED`
- `PRIVATE_INPUT_CENTER_GENERATED_OK`
- `PRIVATE_INPUT_CENTER_GENERATED_WITH_WARNINGS`
- `PRIVATE_INPUT_CENTER_GENERATION_FAILED`

The converter may also surface warning codes from the reused manual NAV, property/mortgage, and Singapore snapshot modules.

## Boundaries

Do not enter raw account numbers, raw account IDs, NRIC, FIN, passwords, API keys, tokens, tax reference numbers, raw government identifiers, bank account numbers, or raw property addresses.

The workflow is offline and manual. It must not use browser automation, external APIs, broker connections, bank portals, CPF, IRAS, HDB, or SingPass. It must not move money, place orders, file taxes, or generate recommendation output.
