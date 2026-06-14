"""CLI runner and orchestration for Personal CFO Agent v0.1."""

from __future__ import annotations

import argparse
import os
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from personal_cfo_agent.config import (
    RuntimeConfig,
    load_ibkr_config,
    load_manual_config,
    load_moomoo_config,
    load_tiger_config,
)
from personal_cfo_agent.dashboard import write_dashboard
from personal_cfo_agent.manual_snapshot import (
    ManualSnapshotReadError,
    ManualSnapshotValidationError,
    load_manual_snapshot_document,
    write_manual_snapshot_template,
)
from personal_cfo_agent.local_env import LOCAL_ENV_FILENAME, load_local_env_file
from personal_cfo_agent.models import NormalizedAsset, ProviderStatus, RawProviderSnapshot
from personal_cfo_agent.normalizer import normalize_snapshots
from personal_cfo_agent.providers import (
    IBKRProvider,
    ManualSnapshotProvider,
    MoomooProvider,
    TigerProvider,
)
from personal_cfo_agent.providers.ibkr_connection_diagnostics import (
    IBKRConnectionDiagnostics,
    run_ibkr_connection_diagnostics,
)
from personal_cfo_agent.providers.tiger_connection_diagnostics import (
    TigerConnectionDiagnostics,
    run_tiger_connection_diagnostics,
)
from personal_cfo_agent.report_writer import write_report_bundle
from personal_cfo_agent.risk_engine import calculate_risk_summary


@dataclass(frozen=True)
class RunnerResult:
    exit_code: int
    statuses: list[ProviderStatus]
    normalized_assets: list[NormalizedAsset]
    output_dir: Path | None = None
    output_paths: dict[str, Path] = field(default_factory=dict)


def run(config: RuntimeConfig) -> RunnerResult:
    if config.readiness_check:
        return run_readiness_check(config)

    as_of_date = config.as_of_date or datetime.now(timezone.utc).strftime("%Y%m%d")
    snapshots = collect_provider_snapshots(config)
    statuses = [snapshot.status for snapshot in snapshots]
    data_snapshots = [snapshot for snapshot in snapshots if snapshot.has_data()]
    normalized_assets = normalize_snapshots(data_snapshots)
    statuses = _attach_diagnostic_normalized_rows(statuses, normalized_assets)
    if not normalized_assets:
        return RunnerResult(
            exit_code=0,
            statuses=statuses,
            normalized_assets=[],
            output_dir=None,
            output_paths={},
        )

    output_dir = config.output_dir or config.output_root / as_of_date
    if config.dashboard:
        output_paths = write_dashboard(
            output_dir,
            normalized_assets,
            statuses,
            config.dashboard_assumptions_path,
            as_of_date=as_of_date,
        )
    else:
        risk_summary = calculate_risk_summary(
            normalized_assets,
            expected_provider_count=len(snapshots),
            as_of_date=as_of_date,
        )
        output_paths = write_report_bundle(output_dir, statuses, normalized_assets, risk_summary)
    return RunnerResult(
        exit_code=0,
        statuses=statuses,
        normalized_assets=normalized_assets,
        output_dir=output_dir,
        output_paths=output_paths,
    )


def run_readiness_check(config: RuntimeConfig) -> RunnerResult:
    if config.provider == "ibkr":
        provider = IBKRProvider(load_ibkr_config(config.env), allow_live_read=False)
    elif config.provider == "moomoo":
        provider = MoomooProvider(load_moomoo_config(config.env), allow_live_read=False)
    elif config.provider == "tiger":
        provider = TigerProvider(load_tiger_config(config.env), allow_live_read=False)
    else:
        return RunnerResult(exit_code=0, statuses=[], normalized_assets=[])
    provider.readiness_check()
    return RunnerResult(exit_code=0, statuses=[provider._status()], normalized_assets=[])


def collect_provider_snapshots(config: RuntimeConfig) -> list[RawProviderSnapshot]:
    providers = []
    if config.provider in {"all", "ibkr"}:
        providers.append(
            IBKRProvider(
                load_ibkr_config(config.env),
                allow_live_read=config.allow_live_read and config.provider == "ibkr",
            )
        )
    if config.provider in {"all", "moomoo"}:
        providers.append(
            MoomooProvider(
                load_moomoo_config(config.env),
                allow_live_read=config.allow_live_read and config.provider == "moomoo",
            )
        )
    if config.provider in {"all", "tiger"}:
        providers.append(
            TigerProvider(
                load_tiger_config(config.env),
                allow_live_read=config.allow_live_read and config.provider == "tiger",
            )
        )
    if config.provider in {"all", "manual"}:
        providers.append(
            ManualSnapshotProvider(
                load_manual_config(config.env, config.manual_snapshot_path),
                allow_live_read=False,
            )
        )
    return [provider._sync() for provider in providers]


def _attach_diagnostic_normalized_rows(
    statuses: list[ProviderStatus], normalized_assets: list[NormalizedAsset]
) -> list[ProviderStatus]:
    row_counts: dict[str, int] = {}
    for row in normalized_assets:
        row_counts[row.provider] = row_counts.get(row.provider, 0) + 1
    updated: list[ProviderStatus] = []
    for status in statuses:
        if status.provider_name != "tiger" or not status.diagnostics:
            updated.append(status)
            continue
        diagnostics = dict(status.diagnostics)
        diagnostics["normalized_rows"] = row_counts.get(status.provider_name, 0)
        updated.append(replace(status, diagnostics=diagnostics))
    return updated


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Personal CFO Agent v0.1 runner")
    parser.add_argument(
        "--provider",
        choices=["all", "ibkr", "moomoo", "tiger", "manual"],
        default="all",
        help="Provider mode to run.",
    )
    parser.add_argument(
        "--readiness-check",
        action="store_true",
        help="Validate selected provider config without live connection.",
    )
    parser.add_argument(
        "--connection-diagnostics",
        action="store_true",
        help="Run redacted provider connection diagnostics without live API messages.",
    )
    parser.add_argument(
        "--ibkr-data-diagnostics",
        action="store_true",
        help="Print redacted IBKR live data-path diagnostics after a gated read.",
    )
    parser.add_argument(
        "--tiger-data-diagnostics",
        action="store_true",
        help="Print redacted Tiger live data-path diagnostics after a gated read.",
    )
    parser.add_argument(
        "--allow-live-read",
        action="store_true",
        help="Allow read-only live readiness checks for enabled API providers.",
    )
    parser.add_argument(
        "--manual-snapshot",
        type=Path,
        default=None,
        help="Path to a manual snapshot JSON fixture or export.",
    )
    parser.add_argument(
        "--write-manual-template",
        type=Path,
        default=None,
        help="Write an empty structured manual snapshot JSON template.",
    )
    parser.add_argument(
        "--validate-manual-snapshot",
        type=Path,
        default=None,
        help="Validate a structured manual snapshot JSON file without writing reports.",
    )
    parser.add_argument(
        "--dashboard",
        action="store_true",
        help="Write the v0.2.0 dashboard bundle from normalized provider/manual data.",
    )
    parser.add_argument(
        "--dashboard-assumptions",
        type=Path,
        default=None,
        help="Optional JSON assumptions file for the v0.2.0 dashboard.",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("reports/personal_cfo_agent/v01"),
        help="Root folder for generated report bundles.",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=None,
        help="Direct output directory for a report bundle.",
    )
    parser.add_argument(
        "--as-of-date",
        default=None,
        help="Report date in YYYYMMDD format.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    local_env_result = load_local_env_file()
    if local_env_result.exists:
        print(f"Loaded local environment from {LOCAL_ENV_FILENAME}; values redacted")
    if args.write_manual_template is not None and args.validate_manual_snapshot is not None:
        parser.error("--write-manual-template and --validate-manual-snapshot cannot be combined")
    if args.write_manual_template is not None:
        path = write_manual_snapshot_template(args.write_manual_template)
        print(f"Manual snapshot template written to {path}")
        return 0
    if args.validate_manual_snapshot is not None:
        return _validate_manual_snapshot_cli(args.validate_manual_snapshot)
    if args.connection_diagnostics:
        if args.provider not in {"ibkr", "tiger"}:
            parser.error(
                "--connection-diagnostics is currently implemented for --provider ibkr or tiger"
            )
        return _connection_diagnostics_cli(args.provider)
    if args.ibkr_data_diagnostics:
        if args.provider != "ibkr":
            parser.error("--ibkr-data-diagnostics requires --provider ibkr")
        if args.readiness_check:
            parser.error("--ibkr-data-diagnostics cannot be combined with --readiness-check")
        if not args.allow_live_read:
            parser.error("--ibkr-data-diagnostics requires --allow-live-read")
    if args.tiger_data_diagnostics:
        if args.provider != "tiger":
            parser.error("--tiger-data-diagnostics requires --provider tiger")
        if args.readiness_check:
            parser.error("--tiger-data-diagnostics cannot be combined with --readiness-check")
        if not args.allow_live_read:
            parser.error("--tiger-data-diagnostics requires --allow-live-read")
    if args.readiness_check and args.provider not in {"ibkr", "moomoo", "tiger"}:
        parser.error(
            "--readiness-check is currently implemented for --provider ibkr, moomoo, or tiger"
        )
    if args.as_of_date is not None:
        _validate_as_of_date(args.as_of_date, parser)
    if args.provider == "ibkr" and args.allow_live_read:
        print("Read-only IBKR sync only. No order methods are exposed.")
    if args.provider == "moomoo" and args.allow_live_read:
        print("Read-only Moomoo sync only. No order methods are exposed.")
    if args.provider == "tiger" and args.allow_live_read:
        print("Read-only Tiger sync only. No order methods are exposed.")
    result = run(
        RuntimeConfig(
            allow_live_read=args.allow_live_read,
            provider=args.provider,
            readiness_check=args.readiness_check,
            ibkr_data_diagnostics=args.ibkr_data_diagnostics,
            tiger_data_diagnostics=args.tiger_data_diagnostics,
            manual_snapshot_path=args.manual_snapshot,
            dashboard=args.dashboard,
            dashboard_assumptions_path=args.dashboard_assumptions,
            output_root=args.output_root,
            output_dir=args.out_dir,
            as_of_date=args.as_of_date,
        )
    )
    for status in result.statuses:
        warnings = ", ".join(code.value for code in status.warning_codes) or "None"
        print(f"{status.provider_name}: {status.connection_mode.value}; warnings={warnings}")
        if args.ibkr_data_diagnostics and status.provider_name == "ibkr":
            for line in _format_ibkr_data_diagnostics(status.diagnostics):
                print(line)
        if args.tiger_data_diagnostics and status.provider_name == "tiger":
            for line in _format_tiger_data_diagnostics(status.diagnostics):
                print(line)
    if result.output_dir is None:
        print("No provider produced data; no reports generated.")
    else:
        bundle_name = "Dashboard bundle" if args.dashboard else "Report bundle"
        print(f"{bundle_name} written to {result.output_dir}")
        print(f"Normalized ledger rows: {len(result.normalized_assets)}")
    return result.exit_code


def _validate_as_of_date(value: str, parser: argparse.ArgumentParser) -> None:
    try:
        datetime.strptime(value, "%Y%m%d")
    except ValueError:
        parser.error("--as-of-date must use YYYYMMDD")


def _validate_manual_snapshot_cli(path: Path) -> int:
    try:
        document = load_manual_snapshot_document(path)
    except ManualSnapshotValidationError as exc:
        _print_manual_validation_issues(exc.result.errors, "error")
        _print_manual_validation_issues(exc.result.warnings, "warning")
        print("Manual snapshot validation failed.")
        return 1
    except ManualSnapshotReadError as exc:
        print(f"Manual snapshot validation failed: {exc}")
        return 1

    _print_manual_validation_issues(document.validation_result.warnings, "warning")
    print("Manual snapshot validation passed.")
    return 0


def _print_manual_validation_issues(issues, severity: str) -> None:
    for issue in issues:
        print(f"{severity}: {issue.path}: {issue.code.value}: {issue.message}")


def _connection_diagnostics_cli(provider: str) -> int:
    if provider == "ibkr":
        diagnostics = run_ibkr_connection_diagnostics(dict(os.environ))
        for line in _format_ibkr_connection_diagnostics(diagnostics):
            print(line)
        return 0
    diagnostics = run_tiger_connection_diagnostics(dict(os.environ))
    for line in _format_tiger_connection_diagnostics(diagnostics):
        print(line)
    return 0


def _format_ibkr_connection_diagnostics(
    diagnostics: IBKRConnectionDiagnostics,
) -> list[str]:
    warning_text = ", ".join(code.value for code in diagnostics.warning_codes) or "None"
    return [
        "IBKR connection diagnostics (values redacted)",
        f"CFO_IBKR_ENABLED present and true: {_yes_no(diagnostics.enabled_present and diagnostics.enabled_true)}",
        f"CFO_IBKR_HOST present: {_yes_no(diagnostics.host_present)}",
        f"CFO_IBKR_PORT present: {_yes_no(diagnostics.port_present)}",
        f"CFO_IBKR_CLIENT_ID present: {_yes_no(diagnostics.client_id_present)}",
        f"CFO_IBKR_ACCOUNT present: {_yes_no(diagnostics.account_present)}, redacted",
        f"CFO_ACCOUNT_HASH_SALT present: {_yes_no(diagnostics.hash_salt_present)}, redacted",
        f"Python executable: {diagnostics.python_executable}",
        f"ibapi import status: {'OK' if diagnostics.ibapi_import_ok else 'MISSING'}",
        f"TCP socket reachable host/port: {_yes_no(diagnostics.tcp_socket_reachable)}",
        f"diagnostic warning codes: {warning_text}",
    ]


def _format_tiger_connection_diagnostics(
    diagnostics: TigerConnectionDiagnostics,
) -> list[str]:
    warning_text = ", ".join(code.value for code in diagnostics.warning_codes) or "None"
    return [
        "Tiger connection diagnostics (values redacted)",
        f"CFO_TIGER_ENABLED present and true: {_yes_no(diagnostics.enabled_present and diagnostics.enabled_true)}",
        f"CFO_TIGER_CONFIG_DIR present: {_yes_no(diagnostics.config_dir_present)}",
        f"Config dir exists: {_yes_no(diagnostics.config_dir_exists)}",
        f"Config file exists: {_yes_no(diagnostics.config_file_exists)}",
        f"CFO_TIGER_ACCOUNT present: {_yes_no(diagnostics.account_present)}, redacted",
        f"CFO_ACCOUNT_HASH_SALT present: {_yes_no(diagnostics.hash_salt_present)}, redacted",
        f"Python executable: {diagnostics.python_executable}",
        f"tigeropen import status: {'OK' if diagnostics.tigeropen_import_ok else 'MISSING'}",
        f"diagnostic warning codes: {warning_text}",
    ]


def _format_ibkr_data_diagnostics(diagnostics: dict[str, object]) -> list[str]:
    if not diagnostics:
        return ["IBKR data-path diagnostics (values redacted): unavailable"]
    warning_codes = diagnostics.get("warning_codes") or []
    warning_text = ", ".join(str(code) for code in warning_codes) or "None"
    requested_hash = diagnostics.get("requested_account_hash") or "not configured"
    requested_seen = diagnostics.get("requested_account_seen")
    requested_seen_text = "not configured" if requested_seen is None else _yes_no(bool(requested_seen))
    return [
        "IBKR data-path diagnostics (values redacted)",
        f"Connected to socket: {_yes_no(bool(diagnostics.get('connected_to_socket')))}",
        f"API handshake observed: {_yes_no(bool(diagnostics.get('api_handshake_seen')))}",
        f"Managed accounts callback observed: {_yes_no(bool(diagnostics.get('managed_accounts_seen')))}",
        f"Managed account count redacted: {diagnostics.get('managed_account_count_redacted', 0)}",
        f"Requested account hash: {requested_hash}",
        f"Requested account observed in managed accounts: {requested_seen_text}",
        f"Positions callback observed: {_yes_no(bool(diagnostics.get('positions_callback_seen')))}",
        f"Position count: {diagnostics.get('position_count', 0)}",
        f"Account summary callback observed: {_yes_no(bool(diagnostics.get('account_summary_callback_seen')))}",
        f"Cash currency count: {diagnostics.get('cash_currency_count', 0)}",
        f"Timeout seconds: {diagnostics.get('timeout_seconds', 0)}",
        f"Data diagnostic warning codes: {warning_text}",
    ]


def _format_tiger_data_diagnostics(diagnostics: dict[str, object]) -> list[str]:
    if not diagnostics:
        return ["Tiger data-path diagnostics (values redacted): unavailable"]
    warning_codes = diagnostics.get("warning_codes") or []
    warning_text = ", ".join(str(code) for code in warning_codes) or "None"
    stage_failures = diagnostics.get("stage_failures") or {}
    if isinstance(stage_failures, dict):
        stage_text = ", ".join(
            f"{key}={value}" for key, value in stage_failures.items()
        ) or "None"
    else:
        stage_text = "unavailable"
    return [
        "Tiger data-path diagnostics (values redacted)",
        f"SDK import OK: {_yes_no(bool(diagnostics.get('sdk_import_ok')))}",
        f"Config loaded: {_yes_no(bool(diagnostics.get('config_loaded')))}",
        f"Account context observed: {_yes_no(bool(diagnostics.get('account_context_observed')))}",
        f"Selected account hash: {diagnostics.get('selected_account_hash', 'not configured')}",
        f"Account count redacted: {diagnostics.get('account_count_redacted', 0)}",
        f"Asset query attempted: {_yes_no(bool(diagnostics.get('asset_query_attempted')))}",
        f"Asset query success: {_yes_no(bool(diagnostics.get('asset_query_success')))}",
        f"Position query attempted: {_yes_no(bool(diagnostics.get('position_query_attempted')))}",
        f"Position query success: {_yes_no(bool(diagnostics.get('position_query_success')))}",
        f"Position count: {diagnostics.get('position_count', 0)}",
        f"Cash currency count: {diagnostics.get('cash_currency_count', 0)}",
        f"Normalized rows: {diagnostics.get('normalized_rows', 0)}",
        f"SDK output suppressed: {_yes_no(bool(diagnostics.get('sdk_output_suppressed')))}",
        f"Data diagnostic warning codes: {warning_text}",
        f"Stage failures: {stage_text}",
    ]


def _yes_no(value: bool) -> str:
    return "yes" if value else "no"
