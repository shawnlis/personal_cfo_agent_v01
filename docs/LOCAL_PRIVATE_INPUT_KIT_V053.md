# Local Private Input Kit v0.5.3

The v0.5.3 Local Private Input Kit provides safe local-only templates for real manual Personal CFO snapshots.

It does not connect to brokers, banks, CPF, IRAS, HDB, SingPass, browsers, or external accounts. It does not file taxes, provide tax advice, move cash, trade, schedule jobs, or generate recommendations.

## What Is Committed

Only placeholder examples are committed:

- `templates/private_inputs/property_snapshot.example.json`
- `templates/private_inputs/mortgage_snapshot.example.json`
- `templates/private_inputs/cpf_snapshot.example.json`
- `templates/private_inputs/srs_snapshot.example.json`
- `templates/private_inputs/tax_snapshot.example.json`
- `templates/private_inputs/hdb_loan_snapshot.example.json`

These files are schema examples only. Real values belong only in ignored local folders.

## Preferred Unified Workflow

v0.5.8 adds `docs/UNIFIED_PRIVATE_INPUT_CENTER_V058.md` and a single ignored local input file option:

```powershell
python .\scripts\personal_cfo_agent.py `
  --init-private-input-center `
  --out-file .\private_inputs\personal_cfo_input.local.json
```

Use the unified private input center when you want one human-friendly local file covering manual NAV, property/mortgage, CPF, SRS, tax, and HDB loan sections. The split v0.5.3 commands below still work and remain useful for focused debugging or separate source files.

## Ignored Local Input Folders

Use one of these ignored local paths for real manual inputs:

- `private_inputs/`
- `local_private_inputs/`
- `reports/personal_cfo_agent/private_inputs/`

Do not commit real manual input files, generated reports, raw addresses, NRIC/FIN, government identifiers, account numbers, secrets, or exact private values.

## Initialize Local Files

```powershell
python .\scripts\personal_cfo_agent.py `
  --init-private-input-kit `
  --out-dir .\private_inputs
```

By default, existing local files are not overwritten. To replace local files intentionally:

```powershell
python .\scripts\personal_cfo_agent.py `
  --init-private-input-kit `
  --out-dir .\private_inputs `
  --overwrite
```

Use `--overwrite` only when you have backed up or no longer need the existing local files.

## Edit Locally

Edit the ignored files under `private_inputs/`. The templates do not require raw addresses, NRIC, FIN, government identifiers, bank account numbers, CPF account numbers, HDB account numbers, or tax reference numbers.

Use labels and hashes instead:

- `property_id_hash`
- `loan_id_hash`
- `linked_property_id_hash`
- provider or lender labels

For property ownership, `ownership_pct` may be entered as a decimal fraction such as `0.50` or as a percent string such as `50%`. It is normalized internally before equity is calculated.

## Validate Without Printing Values

```powershell
python .\scripts\personal_cfo_agent.py `
  --validate-private-inputs `
  --input-dir .\private_inputs
```

Validation reports only file presence, row counts, and warning codes. It does not print private values.

Validation fails closed for missing required fields, raw identifiers, unusable property ownership/valuation values, or unusable mortgage balances. Optional missing fields and stale property valuation dates produce warnings.

## Run Manual Snapshot Chain

```powershell
python .\scripts\personal_cfo_agent.py `
  --run-manual-snapshot-chain `
  --input-dir .\private_inputs `
  --out-dir .\reports\personal_cfo_agent\manual_snapshot_v053_local
```

The chain runs the existing offline property/mortgage and Singapore manual snapshot generators using local ignored inputs.

Generated outputs stay under ignored `reports/` paths and must not be committed.

## Warning Codes

- `PRIVATE_INPUT_KIT_INITIALIZED`
- `PRIVATE_INPUT_OVERWRITE_USED`
- `PRIVATE_INPUT_FILE_EXISTS_SKIPPED`
- `PRIVATE_INPUT_FILE_MISSING`
- `PRIVATE_INPUT_SCHEMA_INVALID`
- `PRIVATE_INPUT_REQUIRED_FIELD_MISSING`
- `PRIVATE_INPUT_OPTIONAL_FIELD_MISSING`
- `PRIVATE_INPUT_RAW_IDENTIFIER_DETECTED`
- `PRIVATE_INPUT_VALIDATION_OK`
- `PRIVATE_INPUT_VALIDATION_WITH_WARNINGS`
- `PRIVATE_INPUT_VALIDATION_FAILED`
- `PRIVATE_INPUT_CHAIN_GENERATED_OK`
- `PRIVATE_INPUT_CHAIN_GENERATED_WITH_WARNINGS`
- `PRIVATE_INPUT_CHAIN_FAILED`

## Boundaries

The kit is local-only and manual. It must not use SingPass, CPF, IRAS, HDB, bank, broker, or browser automation. It must not create account connectors, upload data, file taxes, provide advice, move money, trade, or generate recommendation instructions.
