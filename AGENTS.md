# Personal CFO Agent Instructions

This repository handles private personal finance data. Keep every change
local-first, read-only-first, and audit-first.

## Hard Boundaries

- Do not print, commit, or stage `.env.local`, credentials, tokens, private keys,
  raw account IDs, raw account numbers, private input files, exact balances,
  exact positions, generated reports, or screenshots containing private values.
- Do not run broker live reads, Webull token preflight, Moomoo discovery, bank,
  CPF, IRAS, HDB, SingPass, browser automation, or external account workflows
  unless the user explicitly requests that exact action for that turn.
- Do not place orders, preview orders, modify orders, move cash, file taxes,
  create scheduler jobs, or generate recommendation output.
- Keep `NEXT_CHAT_HANDOFF_2026-06-15.md` untracked unless the user explicitly
  asks to commit it.

## Default Workflow

1. Inspect `git status --short --branch` before editing.
2. Read the relevant docs and tests before changing behavior.
3. Keep changes PR-sized and focused.
4. Use deterministic fixtures and mocked tests for private finance behavior.
5. Run focused tests and `python .\scripts\dev_validate.py` before finalizing.
6. Commit generated source, tests, and docs only. Never commit `reports/` or
   local private input folders.

## Current User-Facing Flow

The preferred manual flow is the unified private input center:

```powershell
python .\scripts\personal_cfo_agent.py --private-input-center-form --out-dir .\reports\personal_cfo_agent\private_input_center_local
python .\scripts\personal_cfo_agent.py --private-input-center-local-app --input-file .\private_inputs\personal_cfo_input.local.json --out-dir .\reports\personal_cfo_agent\private_input_center_local
python .\scripts\personal_cfo_agent.py --fetch-fx-rates --base-currency SGD --fx-currencies USD,CNY,HKD --out-file .\private_inputs\fx_rates.local.json
python .\scripts\personal_cfo_agent.py --validate-private-input-center --input-file .\private_inputs\personal_cfo_input.local.json
python .\scripts\personal_cfo_agent.py --run-net-worth-refresh --refresh-brokers none --input-file .\private_inputs\personal_cfo_input.local.json --out-dir .\reports\personal_cfo_agent\net_worth_refresh_local
python .\scripts\personal_cfo_agent.py --snapshot-review --refresh-dir .\reports\personal_cfo_agent\net_worth_refresh_local --out-dir .\reports\personal_cfo_agent\net_worth_refresh_local\snapshot_review
python .\scripts\personal_cfo_agent.py --dashboard-v4 --refresh-dir .\reports\personal_cfo_agent\net_worth_refresh_local --fx-rates-file .\private_inputs\fx_rates.local.json --out-dir .\reports\personal_cfo_agent\dashboard_v4_local
python .\scripts\personal_cfo_agent.py --net-worth-doctor --input-file .\private_inputs\personal_cfo_input.local.json --refresh-dir .\reports\personal_cfo_agent\net_worth_refresh_local --fx-rates-file .\private_inputs\fx_rates.local.json --out-dir .\reports\personal_cfo_agent\net_worth_doctor_v062_local
python .\scripts\personal_cfo_agent.py --local-workbench --input-file .\private_inputs\personal_cfo_input.local.json --refresh-dir .\reports\personal_cfo_agent\net_worth_refresh_local --fx-rates-file .\private_inputs\fx_rates.local.json --dashboard-dir .\reports\personal_cfo_agent\dashboard_current --out-dir .\reports\personal_cfo_agent\local_workbench
```

Manual-only refresh must use no external provider reads. Broker refresh requires
explicit `--allow-live-read` and must stay on existing read-only provider paths.
Confirmed history writes should be made only after snapshot review and dashboard
review pass.

The input form should not show Expected Sources checkboxes. New form exports use
the complete-refresh expected-source contract by default; this is a quality gate
only and must not trigger broker reads by itself. Public FX fetch is allowed only
through the explicit CLI/local-app action and must not use credentials or print
rate values.
