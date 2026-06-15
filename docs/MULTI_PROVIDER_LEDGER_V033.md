# Multi-provider Normalized Ledger v0.3.3

v0.3.3 adds an offline merge foundation for already-generated normalized ledger bundles.

This workflow combines normalized outputs from manual snapshots, IBKR, Tiger, and Moomoo into one audit/reconciliation ledger. It does not connect to brokers, call broker SDKs, refresh account data, move money, place orders, or produce investment advice.

## Command

```powershell
python .\scripts\personal_cfo_agent.py `
  --merge-provider-bundles `
  --input-root .\reports\personal_cfo_agent `
  --out-dir .\reports\personal_cfo_agent\merged_v033
```

Fixture mode uses synthetic data only:

```powershell
python .\scripts\personal_cfo_agent.py `
  --merge-provider-bundles `
  --fixture-mode `
  --out-dir .\reports\personal_cfo_agent\merged_v033_fixture
```

## Outputs

Generated files stay under ignored `reports/` paths:

- `merged_normalized_ledger.csv`
- `merged_provider_summary.json`
- `account_source_map.json`
- `merge_warnings.md`
- `MERGED_LEDGER_V033.md`

The merged ledger preserves provider, account hash, source bundle or snapshot id, asset fields, as-of date, source confidence, normalization warnings, and merge warnings. It does not preserve raw account IDs.

## Deduplication

The merge layer is conservative. The same symbol across different providers or account hashes is preserved. The same symbol within the same provider, account hash, and source is flagged with `POSSIBLE_DUPLICATE_POSITION` instead of being deleted.

## Warning Codes

- `PROVIDER_BUNDLE_MISSING`
- `PROVIDER_SCHEMA_MISMATCH`
- `PROVIDER_SUMMARY_MISSING`
- `ACCOUNT_HASH_MISSING`
- `SYMBOL_MISSING`
- `CURRENCY_MISSING`
- `AS_OF_DATE_MISSING`
- `POSSIBLE_DUPLICATE_POSITION`
- `MARKET_VALUE_MISSING`
- `COST_BASIS_MISSING`
- `STALE_PROVIDER_BUNDLE`
- `MIXED_AS_OF_DATES`
- `EMPTY_PROVIDER_LEDGER`
- `MERGE_COMPLETED_WITH_WARNINGS`
- `MERGE_COMPLETED_OK`

## Safety Boundaries

IBKR, Tiger, and Moomoo are accepted read-only providers with supervised proof bundles. Manual snapshot remains supported. v0.3.3 only merges existing local normalized outputs.

Real report bundles remain local, ignored, and uncommitted. The merge output is audit and reconciliation infrastructure, not investment advice.
