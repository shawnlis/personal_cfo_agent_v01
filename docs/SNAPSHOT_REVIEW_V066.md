# Snapshot Review v0.6.6

v0.6.6 adds a local-only snapshot review page for net worth refreshes.

The goal is to stop incorrect or partial refreshes from being treated as
confirmed net worth history. A refresh can still produce dashboard outputs for
review, but confirmed history should be written only after the integrity guard
and the user both approve it.

## Command

```powershell
python .\scripts\personal_cfo_agent.py `
  --snapshot-review `
  --refresh-dir .\reports\personal_cfo_agent\net_worth_refresh_local `
  --out-dir .\reports\personal_cfo_agent\net_worth_refresh_local\snapshot_review
```

`--run-net-worth-refresh` also writes this review folder automatically.

## Outputs

- `snapshot_review_summary.json`
- `SNAPSHOT_REVIEW_V066.md`
- `snapshot_review.html`

The files are redacted. They include provider gate status, account NAV row
counts, position row counts, FX completeness, blocking warning codes, and the
next safe action. They do not include exact NAV, balances, positions, account
IDs, account hashes, private input values, `.env.local` values, API keys,
tokens, or secrets.

## Confirmation Rule

Confirmed history is allowed only when:

- the integrity guard was generated
- `ready_to_confirm` is true
- no blocking warning codes are present

If the review page says the result is not ready, rerun the refresh after fixing
the missing layer, failed provider, stale date, or incomplete FX issue.

## Warning Codes

- `SNAPSHOT_REVIEW_READY_TO_CONFIRM`
- `SNAPSHOT_REVIEW_BLOCKED`

## Boundaries

Snapshot review is offline only. It must not run broker reads, Webull token
preflight, Moomoo discovery, account diagnostics, browser automation, external
uploads, trading, cash movement, tax filing, or recommendation output.
