# Dashboard and Input UX Polish v0.6.9

v0.6.9 is a small local UX polish pass over the existing unified private input
center and Dashboard v4.

It does not change broker connectors, source semantics, snapshot history rules,
FX rules, or confirmed-history gates.

## Input Center Polish

The unified private input center remains the only user-facing manual input form.

The form keeps one primary save action:

```text
Save to local JSON
```

The JSON textarea is now an advanced preview panel rather than a large always-on
field. This keeps day-to-day editing focused on the values that matter while
preserving a local preview for debugging.

The old visible `Expected Sources` checkbox section is removed from the main
form. The form now writes a complete-refresh expected source contract by
default:

- IBKR live NAV required
- Moomoo live NAV required
- Tiger live NAV required
- manual NAV required
- property/mortgage required
- Singapore manual layers required

The contract remains in the generated JSON because it is the quality gate that
prevents partial provider reads from being confirmed into long-term history.

The form remains static/local. It does not load external JavaScript, CSS, fonts,
or remote data. Direct saving still requires the explicit localhost save app:

```powershell
python .\scripts\personal_cfo_agent.py `
  --private-input-center-local-app `
  --input-file .\private_inputs\personal_cfo_input.local.json `
  --out-dir .\reports\personal_cfo_agent\private_input_center_local
```

In local-app mode, the form can also fetch public reference FX rates into the
FX fields. The static `file://` form still performs no external requests. Public
FX fetch is triggered only by the local app endpoint or this explicit command:

```powershell
python .\scripts\personal_cfo_agent.py `
  --fetch-fx-rates `
  --base-currency SGD `
  --fx-currencies USD,CNY,HKD `
  --out-file .\private_inputs\fx_rates.local.json
```

The FX command writes the local explicit-FX JSON schema and does not print the
rate values.

## Dashboard v4 Polish

Dashboard v4 now surfaces core totals in the CFO cockpit:

- total assets
- liquid investment assets

The detailed asset bucket section remains below the cockpit for review.

## Boundaries

- No broker/API connections.
- No Webull token preflight.
- No Moomoo discovery.
- No browser automation.
- No live reads.
- Public FX fetch is explicit and does not use credentials or account data.
- No generated reports or private inputs committed.
- No exact private values in committed tests or docs.
