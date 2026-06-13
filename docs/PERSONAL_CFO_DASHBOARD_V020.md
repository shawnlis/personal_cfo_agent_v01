# Personal CFO Dashboard v0.2.0

This is a personal finance risk dashboard, not investment, tax, estate, insurance, or trading advice.

## Purpose

The v0.2.0 dashboard consumes normalized asset ledger rows produced by provider and manual snapshot aggregation. CSV ledger files are not a production input path; a CSV fixture exists only for deterministic tests.

## CLI

Run dashboard output from the current provider/manual aggregation:

```powershell
python .\scripts\personal_cfo_agent.py --dashboard --manual-snapshot .\manual_snapshots\my_snapshot.json --out-dir .\reports\personal_cfo_agent\v020_dashboard
```

Optional assumptions JSON:

```powershell
python .\scripts\personal_cfo_agent.py --dashboard --manual-snapshot .\manual_snapshots\my_snapshot.json --dashboard-assumptions .\manual_snapshots\dashboard_assumptions.json --out-dir .\reports\personal_cfo_agent\v020_dashboard
```

The assumptions file may contain:

- `current_age`
- `target_fire_age`
- `annual_spending_target`
- `safe_withdrawal_rate`
- `expected_annual_return`
- `inflation_rate`
- `emergency_buffer_months`
- `base_currency`

## Output Contract

- `PERSONAL_CFO_DASHBOARD_V020.md`
- `net_worth_dashboard.json`
- `asset_allocation.csv`
- `liquidity_dashboard.csv`
- `fire_progress.csv`
- `liability_dashboard.csv`
- `stress_scenarios.csv`
- `dashboard_warnings.md`

Generated dashboards remain under ignored `reports/` paths.

## Calculations

- Total assets, total liabilities, and net worth
- Liquid assets and investable assets
- Currency exposure
- Provider coverage and manual asset share
- Liquidity runway
- FIRE number, coverage ratio, gap, and deterministic years-to-FIRE estimate
- Stress scenario rows for investment, property, mortgage-rate, income, expense, and combined recession cases
- Warning propagation for stale and manual-review rows

## Boundaries

- No live read is enabled by `--dashboard`.
- No trading, order, or cash-transfer methods are added.
- No recommendation, tax, estate, insurance, or trading advice is produced.
- No network access is required for default dashboard execution.
