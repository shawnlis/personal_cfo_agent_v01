# Moomoo Read-Only Live-Read Setup

Personal CFO Agent v0.3.0 adds a supervised Moomoo / Futu OpenD read-only proof harness with redacted connection and data-path diagnostics. It remains off by default.

## Safety Boundary

- OpenD must be started manually by the operator.
- Live sync requires `--provider moomoo --allow-live-read`.
- Readiness checks do not connect to OpenD.
- Connection diagnostics are explicit and redacted; they do not send live read requests.
- Account discovery is explicit and redacted; it may connect to OpenD but only calls `get_acc_list()`.
- No order, preview, modify, cancel, submit, cash-transfer, or withdrawal methods are exposed on the provider object.
- No unlock flow is performed or added.
- First live read should be supervised.
- Generated outputs may contain sensitive financial information and must remain under ignored `reports/` paths.

## Environment Variables

Required for readiness or live sync:

- `CFO_MOOMOO_ENABLED=true`
- `CFO_MOOMOO_HOST`
- `CFO_MOOMOO_PORT`

Optional:

- `CFO_ACCOUNT_HASH_SALT`

Secrets must stay in environment variables only. Do not commit local config, account exports, logs with account data, or generated reports.

## Readiness Check

Run this before starting a live proof:

```powershell
python .\scripts\personal_cfo_agent.py --provider moomoo --readiness-check
```

This validates environment configuration only. It does not import `futu`, open a network connection, or write reports.

## Local SDK Dependency

Moomoo live-read proof requires the local Python package for Futu OpenD:

```powershell
python -m pip install futu-api
```

Do not commit virtualenv folders, user site-packages, SDK caches, account exports, or generated report outputs. Installing the SDK does not bypass the live-read gates: `.env.local` or OS environment configuration, manually started OpenD, explicit `--provider moomoo`, and explicit `--allow-live-read` are still required.

## Redacted Connection Diagnostics

Before a supervised live-read attempt, run:

```powershell
python .\scripts\personal_cfo_agent.py --provider moomoo --connection-diagnostics
```

Diagnostics report only redacted presence, Python executable, `futu` import status, OpenD socket reachability, and warning codes. They do not print host, port, salts, account identifiers, balances, or `.env.local` values.

## Redacted Account Discovery

OpenD socket reachability is necessary but not enough for acceptance. It only proves the local gateway is reachable; it does not prove that the adapter selected the correct `security_firm`, `filter_trdmarket`, universal account mode, trading environment, account status, or market authority.

Before any later funds, positions, or cash read, run the account-context discovery probe:

```powershell
python .\scripts\personal_cfo_agent.py --provider moomoo --account-discovery
```

This probe tests account context only. It loads local environment values without printing them, imports the `futu` SDK, checks OpenD socket reachability, suppresses SDK stdout/stderr, creates trade contexts only for account discovery, and calls `get_acc_list()` only.

It does not call `accinfo_query`, `position_list_query`, unlock APIs, order APIs, transfer or withdrawal APIs. It does not read balances, positions, cash, orders, or trading history. Output is a redacted JSON object containing only SDK/socket status, context-variant status, redacted account count, account ID hashes, account metadata enums, selected account hash, selected context mode, and warning codes.

Discovery may return `MOOMOO_ACCOUNT_DISCOVERY_OK`, `MOOMOO_NO_ACCOUNT_DISCOVERED`, `MOOMOO_SECURITY_FIRM_MISMATCH`, `MOOMOO_MARKET_FILTER_MISMATCH`, `MOOMOO_GENERAL_SEC_ACCOUNT_REQUIRED`, `MOOMOO_ACCOUNT_STATUS_NOT_ACTIVE`, `MOOMOO_TRDMARKET_AUTH_MISSING`, `MOOMOO_SELECTED_ACCOUNT_MISSING`, `MOOMOO_SDK_DISCOVERY_ARG_UNSUPPORTED`, `MOOMOO_SDK_OUTPUT_SUPPRESSED`, or `MOOMOO_READ_REQUIRES_MANUAL_UNLOCK_REVIEW`.

## Supervised Live Proof

After manually starting OpenD and completing redacted account discovery:

```powershell
python .\scripts\personal_cfo_agent.py `
  --provider moomoo `
  --allow-live-read `
  --moomoo-data-diagnostics `
  --out-dir .\reports\personal_cfo_agent\moomoo_v030_live_acceptance
```

The CLI prints:

```text
Read-only Moomoo sync only. No order methods are exposed.
```

If `futu` is not installed, the provider fails closed with `MOOMOO_SDK_NOT_INSTALLED` and `SDK_NOT_INSTALLED`. If OpenD is not reachable, it fails closed with `MOOMOO_OPEND_UNREACHABLE` or `PROVIDER_CONNECTION_FAILED`. If read requests fail, it reports `PROVIDER_FETCH_FAILED` with a Moomoo stage-specific code such as `MOOMOO_ACCOUNT_LIST_FAILED`, `MOOMOO_ACCOUNT_INFO_FAILED`, `MOOMOO_POSITION_LIST_FAILED`, or `MOOMOO_CASH_QUERY_FAILED`.

## Redacted Data-Path Diagnostics

The `--moomoo-data-diagnostics` mode still requires `--allow-live-read`. It reports only redacted data-path state:

- SDK import status
- OpenD socket reachability
- context open status
- account-list query attempted and success status
- account count redacted
- selected account hash, if an account context was safely selected
- account info query attempted and success status
- positions query attempted, success status, and position count
- cash or balance query attempted, success status, and cash currency count
- normalized rows count
- SDK output suppression status
- warning codes
- sanitized stage failures

It does not print raw account IDs, exact balances, host, port, salts, passwords, screenshots, cookies, or local environment values.

Zero-row outcomes are not accepted as a successful live proof unless the diagnostic state explains them safely. Account discovery by itself is not a successful live-read acceptance because it does not read balances, positions, cash, or normalized rows.

## Diagnostic Stage Table

| Stage | Success signal | Failure signal |
| --- | --- | --- |
| SDK import | `sdk_import_ok: true` | `MOOMOO_SDK_NOT_INSTALLED` |
| Socket reachability | `opend_socket_reachable: true` | `MOOMOO_OPEND_UNREACHABLE` |
| Context open | `context_opened: true` | `MOOMOO_CONTEXT_OPEN_FAILED` |
| Account list | `account_list_query_success: true` | `MOOMOO_ACCOUNT_LIST_FAILED` or `MOOMOO_ACCOUNT_LIST_EMPTY` |
| Account filter | selected account hash present or not configured | `MOOMOO_ACCOUNT_FILTER_MISMATCH` |
| Account info | `account_info_query_success: true` | `MOOMOO_ACCOUNT_INFO_FAILED` |
| Positions | `position_query_success: true` | `MOOMOO_POSITION_LIST_FAILED` or `MOOMOO_POSITION_LIST_EMPTY` |
| Cash/balance | `cash_query_success: true` | `MOOMOO_CASH_QUERY_FAILED` or `MOOMOO_CASH_EMPTY` |
| Normalization | `normalized_rows` greater than zero | `MOOMOO_NORMALIZATION_FAILED` or `MOOMOO_NO_DATA_RETURNED` |

## Current v0.3.0 Status

OpenD socket reachability and readiness passed in the continuation run, but the supervised live attempts failed during provider fetch before any report bundle was generated. Acceptance is not successful yet.

PR #11 remains draft. Account discovery is now required before any later supervised funds, positions, or cash read. The discovery command is only a context probe and does not enable trading capability.

The 2026-06-15 account-discovery run succeeded for context discovery only: SDK import OK, OpenD socket reachable, redacted account count `9`, selected account hash `acct_f63d870d837b3c3d`, selected context mode `filter_trdmarket=NONE;security_firm=FUTUSG;need_general_sec_acc=False`, and warning codes `MOOMOO_SDK_OUTPUT_SUPPRESSED`, `MOOMOO_SDK_DISCOVERY_ARG_UNSUPPORTED`, `MOOMOO_ACCOUNT_DISCOVERY_FAILED`, `MOOMOO_SECURITY_FIRM_MISMATCH`, `MOOMOO_MARKET_FILTER_MISMATCH`, `MOOMOO_ACCOUNT_DISCOVERY_OK`. It did not read balances, positions, cash, orders, or trading history.

Raw SDK console metadata must not be committed. The adapter suppresses SDK stdout and stderr around context creation, account list, account info, position, cash/balance, and context close calls; diagnostics retain only redacted status, counts, warning codes, and sanitized stage summaries.

## Troubleshooting

- Confirm OpenD is open and the operator is logged in.
- Confirm the correct market/account environment is available in OpenD.
- Confirm account permissions allow read-only account, cash, and position queries.
- If account-list diagnostics fail, review OpenD account visibility before another attempt.
- If account-info, position, or cash diagnostics fail, review OpenD permissions and SDK setup.
- If the SDK requires an unlock-like flow for additional access, do not add it silently. Record `MOOMOO_READ_REQUIRES_MANUAL_UNLOCK_REVIEW` and require explicit review before any future change.
- Do not copy raw SDK logs, account IDs, exact balances, screenshots, cookies, or `.env.local` values into docs, PRs, or commits.

## Output Contract

Successful live reads use the existing normalized asset ledger schema and provider sync summary. Raw account IDs are not written to outputs; `account_id_hash` is used instead.
