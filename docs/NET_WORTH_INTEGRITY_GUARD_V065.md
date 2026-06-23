# Net Worth Integrity Guard v0.6.5

v0.6.5 adds a local-only confirmation gate before a refresh can write confirmed
net worth history.

The guard exists because live broker refreshes can fail partially. A dashboard
may still be useful for review, but an incomplete broker read must not silently
pollute long-term history.

## Where It Runs

`--run-net-worth-refresh` now writes review outputs first:

- `manual_layers/`
- `provider_inputs/`
- `merged/`
- `snapshots/`
- `dashboard/`
- `integrity_guard/`
- `data_quality_summary.json`

Only after the guard is ready will `--confirm-snapshot-history-write` write
`snapshots_confirmed/`.

## Confirmation Command

```powershell
python .\scripts\personal_cfo_agent.py `
  --run-net-worth-refresh `
  --refresh-brokers none `
  --confirm-snapshot-history-write `
  --input-file .\private_inputs\personal_cfo_input.local.json `
  --fx-rates-input .\private_inputs\fx_rates.local.json `
  --confirmed-history-dir .\reports\personal_cfo_agent\confirmed_net_worth_history_manual `
  --out-dir .\reports\personal_cfo_agent\net_worth_refresh_local
```

`--confirmed-history-dir` is optional. When provided, the guard compares the new
refresh against a previously reviewed local history folder. When omitted, it
looks for `snapshots_confirmed/` under the current refresh directory.

## Blocking Checks

The guard blocks confirmed history writes when:

- a requested broker is missing from merged account NAV
- a requested broker has account NAV rows but no provider-reported NAV marker
- total NAV cannot be derived from local generated outputs
- mixed account NAV currencies require FX but the FX file is missing or incomplete
- upstream merge/snapshot/dashboard warnings indicate mixed as-of dates
- upstream warnings indicate stale provider data
- the new total has a large change versus confirmed history and needs manual review

Manual-only refreshes can still be confirmed when local inputs validate and no
blocking guard conditions are present.

## Outputs

The guard writes:

- `integrity_guard/net_worth_integrity_summary.json`
- `integrity_guard/net_worth_integrity_warnings.md`
- `integrity_guard/NET_WORTH_INTEGRITY_GUARD_V065.md`

The outputs are redacted. They include only status, row counts, provider
coverage, FX completeness, and warning codes. They do not include exact NAV,
balances, positions, raw account IDs, account hashes, private input values,
`.env.local` values, API keys, tokens, or secrets.

## Warning Codes

- `INTEGRITY_GUARD_OK`
- `INTEGRITY_GUARD_BLOCKED`
- `INTEGRITY_BROKER_REQUESTED_MISSING`
- `INTEGRITY_PROVIDER_NAV_MISSING`
- `INTEGRITY_TOTAL_NAV_UNAVAILABLE`
- `INTEGRITY_MIXED_CURRENCY_BLOCKED`
- `INTEGRITY_FX_REQUIRED`
- `INTEGRITY_MIXED_AS_OF_DATES`
- `INTEGRITY_STALE_PROVIDER_DATA`
- `INTEGRITY_SNAPSHOT_PENDING_REVIEW`
- `INTEGRITY_CONFIRMED_HISTORY_MISSING`
- `INTEGRITY_NAV_CHANGE_REVIEW_REQUIRED`

## Boundaries

The integrity guard is offline only. It must not run broker reads, Webull token
preflight, Moomoo discovery, account diagnostics, browser automation, external
uploads, trading, cash movement, tax filing, or recommendation output.

Generated guard outputs stay under ignored `reports/` paths.
