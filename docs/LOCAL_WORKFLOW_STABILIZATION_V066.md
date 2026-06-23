# Local Workflow Stabilization v0.6.6

This document is the delivery standard for the v0.6.x stabilization pass.

The project should now prioritize reliable real local use over new broker or
asset modules. A change is complete only when it is offline-safe, redacted,
tested, documented, and does not rely on operator memory.

## Delivery Standards

1. Unified private input center remains the only user-facing manual input form.
   - The form must not request raw account IDs, NRIC/FIN, raw addresses, or
     secrets.
   - CPF IA and CPF Balance must map into the existing CPF total.
   - Optional FX entries must be ignored unless they are positive explicit
     rates.

2. Local workbench exists as a static launcher.
   - `--local-workbench` must generate a local HTML page and redacted summary.
   - It may check path presence but must not read private values or run broker
     calls.

3. Net worth refresh remains offline by default.
   - `--refresh-brokers none` must not trigger broker reads.
   - Broker refreshes require explicit `--allow-live-read`.

4. Provider gate is visible.
   - Requested, succeeded, failed, missing, and not-requested providers must be
     represented in redacted data quality output.

5. Source provenance is visible.
   - Data quality output must identify whether layers came from local manual
     input, supervised read-only provider bundles, derived snapshots, explicit
     FX, dashboard generation, or integrity guard.

6. Snapshot review gate exists before confirmed history writes.
   - `--snapshot-review` must generate a redacted review page.
   - Confirmed history writes must remain explicit and blocked when integrity
     guard is not ready.

7. Integrity guard remains the write gate.
   - Mixed currency without complete FX, missing requested brokers, stale/mixed
     dates, missing provider NAV, unavailable totals, and abnormal changes must
     block confirmed history writes.

8. Dashboard v4 has a stable current alias.
   - Dashboard v4 CLI generation must sync the latest generated dashboard to
     `reports/personal_cfo_agent/dashboard_current`.

9. Warning codes are human-readable.
   - Doctor, data quality, integrity guard, snapshot review, and dashboard
     outputs must provide safe descriptions for warning codes.

10. Safety boundaries are machine-tested.
    - Tests must cover redaction, no generated reports/private inputs tracked,
      no live read paths for offline commands, no external upload/browser
      markers, and no recommendation/trading/tax-advice wording.

## Validation Gates

Run focused tests after code changes:

```powershell
python -m pytest `
  tests\test_private_input_center_v058.py `
  tests\test_data_quality_summary_v064.py `
  tests\test_local_workbench_snapshot_review_v066.py `
  tests\test_net_worth_doctor_v062.py `
  tests\test_net_worth_integrity_guard_v065.py `
  tests\test_dashboard_v060.py `
  tests\test_security_boundaries.py `
  -q
```

Run full validation before committing or finalizing:

```powershell
$env:PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION='python'
python .\scripts\dev_validate.py
```

## Safety Boundaries

This stabilization pass must not run broker live reads, Webull token preflight,
Moomoo discovery, browser automation, bank/CPF/IRAS/HDB/SingPass workflows,
trading, cash movement, tax filing, scheduler jobs, or recommendation output.

It must not print or commit exact NAV, balances, positions, raw account IDs,
account numbers, private input contents, `.env.local` values, API keys, tokens,
or secrets.
