# CPF And SGFinDex Manual Workflow

CPF, IRAS, and HDB values are manual-only in Personal CFO Agent v0.1.4.

## Allowed Workflow

1. Use official apps or websites yourself.
2. If desired, use SGFinDex manually through official apps.
3. Enter summarized values into the manual snapshot JSON.
4. Validate the JSON before running aggregation.

## Blocked Workflow

- Do not automate SingPass.
- Do not scrape CPF / IRAS / HDB.
- Do not automate identity login.
- Do not store passwords, cookies, private keys, or screenshots.
- Do not commit manual snapshots or generated reports.

## Source Labels

Use `valuation_source` values such as:

- `manual official app summary`
- `manual SGFinDex-derived summary`
- `manual statement summary`

Do not use source labels such as scraped, automated, unofficial API, or screen capture. The validator rejects automated-source markers for CPF, IRAS, and HDB rows.
