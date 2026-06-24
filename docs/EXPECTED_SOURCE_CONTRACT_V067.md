# Expected Source Contract v0.6.7

The expected source contract is a local-only safety gate for net worth refreshes.
It tells the refresh which broker and manual layers are expected for a run, so a
partial refresh is visible and cannot be silently confirmed into history.

## Scope

This feature is offline validation and reporting only.

It does not:

- run broker reads
- run Moomoo discovery
- run Webull token preflight
- connect to banks, CPF, IRAS, HDB, SingPass, or browsers
- place orders, move cash, file taxes, or produce recommendations
- print private input values, balances, positions, raw account IDs, or secrets

## Input Shape

The unified private input file may include:

```json
{
  "expected_sources": {
    "providers": [
      {"provider": "ibkr", "required": true},
      {"provider": "moomoo", "required": false},
      {"provider": "tiger", "required": false}
    ],
    "manual_layers": {
      "manual_nav": "required",
      "property_mortgage": "optional",
      "sg_retirement_tax": "optional"
    }
  }
}
```

Provider entries may be required or optional. Manual layers currently support:

- `manual_nav`
- `property_mortgage`
- `sg_retirement_tax`

Missing `expected_sources` remains compatible with older local inputs.

As of the v0.6.9 input UX polish, the visible form no longer asks the user to
choose these requirements. New form exports and the committed example input use
a complete-refresh default: IBKR, Moomoo, Tiger, manual NAV, property/mortgage,
and Singapore manual layers are all marked required. The contract remains a
quality gate only; it does not trigger broker reads.

## Behavior

During `--run-net-worth-refresh`, the contract is read from the private input
file and passed to the data quality summary and integrity guard.

Required broker providers:

- appear in the provider gate even if they were not requested in
  `--refresh-brokers`
- produce `DATA_QUALITY_EXPECTED_SOURCE_MISSING` if not available
- block confirmed history writes through `INTEGRITY_EXPECTED_SOURCE_MISSING`

Required manual layers:

- are checked against local conversion outputs only
- produce the same data-quality warning when unavailable
- block confirmed history writes until the layer is available

Optional sources are reported as optional missing when absent, but they do not
block confirmed history writes.

## Outputs

The data quality summary includes:

- `expected_sources.providers_required`
- `expected_sources.providers_optional`
- `expected_sources.manual_layers_required`
- `expected_sources.manual_layers_optional`
- provider gate `expected_required` and `expected_optional` fields
- source provenance `expected_requirement` fields

The integrity guard includes:

- required expected providers
- required manual layers
- missing required manual layers
- blocking warning codes

All outputs are redacted and contain statuses/counts only.

## Safe Flow

```powershell
python .\scripts\personal_cfo_agent.py `
  --run-net-worth-refresh `
  --refresh-brokers none `
  --input-file .\private_inputs\personal_cfo_input.local.json `
  --out-dir .\reports\personal_cfo_agent\net_worth_refresh_local
```

If a required source is missing, inspect:

- `data_quality_summary.json`
- `integrity_guard/net_worth_integrity_summary.json`
- `snapshot_review/snapshot_review.html`

Do not use `--confirm-snapshot-history-write` until the required sources are
available and the integrity guard reports ready.
