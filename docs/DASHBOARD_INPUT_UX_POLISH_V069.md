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

The form remains static/local. It does not load external JavaScript, CSS, fonts,
or remote data. Direct saving still requires the explicit localhost save app:

```powershell
python .\scripts\personal_cfo_agent.py `
  --private-input-center-local-app `
  --input-file .\private_inputs\personal_cfo_input.local.json `
  --out-dir .\reports\personal_cfo_agent\private_input_center_local
```

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
- No generated reports or private inputs committed.
- No exact private values in committed tests or docs.
