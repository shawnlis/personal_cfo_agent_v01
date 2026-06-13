# Personal CFO Agent v0.1

“This is a personal finance aggregation and risk dashboard, not investment, tax, estate, insurance, or trading advice.”

Personal CFO Agent v0.1 is a standalone, API-first asset aggregation foundation. It is not part of AI PM Agent and does not import or call any AI PM Agent path.

## What v0.1 Does

- Defines a read-only provider contract for asset, cash, position, and balance reads.
- Implements IBKR, Moomoo, and Tiger as Level 1 API contract stubs with guarded Level 2 readiness skeletons.
- Implements a Level 0 manual snapshot provider for fixtures, unsupported platforms, property values, and mortgage balances.
- Provides a structured JSON manual snapshot workflow for unsupported assets and manually entered liabilities.
- Normalizes provider data into a stable asset ledger with hashed account IDs.
- Writes a dated report bundle under `reports/personal_cfo_agent/v01/<YYYYMMDD>/`.

## Provider Levels

- Level 0: fixture/manual snapshot only, no network, no real credentials.
- Level 1: API contract stub, no live connection, validates config and output schema.
- Level 2: read-only live connector, network allowed only when an explicit CLI flag is passed, and no account-write surfaces are exposed.

## CLI

```powershell
python scripts/personal_cfo_agent.py
python scripts/personal_cfo_agent.py --write-manual-template manual_snapshots/manual_snapshot_template.json
python scripts/personal_cfo_agent.py --validate-manual-snapshot manual_snapshots/my_snapshot.json
python scripts/personal_cfo_agent.py --manual-snapshot tests/fixtures/manual_snapshot_sample.json --as-of-date 20260614
python scripts/personal_cfo_agent.py --manual-snapshot tests/fixtures/manual_snapshot/sample_manual_assets_v010.json --out-dir reports/personal_cfo_agent/v010_final_smoke
python scripts/personal_cfo_agent.py --allow-live-read
```

Default behavior is safe: all live providers are disabled, manual snapshots are not auto-enabled, no network call is made, and the runner exits with no generated reports when no provider is enabled.

## Outputs

Generated outputs are ignored by Git:

- `PERSONAL_CFO_AGENT_V010.md`
- `provider_sync_summary.json`
- `normalized_asset_ledger.csv`
- `net_worth_summary.csv`
- `liquidity_summary.csv`
- `currency_exposure.csv`
- `provider_warning_summary.csv`
- `personal_cfo_warnings.md`

## v0.1 Connector Roadmap

- v0.1.1: IBKR read-only live proof.
- v0.1.2: Moomoo read-only live proof.
- v0.1.3: Tiger read-only live proof.
- v0.1.4: Structured manual snapshot workflow.

Each proof should be added independently, guarded by `--allow-live-read`, and covered by tests that confirm account-write methods are not exposed.
