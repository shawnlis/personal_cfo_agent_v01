# Multi-provider Normalized Ledger v0.3.3

v0.3.3 adds an offline, account-NAV-first merge foundation for already-generated normalized ledger bundles.

This workflow combines normalized outputs from manual snapshots, IBKR, Tiger, and Moomoo into account-level Personal CFO net-worth infrastructure. Account NAV is the primary layer. Position rows are secondary best-effort drilldown data for exposure review and reconciliation. The workflow does not connect to brokers, call broker SDKs, refresh account data, move money, place orders, or produce investment advice.

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

- `merged_account_nav_ledger.csv`
- `merged_account_nav_summary.json`
- `merged_position_ledger.csv`
- `merged_provider_summary.json`
- `account_source_map.json`
- `merge_warnings.md`
- `MERGED_LEDGER_V033.md`

## Account NAV Layer

`merged_account_nav_ledger.csv` is the primary acceptance layer. Each row preserves provider, account hash, source bundle or snapshot id, as-of date, base currency, provider-reported or derived NAV fields, source confidence, and warning codes.

If provider-reported NAV exists, it is treated as the account-level source of truth. If provider-reported NAV is missing, the merger can derive NAV from cash plus positions and emits `ACCOUNT_NAV_DERIVED` plus `ACCOUNT_NAV_MISSING`. If NAV is unavailable, the account row is retained with warnings instead of being silently dropped.

## Position Layer

`merged_position_ledger.csv` is best-effort. Position rows preserve available asset fields and warnings, but missing optional position details do not block account-level NAV output. Position rows are for drilldown and exposure analysis, not the v0.3.3 acceptance gate.

## Deduplication

The merge layer is conservative. The same symbol across different providers or account hashes is preserved. The same symbol within the same provider, account hash, and source is flagged with `POSSIBLE_DUPLICATE_POSITION` instead of being deleted.

## Reconciliation

When both provider-reported account NAV and derived cash-plus-position totals are available, the merger compares them within a small tolerance. Differences emit warning codes rather than hard failures.

## Warning Codes

- `ACCOUNT_NAV_MISSING`
- `ACCOUNT_NAV_DERIVED`
- `ACCOUNT_NAV_PROVIDER_REPORTED`
- `ACCOUNT_NAV_RECONCILIATION_MISMATCH`
- `ACCOUNT_NAV_RECONCILIATION_OK`
- `ACCOUNT_NAV_UNAVAILABLE`
- `POSITION_LEDGER_BEST_EFFORT`
- `POSITION_ROWS_MISSING`
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
