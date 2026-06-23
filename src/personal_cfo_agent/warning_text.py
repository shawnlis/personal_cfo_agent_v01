"""Human-readable warning text for local Personal CFO reports."""

from __future__ import annotations

from personal_cfo_agent.models import WarningCode


_WARNING_DESCRIPTIONS: dict[str, str] = {
    WarningCode.NET_WORTH_REFRESH_LIVE_READ_SKIPPED.value: (
        "Broker refresh was skipped. The output uses manual/local inputs only."
    ),
    WarningCode.NET_WORTH_REFRESH_BROKER_READ_FAILED.value: (
        "At least one requested broker refresh did not produce usable rows."
    ),
    WarningCode.NET_WORTH_REFRESH_SNAPSHOT_PENDING_REVIEW.value: (
        "The snapshot was generated for review only and was not appended to confirmed history."
    ),
    WarningCode.NET_WORTH_REFRESH_SNAPSHOT_HISTORY_CONFIRMED.value: (
        "The snapshot passed the confirmation gate and was written to confirmed history."
    ),
    WarningCode.DATA_QUALITY_BROKER_FAILURES.value: (
        "One or more requested live broker layers failed or returned no usable data."
    ),
    WarningCode.DATA_QUALITY_REFRESH_INCOMPLETE.value: (
        "A required refresh stage did not generate its expected output."
    ),
    WarningCode.DATA_QUALITY_FX_INCOMPLETE.value: (
        "Explicit FX coverage is missing or incomplete for cross-currency aggregation."
    ),
    WarningCode.DATA_QUALITY_STALE_OR_MIXED_DATES.value: (
        "Some source dates are stale or not aligned and should be reviewed before confirmation."
    ),
    WarningCode.DATA_QUALITY_EXPECTED_SOURCE_MISSING.value: (
        "A source marked required by the local expected-source contract is missing."
    ),
    WarningCode.EXPECTED_SOURCE_CONTRACT_INVALID.value: (
        "The expected-source contract has an invalid shape and was ignored."
    ),
    WarningCode.EXPECTED_SOURCE_REQUIRED_MISSING.value: (
        "A required expected source is unavailable in the refresh output."
    ),
    WarningCode.INTEGRITY_GUARD_OK.value: (
        "The integrity guard found no blocking issue for confirmed history write."
    ),
    WarningCode.INTEGRITY_GUARD_BLOCKED.value: (
        "The integrity guard blocked confirmed history write."
    ),
    WarningCode.INTEGRITY_EXPECTED_SOURCE_MISSING.value: (
        "A required expected source is missing, so confirmed history write is blocked."
    ),
    WarningCode.INTEGRITY_BROKER_REQUESTED_MISSING.value: (
        "A requested broker has no account NAV rows in the refresh output."
    ),
    WarningCode.INTEGRITY_PROVIDER_NAV_MISSING.value: (
        "A requested broker has rows, but no provider-reported account NAV marker."
    ),
    WarningCode.INTEGRITY_TOTAL_NAV_UNAVAILABLE.value: (
        "The current total net worth could not be computed safely."
    ),
    WarningCode.INTEGRITY_MIXED_CURRENCY_BLOCKED.value: (
        "Mixed-currency NAV was detected without complete explicit FX coverage."
    ),
    WarningCode.INTEGRITY_FX_REQUIRED.value: (
        "Explicit FX rates are required before this refresh can be confirmed."
    ),
    WarningCode.INTEGRITY_MIXED_AS_OF_DATES.value: (
        "Source dates are mixed and require review before writing confirmed history."
    ),
    WarningCode.INTEGRITY_STALE_PROVIDER_DATA.value: (
        "At least one provider source appears stale."
    ),
    WarningCode.INTEGRITY_SNAPSHOT_PENDING_REVIEW.value: (
        "The snapshot is pending manual review."
    ),
    WarningCode.INTEGRITY_CONFIRMED_HISTORY_MISSING.value: (
        "No previous confirmed history was available for change comparison."
    ),
    WarningCode.INTEGRITY_NAV_CHANGE_REVIEW_REQUIRED.value: (
        "The net worth change versus confirmed history is large enough to require review."
    ),
    WarningCode.SNAPSHOT_HISTORY_MANAGER_INPUT_MISSING.value: (
        "The snapshot history manager could not find the required history files."
    ),
    WarningCode.SNAPSHOT_HISTORY_MANAGER_NO_HISTORY_ROWS.value: (
        "No snapshot history rows were available to manage."
    ),
    WarningCode.SNAPSHOT_HISTORY_MANAGER_KEEP_SET_EMPTY.value: (
        "The selected keep criteria matched no snapshot history rows."
    ),
    WarningCode.SNAPSHOT_HISTORY_MANAGER_DRY_RUN.value: (
        "Snapshot history manager ran in dry-run mode and did not rewrite history."
    ),
    WarningCode.SNAPSHOT_HISTORY_MANAGER_BACKUP_CREATED.value: (
        "A local backup was created before snapshot history files were rewritten."
    ),
    WarningCode.SNAPSHOT_HISTORY_MANAGER_APPLIED.value: (
        "Snapshot history manager rewrote local history files using the selected keep set."
    ),
    WarningCode.SNAPSHOT_HISTORY_MANAGER_GENERATED_OK.value: (
        "Snapshot history manager completed without warnings."
    ),
    WarningCode.SNAPSHOT_HISTORY_MANAGER_GENERATED_WITH_WARNINGS.value: (
        "Snapshot history manager completed with warnings that require review."
    ),
    WarningCode.SNAPSHOT_REVIEW_READY_TO_CONFIRM.value: (
        "The redacted snapshot review says the refresh is ready for confirmed history write."
    ),
    WarningCode.SNAPSHOT_REVIEW_BLOCKED.value: (
        "The redacted snapshot review says confirmed history write should remain blocked."
    ),
    WarningCode.LOCAL_WORKBENCH_INPUT_MISSING.value: (
        "The local workbench could not find the configured private input file."
    ),
    WarningCode.LOCAL_WORKBENCH_REFRESH_MISSING.value: (
        "The local workbench could not find the configured refresh directory."
    ),
    WarningCode.LOCAL_WORKBENCH_FX_MISSING.value: (
        "The local workbench could not find the configured FX rates file."
    ),
    WarningCode.LOCAL_WORKBENCH_GENERATED_OK.value: (
        "The local workbench was generated without missing-path warnings."
    ),
    WarningCode.LOCAL_WORKBENCH_GENERATED_WITH_WARNINGS.value: (
        "The local workbench was generated and lists missing local paths to review."
    ),
    WarningCode.DASHBOARD_V4_FX_RATES_MISSING.value: (
        "Dashboard v4 skipped FX conversion because no explicit FX file was provided."
    ),
    WarningCode.DASHBOARD_V4_FX_CONVERSION_SKIPPED.value: (
        "Dashboard v4 skipped a currency conversion instead of making a silent FX assumption."
    ),
    WarningCode.DASHBOARD_V4_BUCKET_HISTORY_LIMITED.value: (
        "Bucket history is limited because there are too few confirmed history rows."
    ),
    WarningCode.DASHBOARD_V4_FIRE_TARGET_FX_MISSING.value: (
        "FIRE target conversion needs explicit FX before the USD scenario can use local currency values."
    ),
    WarningCode.PRIVATE_INPUT_CENTER_VALIDATION_FAILED.value: (
        "The unified private input file failed validation."
    ),
    WarningCode.PRIVATE_INPUT_CENTER_VALIDATION_WITH_WARNINGS.value: (
        "The unified private input file is usable but has review warnings."
    ),
    WarningCode.PRIVATE_INPUT_CENTER_REQUIRED_FIELD_MISSING.value: (
        "A required private input field is missing."
    ),
    WarningCode.PRIVATE_INPUT_CENTER_RAW_IDENTIFIER_DETECTED.value: (
        "A raw identifier-like field was detected and must be removed or hashed."
    ),
    WarningCode.NET_WORTH_DOCTOR_INPUT_MISSING.value: (
        "The doctor could not find the unified private input file."
    ),
    WarningCode.NET_WORTH_DOCTOR_INPUT_INVALID.value: (
        "The unified private input file is present but invalid."
    ),
    WarningCode.NET_WORTH_DOCTOR_REFRESH_MISSING.value: (
        "The doctor could not find the refresh directory."
    ),
    WarningCode.NET_WORTH_DOCTOR_REFRESH_INCOMPLETE.value: (
        "The refresh directory exists but is missing required files."
    ),
    WarningCode.NET_WORTH_DOCTOR_FX_MISSING.value: (
        "The doctor could not find an explicit FX rates file."
    ),
    WarningCode.NET_WORTH_DOCTOR_FX_INCOMPLETE.value: (
        "The explicit FX file does not cover all required currencies."
    ),
    WarningCode.NET_WORTH_DOCTOR_BROKER_CONFIG_MISSING.value: (
        "A broker is enabled but required redacted config presence is incomplete."
    ),
}


def warning_description(code: WarningCode | str) -> str:
    """Return a concise non-private explanation for a warning code."""

    text = code.value if isinstance(code, WarningCode) else str(code)
    if text in _WARNING_DESCRIPTIONS:
        return _WARNING_DESCRIPTIONS[text]
    return text.replace("_", " ").capitalize() + "."


def warning_details(codes: list[WarningCode] | list[str]) -> list[dict[str, str]]:
    """Return structured warning code explanations."""

    return [
        {"code": code.value if isinstance(code, WarningCode) else str(code), "description": warning_description(code)}
        for code in codes
    ]


def warning_lines(codes: list[WarningCode] | list[str]) -> list[str]:
    """Return Markdown bullet lines with code and explanation."""

    if not codes:
        return ["- None"]
    return [
        f"- `{detail['code']}`: {detail['description']}"
        for detail in warning_details(codes)
    ]
