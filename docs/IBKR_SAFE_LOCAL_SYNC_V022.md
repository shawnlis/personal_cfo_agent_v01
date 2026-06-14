# IBKR Safe Local Sync v0.2.2

## Purpose

This workflow makes the v0.2.1 supervised IBKR read-only proof easier to rerun locally while keeping the same safety boundary. It adds a manual PowerShell template, a Python wrapper, and a local sync index under ignored `reports/` paths.

## Prerequisites

- TWS or IB Gateway is installed and started manually by the operator.
- IBKR API access is enabled in read-only mode.
- The local Python environment can run `python .\scripts\personal_cfo_agent.py`.
- `ibapi` is installed in the Python environment used for live IBKR reads.
- The repo-local `.env.local` file is configured and remains ignored by git.

## Manual TWS / IB Gateway Step

The workflow does not start TWS or IB Gateway. Open TWS or IB Gateway yourself, confirm the API port matches your local configuration, and confirm API read-only mode before running a live sync.

## `.env.local` Setup

Use `.env.example` as the placeholder reference and keep real values only in `.env.local` or OS environment variables:

```text
CFO_IBKR_ENABLED=true
CFO_IBKR_HOST=
CFO_IBKR_PORT=
CFO_IBKR_CLIENT_ID=
```

Optional sensitive values such as the account filter and account-hash salt must be kept only in `.env.local` or OS environment variables. Leave them out unless needed for your local setup.

Do not commit `.env.local`, account identifiers, salts, passwords, tokens, local logs, screenshots, cookies, or generated report outputs.

## Read-Only Safety Boundary

- `read_only`: true
- `trading_enabled`: false
- `order_placement_enabled`: false
- `cash_transfer_enabled`: false
- `recommendation_output`: false
- `raw_account_ids_output`: false
- `env_file_committed`: false
- `reports_committed`: false

The workflow only calls the existing IBKR diagnostics, readiness, and explicitly gated read-only data path. It does not add automatic execution, account-write behavior, recommendation output, screenshots, cookies, or browser automation.

## Run the PowerShell Template

The template is meant for a supervised local run:

```powershell
Copy-Item .\scripts\run_ibkr_readonly_sync.ps1.template .\scripts\run_ibkr_readonly_sync.local.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\run_ibkr_readonly_sync.local.ps1
```

The template asks you to confirm that TWS or IB Gateway is already open with API read-only mode enabled and that this is read-only sync only. It then runs connection diagnostics, readiness, and the gated live read only if the prior checks have no warning codes.

## Run the Python Wrapper

Diagnostics and readiness only:

```powershell
python .\scripts\run_ibkr_readonly_sync.py --diagnostics-only
```

No-network finalization dry smoke:

```powershell
python .\scripts\run_ibkr_readonly_sync.py --dry-smoke --out-root .\reports\personal_cfo_agent\ibkr_sync_dry_smoke
```

Dry smoke is for PR finalization and local validation only. It runs the readiness check, writes only the ignored local sync index, and does not run connection diagnostics, open a broker socket, pass `--allow-live-read`, or create a report bundle.

Full supervised read-only sync:

```powershell
python .\scripts\run_ibkr_readonly_sync.py --allow-live-read
```

The wrapper refuses the live read unless `--allow-live-read` is present. Each run creates a timestamped local directory under `reports/personal_cfo_agent/ibkr_sync/` and updates `reports/personal_cfo_agent/ibkr_sync/ibkr_sync_index.json`.

## Inspect Output

After a successful live sync, inspect the printed output path. Expected report files match the existing Personal CFO report bundle, including `provider_sync_summary.json`, `normalized_asset_ledger.csv`, and warning summaries. The sync index records status, warning codes, row counts, redaction confirmation, ignored-report confirmation, and the safety boundary.

## Why Reports Stay Ignored

IBKR outputs can contain sensitive personal financial data. The repo ignores `reports/`, including the sync output folders and `ibkr_sync_index.json`. The index is local operational state, not source code or documentation.

## What Not To Commit

- `.env.local` or any file with local environment values.
- `reports/` contents, including sync indexes and generated report bundles.
- Raw account identifiers, exact sensitive balances, screenshots, cookies, or local broker logs.
- Any temporary local PowerShell copy such as `run_ibkr_readonly_sync.local.ps1`.

## If Sync Returns Zero Rows

Do not treat a zero-row run as an accepted sync. Check the data-path diagnostics for managed-account, account filter, position callback, and cash callback state. Common causes are an account filter mismatch, TWS/Gateway not fully authorizing the API session, callbacks timing out, or no readable positions/cash for the selected account scope.

## No Task Scheduler Task Yet

No Windows Task Scheduler task is created in v0.2.2. The workflow remains a manual local run until the read-only rerun path, index behavior, redaction checks, and retention rules have been reviewed.
