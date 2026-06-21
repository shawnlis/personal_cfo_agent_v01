"""Local-only net worth refresh health checks."""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from personal_cfo_agent.config import (
    ProviderConfig,
    load_ibkr_config,
    load_moomoo_config,
    load_tiger_config,
    load_webull_config,
)
from personal_cfo_agent.models import WarningCode
from personal_cfo_agent.private_input_center import validate_private_input_center


SCHEMA_VERSION = "v0.6.2"

SUMMARY_NAME = "net_worth_doctor_summary.json"
WARNINGS_NAME = "net_worth_doctor_warnings.md"
REPORT_NAME = "NET_WORTH_DOCTOR_V062.md"


@dataclass(frozen=True)
class NetWorthDoctorResult:
    input_file: Path
    refresh_dir: Path
    fx_rates_file: Path | None
    output_dir: Path
    output_paths: dict[str, Path] = field(default_factory=dict)
    generated: bool = False
    input_valid: bool = False
    refresh_present: bool = False
    refresh_complete: bool = False
    fx_present: bool = False
    fx_complete: bool = False
    broker_config_presence: dict[str, dict[str, bool]] = field(default_factory=dict)
    warning_codes: list[WarningCode] = field(default_factory=list)


def run_net_worth_doctor(
    *,
    input_file: Path,
    refresh_dir: Path,
    fx_rates_file: Path | None,
    out_dir: Path,
    env: Mapping[str, str],
) -> NetWorthDoctorResult:
    """Inspect local Personal CFO inputs and outputs without live connections."""

    warnings: list[WarningCode] = []
    input_summary = _input_summary(input_file, warnings)
    refresh_summary = _refresh_summary(refresh_dir, warnings)
    fx_summary = _fx_summary(
        fx_rates_file,
        required_currencies=_required_fx_currencies(refresh_dir),
        warnings=warnings,
    )
    broker_summary = _broker_config_summary(env, warnings)
    warnings = _dedupe_warning_codes(warnings)
    completion = (
        WarningCode.NET_WORTH_DOCTOR_GENERATED_WITH_WARNINGS
        if warnings
        else WarningCode.NET_WORTH_DOCTOR_GENERATED_OK
    )
    warnings = _dedupe_warning_codes([*warnings, completion])

    out_dir.mkdir(parents=True, exist_ok=True)
    output_paths = {
        "summary": out_dir / SUMMARY_NAME,
        "warnings": out_dir / WARNINGS_NAME,
        "report": out_dir / REPORT_NAME,
    }
    summary = {
        "schema_version": SCHEMA_VERSION,
        "external_connections_used": False,
        "broker_live_reads_used": False,
        "input_file": str(input_file),
        "refresh_dir": str(refresh_dir),
        "fx_rates_file": str(fx_rates_file or ""),
        "input": input_summary,
        "refresh": refresh_summary,
        "fx": fx_summary,
        "broker_config_presence": broker_summary,
        "warning_codes": [code.value for code in warnings],
    }
    output_paths["summary"].write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    _write_warnings(output_paths["warnings"], warnings)
    output_paths["report"].write_text(_report(summary), encoding="utf-8")

    return NetWorthDoctorResult(
        input_file=input_file,
        refresh_dir=refresh_dir,
        fx_rates_file=fx_rates_file,
        output_dir=out_dir,
        output_paths=output_paths,
        generated=True,
        input_valid=bool(input_summary["valid"]),
        refresh_present=bool(refresh_summary["present"]),
        refresh_complete=bool(refresh_summary["complete"]),
        fx_present=bool(fx_summary["present"]),
        fx_complete=bool(fx_summary["complete"]),
        broker_config_presence=broker_summary,
        warning_codes=warnings,
    )


def _input_summary(input_file: Path, warnings: list[WarningCode]) -> dict[str, Any]:
    if not input_file.exists():
        warnings.append(WarningCode.NET_WORTH_DOCTOR_INPUT_MISSING)
        return {
            "present": False,
            "valid": False,
            "manual_nav_account_count": 0,
            "property_count": 0,
            "mortgage_count": 0,
            "cpf_count": 0,
            "srs_count": 0,
            "tax_count": 0,
            "hdb_loan_count": 0,
            "provider_labels": [],
            "base_currencies": [],
            "warning_codes": [WarningCode.NET_WORTH_DOCTOR_INPUT_MISSING.value],
        }
    validation = validate_private_input_center(input_file=input_file)
    if not validation.valid:
        warnings.append(WarningCode.NET_WORTH_DOCTOR_INPUT_INVALID)
    return {
        "present": True,
        "valid": validation.valid,
        "manual_nav_account_count": validation.manual_nav_account_count,
        "property_count": validation.property_count,
        "mortgage_count": validation.mortgage_count,
        "cpf_count": validation.cpf_count,
        "srs_count": validation.srs_count,
        "tax_count": validation.tax_count,
        "hdb_loan_count": validation.hdb_loan_count,
        "provider_labels": validation.provider_labels,
        "base_currencies": validation.base_currencies,
        "warning_codes": [code.value for code in validation.warning_codes],
    }


def _refresh_summary(refresh_dir: Path, warnings: list[WarningCode]) -> dict[str, Any]:
    required = _refresh_required_paths(refresh_dir)
    present = refresh_dir.exists()
    files = {name: path.exists() for name, path in required.items()}
    complete = present and all(files.values())
    if not present:
        warnings.append(WarningCode.NET_WORTH_DOCTOR_REFRESH_MISSING)
    elif not complete:
        warnings.append(WarningCode.NET_WORTH_DOCTOR_REFRESH_INCOMPLETE)
    return {
        "present": present,
        "complete": complete,
        "required_files": files,
    }


def _refresh_required_paths(refresh_dir: Path) -> dict[str, Path]:
    return {
        "merged_account_nav_ledger": refresh_dir / "merged" / "merged_account_nav_ledger.csv",
        "net_worth_history": refresh_dir / "snapshots" / "net_worth_history.csv",
        "net_worth_progress": refresh_dir / "dashboard" / "net_worth_progress.csv",
        "property_equity_summary": (
            refresh_dir
            / "manual_layers"
            / "property_mortgage"
            / "property_equity_summary.json"
        ),
        "cpf_snapshot_ledger": (
            refresh_dir
            / "manual_layers"
            / "sg_retirement_tax"
            / "cpf_snapshot_ledger.csv"
        ),
        "srs_snapshot_ledger": (
            refresh_dir
            / "manual_layers"
            / "sg_retirement_tax"
            / "srs_snapshot_ledger.csv"
        ),
    }


def _fx_summary(
    fx_rates_file: Path | None,
    *,
    required_currencies: set[str],
    warnings: list[WarningCode],
) -> dict[str, Any]:
    if fx_rates_file is None or not fx_rates_file.exists():
        warnings.append(WarningCode.NET_WORTH_DOCTOR_FX_MISSING)
        return {
            "present": False,
            "complete": False,
            "base_currency_present": False,
            "required_currencies": sorted(required_currencies),
            "covered_currencies": [],
            "missing_currencies": sorted(required_currencies),
        }
    try:
        payload = json.loads(fx_rates_file.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        warnings.append(WarningCode.NET_WORTH_DOCTOR_FX_INCOMPLETE)
        return {
            "present": True,
            "complete": False,
            "base_currency_present": False,
            "required_currencies": sorted(required_currencies),
            "covered_currencies": [],
            "missing_currencies": sorted(required_currencies),
        }
    rates = payload.get("rates_to_base") if isinstance(payload, dict) else None
    covered = {
        str(currency).upper()
        for currency, value in (rates or {}).items()
        if str(currency).strip() and str(value).strip()
    } if isinstance(rates, dict) else set()
    base_currency_present = bool(
        isinstance(payload, dict) and str(payload.get("base_currency", "")).strip()
    )
    missing = sorted(required_currencies - covered)
    complete = base_currency_present and not missing
    if not complete:
        warnings.append(WarningCode.NET_WORTH_DOCTOR_FX_INCOMPLETE)
    return {
        "present": True,
        "complete": complete,
        "base_currency_present": base_currency_present,
        "required_currencies": sorted(required_currencies),
        "covered_currencies": sorted(covered),
        "missing_currencies": missing,
    }


def _required_fx_currencies(refresh_dir: Path) -> set[str]:
    currencies = {"SGD", "USD", "CNY"}
    account_nav = refresh_dir / "merged" / "merged_account_nav_ledger.csv"
    for row in _read_csv(account_nav):
        currency = str(row.get("base_currency", "")).strip().upper()
        if currency:
            currencies.add(currency)
    return currencies


def _broker_config_summary(
    env: Mapping[str, str], warnings: list[WarningCode]
) -> dict[str, dict[str, bool]]:
    configs = {
        "ibkr": load_ibkr_config(env),
        "moomoo": load_moomoo_config(env),
        "tiger": load_tiger_config(env),
        "webull": load_webull_config(env),
    }
    summary: dict[str, dict[str, bool]] = {}
    for name, config in configs.items():
        provider_summary = _provider_config_presence(config)
        summary[name] = provider_summary
        if provider_summary["enabled"] and not provider_summary["required_config_present"]:
            warnings.append(WarningCode.NET_WORTH_DOCTOR_BROKER_CONFIG_MISSING)
    return summary


def _provider_config_presence(config: ProviderConfig) -> dict[str, bool]:
    return {
        "enabled": config.enabled,
        "required_config_present": not bool(config.missing_required_env_vars()),
        "optional_selector_present": any(
            bool(str(config.settings.get(key, "")).strip())
            for key in config.settings
            if key.endswith("_ACCOUNT") or key.endswith("_BASE_CURRENCY")
        ),
    }


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            return list(csv.DictReader(handle))
    except (OSError, UnicodeDecodeError, csv.Error):
        return []


def _write_warnings(path: Path, warnings: list[WarningCode]) -> None:
    lines = ["# Net Worth Doctor Warnings", ""]
    if warnings:
        lines.extend(f"- `{code.value}`" for code in warnings)
    else:
        lines.append("- None")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _report(summary: dict[str, Any]) -> str:
    warnings = summary["warning_codes"]
    refresh_files = summary["refresh"]["required_files"]
    broker_lines = [
        f"- {name}: enabled={_yes_no(values['enabled'])}; "
        f"required_config_present={_yes_no(values['required_config_present'])}"
        for name, values in sorted(summary["broker_config_presence"].items())
    ]
    lines = [
        "# Local Net Worth Doctor v0.6.2",
        "",
        "Offline health check for the local Personal CFO workflow. No external connection is used.",
        "",
        "## Input",
        "",
        f"- Present: {_yes_no(summary['input']['present'])}",
        f"- Valid: {_yes_no(summary['input']['valid'])}",
        f"- Manual NAV accounts: {summary['input']['manual_nav_account_count']}",
        f"- Properties: {summary['input']['property_count']}",
        f"- CPF rows: {summary['input']['cpf_count']}",
        f"- SRS rows: {summary['input']['srs_count']}",
        "",
        "## Refresh Bundle",
        "",
        f"- Present: {_yes_no(summary['refresh']['present'])}",
        f"- Complete: {_yes_no(summary['refresh']['complete'])}",
        *[f"- {name}: {_yes_no(present)}" for name, present in sorted(refresh_files.items())],
        "",
        "## FX",
        "",
        f"- Present: {_yes_no(summary['fx']['present'])}",
        f"- Complete: {_yes_no(summary['fx']['complete'])}",
        f"- Required currencies: {', '.join(summary['fx']['required_currencies']) or 'None'}",
        f"- Missing currencies: {', '.join(summary['fx']['missing_currencies']) or 'None'}",
        "",
        "## Broker Config Presence",
        "",
        *broker_lines,
        "",
        "## Warning Codes",
        "",
        *[f"- `{code}`" for code in warnings],
    ]
    return "\n".join(lines) + "\n"


def _yes_no(value: bool) -> str:
    return "yes" if value else "no"


def _dedupe_warning_codes(codes: list[WarningCode]) -> list[WarningCode]:
    seen: set[WarningCode] = set()
    result: list[WarningCode] = []
    for code in codes:
        if code in seen:
            continue
        seen.add(code)
        result.append(code)
    return result
