"""Redacted data quality reporting for local net worth refreshes."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from personal_cfo_agent.models import WarningCode
from personal_cfo_agent.warning_text import warning_details, warning_lines


SCHEMA_VERSION = "v0.6.4"

SUMMARY_NAME = "data_quality_summary.json"
WARNINGS_NAME = "data_quality_warnings.md"
REPORT_NAME = "DATA_QUALITY_SUMMARY_V064.md"


@dataclass(frozen=True)
class DataQualitySummaryResult:
    output_dir: Path
    output_paths: dict[str, Path] = field(default_factory=dict)
    warning_codes: list[WarningCode] = field(default_factory=list)
    generated: bool = False


def write_data_quality_summary(
    *,
    out_dir: Path,
    providers_requested: list[str],
    providers_succeeded: list[str],
    providers_failed: list[str],
    expected_required_providers: list[str] | None = None,
    expected_optional_providers: list[str] | None = None,
    expected_required_manual_layers: list[str] | None = None,
    expected_optional_manual_layers: list[str] | None = None,
    manual_layer_status: dict[str, bool],
    account_nav_row_count: int,
    position_row_count: int,
    snapshot_generated: bool,
    fx_file_present: bool,
    fx_complete: bool,
    stale_or_mixed_date_warning_codes: list[str],
    dashboard_generated: bool,
    upstream_warning_codes: list[WarningCode],
    integrity_guard_generated: bool = False,
    integrity_ready_to_confirm: bool = False,
    integrity_blocking_warning_codes: list[str] | None = None,
) -> DataQualitySummaryResult:
    """Write refresh data-quality outputs without private values."""

    required_providers = _clean_list(expected_required_providers or [])
    optional_providers = _clean_list(expected_optional_providers or [])
    required_manual_layers = _clean_list(expected_required_manual_layers or [])
    optional_manual_layers = _clean_list(expected_optional_manual_layers or [])
    expected_required_missing = _expected_required_missing(
        required_providers=required_providers,
        providers_succeeded=providers_succeeded,
        required_manual_layers=required_manual_layers,
        manual_layer_status=manual_layer_status,
    )
    warnings = _data_quality_warning_codes(
        providers_failed=providers_failed,
        snapshot_generated=snapshot_generated,
        dashboard_generated=dashboard_generated,
        fx_file_present=fx_file_present,
        fx_complete=fx_complete,
        stale_or_mixed_date_warning_codes=stale_or_mixed_date_warning_codes,
        expected_required_missing=expected_required_missing,
    )
    completion = (
        WarningCode.DATA_QUALITY_GENERATED_WITH_WARNINGS
        if warnings
        else WarningCode.DATA_QUALITY_GENERATED_OK
    )
    warnings = _dedupe_warning_codes([*warnings, completion])

    out_dir.mkdir(parents=True, exist_ok=True)
    output_paths = {
        "summary": out_dir / SUMMARY_NAME,
        "warnings": out_dir / WARNINGS_NAME,
        "report": out_dir / REPORT_NAME,
    }
    summary: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "redacted": True,
        "providers": {
            "requested": sorted(providers_requested),
            "succeeded": sorted(providers_succeeded),
            "failed": sorted(providers_failed),
        },
        "expected_sources": {
            "providers_required": required_providers,
            "providers_optional": optional_providers,
            "manual_layers_required": required_manual_layers,
            "manual_layers_optional": optional_manual_layers,
        },
        "provider_gate": _provider_gate_rows(
            providers_requested=providers_requested,
            providers_succeeded=providers_succeeded,
            providers_failed=providers_failed,
            expected_required_providers=required_providers,
            expected_optional_providers=optional_providers,
        ),
        "manual_layers": {
            key: bool(value) for key, value in sorted(manual_layer_status.items())
        },
        "source_provenance": _source_provenance_rows(
            providers_requested=providers_requested,
            providers_succeeded=providers_succeeded,
            providers_failed=providers_failed,
            expected_required_providers=required_providers,
            expected_optional_providers=optional_providers,
            manual_layer_status=manual_layer_status,
            expected_required_manual_layers=required_manual_layers,
            expected_optional_manual_layers=optional_manual_layers,
            snapshot_generated=snapshot_generated,
            fx_file_present=fx_file_present,
            fx_complete=fx_complete,
            dashboard_generated=dashboard_generated,
            integrity_guard_generated=integrity_guard_generated,
        ),
        "counts": {
            "account_nav_row_count": max(0, int(account_nav_row_count)),
            "position_row_count": max(0, int(position_row_count)),
        },
        "snapshot": {
            "generated": bool(snapshot_generated),
        },
        "fx": {
            "file_present": bool(fx_file_present),
            "complete": bool(fx_complete),
        },
        "dates": {
            "stale_or_mixed_date_warning_codes": sorted(stale_or_mixed_date_warning_codes),
        },
        "dashboard": {
            "generated": bool(dashboard_generated),
        },
        "integrity_guard": {
            "generated": bool(integrity_guard_generated),
            "ready_to_confirm": bool(integrity_ready_to_confirm),
            "blocking_warning_codes": sorted(integrity_blocking_warning_codes or []),
        },
        "source_warning_codes": [code.value for code in upstream_warning_codes],
        "warning_codes": [code.value for code in warnings],
        "warning_details": warning_details(warnings),
    }
    output_paths["summary"].write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    _write_warnings(output_paths["warnings"], warnings)
    output_paths["report"].write_text(_report(summary), encoding="utf-8")

    return DataQualitySummaryResult(
        output_dir=out_dir,
        output_paths=output_paths,
        warning_codes=warnings,
        generated=True,
    )


def _data_quality_warning_codes(
    *,
    providers_failed: list[str],
    snapshot_generated: bool,
    dashboard_generated: bool,
    fx_file_present: bool,
    fx_complete: bool,
    stale_or_mixed_date_warning_codes: list[str],
    expected_required_missing: bool,
) -> list[WarningCode]:
    warnings: list[WarningCode] = []
    if providers_failed:
        warnings.append(WarningCode.DATA_QUALITY_BROKER_FAILURES)
    if expected_required_missing:
        warnings.append(WarningCode.DATA_QUALITY_EXPECTED_SOURCE_MISSING)
    if not snapshot_generated or not dashboard_generated:
        warnings.append(WarningCode.DATA_QUALITY_REFRESH_INCOMPLETE)
    if not fx_file_present or not fx_complete:
        warnings.append(WarningCode.DATA_QUALITY_FX_INCOMPLETE)
    if stale_or_mixed_date_warning_codes:
        warnings.append(WarningCode.DATA_QUALITY_STALE_OR_MIXED_DATES)
    return warnings


def _write_warnings(path: Path, warnings: list[WarningCode]) -> None:
    lines = ["# Data Quality Warnings", ""]
    lines.extend(warning_lines(warnings))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _report(summary: dict[str, Any]) -> str:
    providers = summary["providers"]
    expected_sources = summary.get("expected_sources", {})
    layers = summary["manual_layers"]
    counts = summary["counts"]
    warnings = summary["warning_codes"]
    integrity = summary.get("integrity_guard", {})
    provider_gate = summary.get("provider_gate", [])
    source_provenance = summary.get("source_provenance", [])
    lines = [
        "# Data Quality Summary v0.6.4",
        "",
        "Redacted refresh quality report. It records statuses and row counts only.",
        "",
        "## Providers",
        "",
        f"- Requested: {', '.join(providers['requested']) or 'None'}",
        f"- Succeeded: {', '.join(providers['succeeded']) or 'None'}",
        f"- Failed: {', '.join(providers['failed']) or 'None'}",
        "",
        "## Expected Sources",
        "",
        (
            "- Required providers: "
            + (
                ", ".join(expected_sources.get("providers_required", []))
                if expected_sources.get("providers_required")
                else "None"
            )
        ),
        (
            "- Required manual layers: "
            + (
                ", ".join(expected_sources.get("manual_layers_required", []))
                if expected_sources.get("manual_layers_required")
                else "None"
            )
        ),
        "",
        "## Provider Gate",
        "",
        *(_provider_gate_lines(provider_gate)),
        "",
        "## Manual Layers",
        "",
        *[f"- {name}: {_yes_no(value)}" for name, value in sorted(layers.items())],
        "",
        "## Source Provenance",
        "",
        *(_source_provenance_lines(source_provenance)),
        "",
        "## Counts",
        "",
        f"- Account NAV rows: {counts['account_nav_row_count']}",
        f"- Position rows: {counts['position_row_count']}",
        "",
        "## Snapshot And Dashboard",
        "",
        f"- Snapshot generated: {_yes_no(summary['snapshot']['generated'])}",
        f"- Dashboard generated: {_yes_no(summary['dashboard']['generated'])}",
        "",
        "## Integrity Guard",
        "",
        f"- Guard generated: {_yes_no(bool(integrity.get('generated')))}",
        f"- Ready to confirm history: {_yes_no(bool(integrity.get('ready_to_confirm')))}",
        (
            "- Blocking warning codes: "
            + (
                ", ".join(integrity.get("blocking_warning_codes", []))
                if integrity.get("blocking_warning_codes")
                else "None"
            )
        ),
        "",
        "## FX",
        "",
        f"- FX file present: {_yes_no(summary['fx']['file_present'])}",
        f"- FX complete: {_yes_no(summary['fx']['complete'])}",
        "",
        "## Warning Codes",
        "",
        *warning_lines(warnings),
    ]
    return "\n".join(lines) + "\n"


def _provider_gate_rows(
    *,
    providers_requested: list[str],
    providers_succeeded: list[str],
    providers_failed: list[str],
    expected_required_providers: list[str],
    expected_optional_providers: list[str],
) -> list[dict[str, bool | str]]:
    providers = sorted(
        {
            *[provider for provider in providers_requested if provider],
            *[provider for provider in providers_succeeded if provider],
            *[provider for provider in providers_failed if provider],
            *[provider for provider in expected_required_providers if provider],
            *[provider for provider in expected_optional_providers if provider],
        }
    )
    requested = set(providers_requested)
    succeeded = set(providers_succeeded)
    failed = set(providers_failed)
    expected_required = set(expected_required_providers)
    expected_optional = set(expected_optional_providers)
    rows: list[dict[str, bool | str]] = []
    for provider in providers:
        status = "not_requested"
        if provider in succeeded:
            status = "ok"
        elif provider in failed and provider in expected_required:
            status = "failed_required"
        elif provider in failed:
            status = "failed"
        elif provider in expected_required:
            status = "missing_required"
        elif provider in requested:
            status = "missing"
        elif provider in expected_optional:
            status = "optional_missing"
        rows.append(
            {
                "provider": provider,
                "requested": provider in requested,
                "succeeded": provider in succeeded,
                "failed": provider in failed,
                "expected_required": provider in expected_required,
                "expected_optional": provider in expected_optional,
                "status": status,
            }
        )
    return rows


def _provider_gate_lines(provider_gate: object) -> list[str]:
    if not isinstance(provider_gate, list) or not provider_gate:
        return ["- None"]
    lines: list[str] = []
    for row in provider_gate:
        if not isinstance(row, dict):
            continue
        lines.append(
            f"- {row.get('provider', 'unknown')}: "
            f"requested={_yes_no(bool(row.get('requested')))}; "
            f"succeeded={_yes_no(bool(row.get('succeeded')))}; "
            f"failed={_yes_no(bool(row.get('failed')))}; "
            f"expected_required={_yes_no(bool(row.get('expected_required')))}; "
            f"status={row.get('status', 'unknown')}"
        )
    return lines or ["- None"]


def _source_provenance_rows(
    *,
    providers_requested: list[str],
    providers_succeeded: list[str],
    providers_failed: list[str],
    expected_required_providers: list[str],
    expected_optional_providers: list[str],
    manual_layer_status: dict[str, bool],
    expected_required_manual_layers: list[str],
    expected_optional_manual_layers: list[str],
    snapshot_generated: bool,
    fx_file_present: bool,
    fx_complete: bool,
    dashboard_generated: bool,
    integrity_guard_generated: bool,
) -> list[dict[str, bool | str]]:
    rows: list[dict[str, bool | str]] = []
    expected_manual = {
        **{layer: "required" for layer in expected_required_manual_layers},
        **{
            layer: "optional"
            for layer in expected_optional_manual_layers
            if layer not in expected_required_manual_layers
        },
    }
    for layer_name, available in sorted(manual_layer_status.items()):
        requirement = expected_manual.get(layer_name, "none")
        status = "available" if available else "missing_required" if requirement == "required" else "missing"
        rows.append(
            {
                "layer": layer_name,
                "source_type": "local_manual_private_input",
                "available": bool(available),
                "status": status,
                "expected_requirement": requirement,
                "confirmed_history_source": False,
            }
        )
    expected_providers = {
        **{provider: "required" for provider in expected_required_providers},
        **{
            provider: "optional"
            for provider in expected_optional_providers
            if provider not in expected_required_providers
        },
    }
    for provider in sorted(
        {
            *[item for item in providers_requested if item],
            *[item for item in providers_succeeded if item],
            *[item for item in providers_failed if item],
            *[item for item in expected_required_providers if item],
            *[item for item in expected_optional_providers if item],
        }
    ):
        succeeded = provider in providers_succeeded
        failed = provider in providers_failed
        requirement = expected_providers.get(provider, "none")
        status = (
            "available"
            if succeeded
            else "failed"
            if failed
            else "missing_required"
            if requirement == "required"
            else "missing"
        )
        rows.append(
            {
                "layer": f"broker_provider_{provider}",
                "source_type": "supervised_read_only_provider_bundle",
                "available": succeeded,
                "status": status,
                "expected_requirement": requirement,
                "confirmed_history_source": False,
            }
        )
    rows.extend(
        [
            {
                "layer": "pending_snapshot",
                "source_type": "derived_pending_review_snapshot",
                "available": bool(snapshot_generated),
                "status": "available" if snapshot_generated else "missing",
                "confirmed_history_source": False,
            },
            {
                "layer": "explicit_fx",
                "source_type": "local_explicit_fx_rates",
                "available": bool(fx_file_present and fx_complete),
                "status": "available" if fx_file_present and fx_complete else "incomplete",
                "confirmed_history_source": False,
            },
            {
                "layer": "dashboard",
                "source_type": "derived_local_dashboard",
                "available": bool(dashboard_generated),
                "status": "available" if dashboard_generated else "missing",
                "confirmed_history_source": False,
            },
            {
                "layer": "integrity_guard",
                "source_type": "offline_confirmation_gate",
                "available": bool(integrity_guard_generated),
                "status": "available" if integrity_guard_generated else "missing",
                "confirmed_history_source": False,
            },
        ]
    )
    return rows


def _source_provenance_lines(source_provenance: object) -> list[str]:
    if not isinstance(source_provenance, list) or not source_provenance:
        return ["- None"]
    lines: list[str] = []
    for row in source_provenance:
        if not isinstance(row, dict):
            continue
        lines.append(
            f"- {row.get('layer', 'unknown')}: "
            f"source_type={row.get('source_type', 'unknown')}; "
            f"available={_yes_no(bool(row.get('available')))}; "
            f"status={row.get('status', 'unknown')}"
        )
    return lines or ["- None"]


def _yes_no(value: bool) -> str:
    return "yes" if value else "no"


def _clean_list(values: list[str]) -> list[str]:
    return sorted({str(value).strip().lower() for value in values if str(value).strip()})


def _expected_required_missing(
    *,
    required_providers: list[str],
    providers_succeeded: list[str],
    required_manual_layers: list[str],
    manual_layer_status: dict[str, bool],
) -> bool:
    succeeded = {provider.strip().lower() for provider in providers_succeeded if provider}
    if any(provider not in succeeded for provider in required_providers):
        return True
    return any(not manual_layer_status.get(layer, False) for layer in required_manual_layers)


def _dedupe_warning_codes(codes: list[WarningCode]) -> list[WarningCode]:
    seen: set[WarningCode] = set()
    result: list[WarningCode] = []
    for code in codes:
        if code in seen:
            continue
        seen.add(code)
        result.append(code)
    return result
