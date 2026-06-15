# Moomoo Read-Only Live-Read Setup

Personal CFO Agent v0.3.0 adds a supervised Moomoo / Futu OpenD read-only proof harness with redacted connection and data-path diagnostics. It remains off by default.

## Safety Boundary

- OpenD must be started manually by the operator.
- Live sync requires `--provider moomoo --allow-live-read`.
- Readiness checks do not connect to OpenD.
- Connection diagnostics are explicit and redacted; they do not send live read requests.
- Account discovery is explicit and redacted; it may connect to OpenD but only calls `get_acc_list()`.
- Read-context diagnostics are explicit and redacted; they run account discovery first and then test read-only account info and position queries with the discovered account hash context.
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

It does not call `accinfo_query`, `position_list_query`, unlock APIs, order APIs, transfer or withdrawal APIs. It does not read balances, positions, cash, orders, or trading history. Output is a redacted JSON object containing only SDK/socket status, discovery success status, context-variant status, redacted account count, account ID hashes, account metadata enums, selected account hash, selected context mode, terminal warning codes, variant warning codes, and warning codes.

Discovery may return `MOOMOO_ACCOUNT_DISCOVERY_OK`, `MOOMOO_NO_ACCOUNT_DISCOVERED`, `MOOMOO_SECURITY_FIRM_MISMATCH`, `MOOMOO_MARKET_FILTER_MISMATCH`, `MOOMOO_GENERAL_SEC_ACCOUNT_REQUIRED`, `MOOMOO_ACCOUNT_STATUS_NOT_ACTIVE`, `MOOMOO_TRDMARKET_AUTH_MISSING`, `MOOMOO_SELECTED_ACCOUNT_MISSING`, `MOOMOO_SELECTED_ACCOUNT_HASHED`, `MOOMOO_EXPLICIT_ACC_ID_SELECTED`, `MOOMOO_SDK_DISCOVERY_ARG_UNSUPPORTED`, `MOOMOO_SDK_OUTPUT_SUPPRESSED`, or `MOOMOO_READ_REQUIRES_MANUAL_UNLOCK_REVIEW`.

Failed context variants are non-terminal when discovery also returns `discovery_success: true`, `MOOMOO_ACCOUNT_DISCOVERY_OK`, and a selected account hash. In that case `MOOMOO_SECURITY_FIRM_MISMATCH` and `MOOMOO_MARKET_FILTER_MISMATCH` belong to `variant_warning_codes`, not terminal blockers.

## Supervised Live Proof

After manually starting OpenD and completing redacted account discovery, the supervised live proof runs account discovery first, probes a read context, then uses the selected read context for the read-only data calls:

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

If `futu` is not installed, the provider fails closed with `MOOMOO_SDK_NOT_INSTALLED` and `SDK_NOT_INSTALLED`. If OpenD is not reachable, it fails closed with `MOOMOO_OPEND_UNREACHABLE` or `PROVIDER_CONNECTION_FAILED`. If read requests fail, terminal warning codes now include stage-specific read failures such as `MOOMOO_ACCINFO_QUERY_FAILED`, `MOOMOO_POSITION_QUERY_FAILED`, `MOOMOO_READ_ONLY_FETCH_FAILED`, and `MOOMOO_NORMALIZED_ROWS_EMPTY`.

The supervised data fetch is limited to `get_acc_list`, `accinfo_query`, and `position_list_query`. It uses explicit selected `acc_id` internally when the installed SDK signature supports it, never prints or writes the raw account ID, and does not use `acc_index` unless a future fallback is unavoidable and reported with `MOOMOO_ACC_INDEX_FALLBACK_USED`.

## Redacted Read-Context Probe

Discovery can succeed with `filter_trdmarket=NONE` while later account info or position queries require a concrete market filter. The read-context probe tests installed-SDK-valid `HK`, `US`, `SG`, and `NONE` filters using the discovered `security_firm` and explicit selected account internally:

```powershell
python .\scripts\personal_cfo_agent.py --provider moomoo --read-context-probe
```

The probe runs account discovery first, then calls only `accinfo_query` and `position_list_query` for redacted context diagnostics. It does not perform unlock, order, history, transfer, or withdrawal operations. It prints only redacted success flags, selected account hash, selected discovery context mode, selected read context mode if found, position count, cash field count, normalized rows possible, terminal warning codes, variant warning codes, and forbidden-API status.

## Redacted Data-Path Diagnostics

The `--moomoo-data-diagnostics` mode still requires `--allow-live-read`. It reports only redacted data-path state:

- SDK import status
- OpenD socket reachability
- discovery success status
- selected context mode
- selected discovery context mode
- selected read context mode, if selected
- context open status
- account-list query attempted and success status
- account count redacted
- selected account hash, if an account context was safely selected
- account info query attempted and success status
- positions query attempted, success status, and position count
- cash or balance query attempted, success status, and cash currency count
- normalized rows count
- SDK output suppression status
- forbidden API called status
- terminal warning codes
- variant warning codes
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
| Read context | selected read context mode present | `MOOMOO_READ_CONTEXT_NOT_FOUND` or `MOOMOO_SELECTED_READ_CONTEXT_MISSING` |
| Account info | `account_info_query_success: true` | `MOOMOO_ACCOUNT_INFO_FAILED` or `MOOMOO_ACCINFO_QUERY_FAILED` |
| Positions | `position_query_success: true` | `MOOMOO_POSITION_LIST_FAILED`, `MOOMOO_POSITION_QUERY_FAILED`, or `MOOMOO_POSITION_LIST_EMPTY` |
| Cash/balance | `cash_query_success: true` | `MOOMOO_CASH_QUERY_FAILED`, `MOOMOO_CASH_EMPTY`, or `MOOMOO_CASH_NORMALIZATION_SHAPE_WARNING` |
| Normalization | `normalized_rows` greater than zero | `MOOMOO_NORMALIZATION_FAILED`, `MOOMOO_NORMALIZED_ROWS_EMPTY`, or `MOOMOO_NO_DATA_RETURNED` |

## Current v0.3.0 Status

OpenD socket reachability and readiness passed in the continuation run. The final supervised read-only attempt produced normalized rows and a local ignored report bundle. Acceptance is successful for the Moomoo read-only proof, while PR #11 remains draft until the user separately approves finalization.

PR #11 remains draft. Account discovery is now required before any later supervised funds, positions, or cash read. The discovery command is only a context probe and does not enable trading capability.

The 2026-06-15 account-discovery run succeeded for context discovery only: SDK import OK, OpenD socket reachable, redacted account count `9`, selected account hash `acct_f63d870d837b3c3d`, selected context mode `filter_trdmarket=NONE;security_firm=FUTUSG;need_general_sec_acc=False`, and `MOOMOO_ACCOUNT_DISCOVERY_OK`. Failed discovery variants are non-terminal once a selected account hash exists. That discovery run did not read balances, positions, cash, orders, or trading history.

The 2026-06-15 selected-context supervised read-only fetch was attempted exactly once after validation passed with 170 tests and 101 warnings. Discovery succeeded with redacted account count `9`, selected account hash `acct_f63d870d837b3c3d`, and selected discovery context mode `filter_trdmarket=NONE;security_firm=FUTUSG;need_general_sec_acc=False`. The fetch then attempted `accinfo_query` and `position_list_query`; both returned nonzero SDK ret codes. Position count was `0`, cash currency count was `0`, normalized rows were `0`, variant warnings remained non-terminal, and live-read acceptance success remains no.

That fetch previously reported empty terminal warning codes despite failed read stages. This is now fixed: if account info fails, terminal warnings include `MOOMOO_ACCINFO_QUERY_FAILED`; if positions fail, terminal warnings include `MOOMOO_POSITION_QUERY_FAILED`; if both fail and no rows normalize, terminal warnings include `MOOMOO_READ_ONLY_FETCH_FAILED` and `MOOMOO_NORMALIZED_ROWS_EMPTY`.

The next diagnostic step added a read-context probe that tests `HK`, `US`, `SG`, and `NONE` contexts with discovered `FUTUSG` and the explicit selected account internally.

The 2026-06-15 read-context probe was attempted exactly once after validation passed with 174 tests and 101 warnings. Discovery succeeded, SDK import was OK, OpenD socket was reachable, redacted account count was `9`, selected account hash was `acct_f63d870d837b3c3d`, and selected discovery context mode remained `filter_trdmarket=NONE;security_firm=FUTUSG;need_general_sec_acc=False`. The probe tested `HK`, `US`, `SG`, and `NONE` read contexts with `FUTUSG`; all tested contexts returned sanitized nonzero account info and position ret codes, position count was `0`, cash field count detected was `0`, normalized rows possible was `0`, and no selected read context was found.

Terminal warning codes from the read-context probe were `MOOMOO_ACCINFO_QUERY_FAILED`, `MOOMOO_POSITION_QUERY_FAILED`, `MOOMOO_READ_CONTEXT_NOT_FOUND`, `MOOMOO_SELECTED_READ_CONTEXT_MISSING`, `MOOMOO_READ_CONTEXT_PROBE_FAILED`, `MOOMOO_READ_ONLY_FETCH_FAILED`, and `MOOMOO_NORMALIZED_ROWS_EMPTY`. Variant warning codes remained discovery-matrix-only: `MOOMOO_SDK_DISCOVERY_ARG_UNSUPPORTED`, `MOOMOO_ACCOUNT_DISCOVERY_FAILED`, `MOOMOO_SECURITY_FIRM_MISMATCH`, `MOOMOO_MARKET_FILTER_MISMATCH`, and `MOOMOO_DISCOVERY_SUCCESS_WITH_VARIANT_WARNINGS`. Because no working read context was found, no supervised data fetch was run in this continuation.

No report bundle was generated, no reports were committed, no unlock was performed, no orders were requested, and no cash transfer was attempted.

The final 2026-06-15 supervised read-only attempt was run exactly once after validation passed with 175 tests and 101 warnings. Discovery succeeded, SDK import was OK, OpenD socket was reachable, redacted account count was `9`, selected account hash was `acct_f63d870d837b3c3d`, selected discovery context mode was `filter_trdmarket=NONE;security_firm=FUTUSG;need_general_sec_acc=False`, and selected read context mode was `filter_trdmarket=NONE;security_firm=FUTUSG;need_general_sec_acc=False`.

The final attempt used explicit selected account context internally and preserved the selected account ID only in memory for SDK calls. Account info query succeeded, position query succeeded, position count was `0`, cash currency count was `4`, normalized rows count was `5`, and the report bundle was written under ignored path `reports/personal_cfo_agent/moomoo_v030_live_acceptance`. Terminal warning codes were none. Variant warning codes remained discovery-matrix-only: `MOOMOO_SDK_DISCOVERY_ARG_UNSUPPORTED`, `MOOMOO_ACCOUNT_DISCOVERY_FAILED`, `MOOMOO_SECURITY_FIRM_MISMATCH`, `MOOMOO_MARKET_FILTER_MISMATCH`, and `MOOMOO_DISCOVERY_SUCCESS_WITH_VARIANT_WARNINGS`.

The final warning/status codes were `MOOMOO_SDK_OUTPUT_SUPPRESSED`, `MOOMOO_ACCOUNT_DISCOVERY_OK`, `MOOMOO_SELECTED_ACCOUNT_HASHED`, `MOOMOO_EXPLICIT_ACC_ID_SELECTED`, `MOOMOO_SDK_DISCOVERY_ARG_UNSUPPORTED`, `MOOMOO_ACCOUNT_DISCOVERY_FAILED`, `MOOMOO_SECURITY_FIRM_MISMATCH`, `MOOMOO_MARKET_FILTER_MISMATCH`, `MOOMOO_DISCOVERY_SUCCESS_WITH_VARIANT_WARNINGS`, `MOOMOO_READ_CONTEXT_PROBE_OK`, `MOOMOO_READ_ONLY_FETCH_OK`, `MOOMOO_ACCINFO_QUERY_OK`, `MOOMOO_POSITION_QUERY_OK`, `MOOMOO_POSITION_DATA_EMPTY`, `MOOMOO_POSITION_LIST_EMPTY`, and `MOOMOO_POSITIONS_EMPTY`.

No raw account IDs, card numbers, universal card numbers, exact balances, raw positions, `.env.local` values, screenshots, cookies, or raw SDK output were added to committed docs. No unlock was performed, no orders were requested, no cash transfer or withdrawal was attempted, and generated reports remain ignored and uncommitted.

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
