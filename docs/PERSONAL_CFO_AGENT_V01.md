# Personal CFO Agent Project Note

This file is retained as a historical v0.1 project note. The active project is
now a v0.6.x local-first Personal CFO workflow. Use the root `README.md` for the
current operating guide.

## Current State

The current workflow supports:

- unified private input center for manual NAV, property, mortgage, CPF, SRS, tax,
  and HDB loan sections
- local net worth refresh
- account NAV merge
- snapshot history
- Dashboard v3 and Dashboard v4
- local net worth doctor
- supervised read-only broker refreshes only when explicitly approved

The project remains read-only-first and offline by default. Generated reports
stay under ignored `reports/` paths. Real local input files stay under ignored
private input folders.

## Current Commands

Initialize local private input:

```powershell
python .\scripts\personal_cfo_agent.py `
  --init-private-input-center `
  --out-file .\private_inputs\personal_cfo_input.local.json
```

Generate the local input form:

```powershell
python .\scripts\personal_cfo_agent.py `
  --private-input-center-form `
  --out-dir .\reports\personal_cfo_agent\private_input_center_local
```

Run manual-only refresh:

```powershell
python .\scripts\personal_cfo_agent.py `
  --run-net-worth-refresh `
  --refresh-brokers none `
  --input-file .\private_inputs\personal_cfo_input.local.json `
  --out-dir .\reports\personal_cfo_agent\net_worth_refresh_local
```

Generate Dashboard v4:

```powershell
python .\scripts\personal_cfo_agent.py `
  --dashboard-v4 `
  --refresh-dir .\reports\personal_cfo_agent\net_worth_refresh_local `
  --fx-rates-file .\private_inputs\fx_rates.local.json `
  --out-dir .\reports\personal_cfo_agent\dashboard_v4_local
```

Run the local doctor:

```powershell
python .\scripts\personal_cfo_agent.py `
  --net-worth-doctor `
  --input-file .\private_inputs\personal_cfo_input.local.json `
  --refresh-dir .\reports\personal_cfo_agent\net_worth_refresh_local `
  --fx-rates-file .\private_inputs\fx_rates.local.json `
  --out-dir .\reports\personal_cfo_agent\net_worth_doctor_v062_local
```

## Historical v0.1 Scope

The original v0.1 scope established the provider contract, manual snapshot
workflow, normalized asset ledger, and initial read-only boundaries. That scope
has been superseded by the v0.6.x local workflow described above.

## Boundaries

Do not commit generated reports, private inputs, credentials, exact private
values, raw account IDs, raw government identifiers, or `.env.local`.

Live broker reads require explicit approval and `--allow-live-read`. The default
workflow is offline and local-only.
