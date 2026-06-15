"""CLI runner and orchestration for Personal CFO Agent v0.1."""

from __future__ import annotations

import argparse
import json
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
from personal_cfo_agent.models import (
    NormalizedAsset,
    ProviderStatus,
    RawProviderSnapshot,
    WarningCode,
)
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
from personal_cfo_agent.providers.moomoo_connection_diagnostics import (
    MoomooConnectionDiagnostics,
    run_moomoo_connection_diagnostics,
)
from personal_cfo_agent.providers.moomoo_account_discovery import (
    run_moomoo_account_discovery,
)
from personal_cfo_agent.providers.moomoo_read_context_probe import (
    run_moomoo_read_context_probe,
)
from personal_cfo_agent.providers.tiger_connection_diagnostics import (
    TigerConfigPreflight,
    TigerConnectionDiagnostics,
    TigerSDKConfigProbe,
    run_tiger_config_preflight,
    run_tiger_connection_diagnostics,
    run_tiger_sdk_config_probe,
)
from personal_cfo_agent.provider_bundle_merge import MergeResult, merge_provider_bundles
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
    try:
        normalized_assets = normalize_snapshots(data_snapshots)
    except Exception:
        if any(snapshot.provider_name == "moomoo" for snapshot in data_snapshots):
            return RunnerResult(
                exit_code=1,
                statuses=_mark_moomoo_normalization_failed(statuses),
                normalized_assets=[],
                output_dir=None,
                output_paths={},
            )
        if any(snapshot.provider_name == "tiger" for snapshot in data_snapshots):
            return RunnerResult(
                exit_code=1,
                statuses=_mark_tiger_normalization_failed(statuses),
                normalized_assets=[],
                output_dir=None,
                output_paths={},
            )
        raise
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


def _mark_moomoo_normalization_failed(
    statuses: list[ProviderStatus],
) -> list[ProviderStatus]:
    updated_statuses: list[ProviderStatus] = []
    for status in statuses:
        if status.provider_name != "moomoo":
            updated_statuses.append(status)
            continue
        warning_codes = _dedupe_warning_codes(
            [
                *status.warning_codes,
                WarningCode.MOOMOO_NORMALIZATION_FAILED,
                WarningCode.PROVIDER_FETCH_FAILED,
            ]
        )
        diagnostics = dict(status.diagnostics)
        stage_failures = dict(diagnostics.get("stage_failures") or {})
        stage_failures["normalization"] = "Normalization failed"
        diagnostics["stage_failures"] = stage_failures
        diagnostics["normalized_rows"] = 0
        diagnostics["warning_codes"] = _dedupe_text(
            [
                *[str(code) for code in diagnostics.get("warning_codes", [])],
                WarningCode.MOOMOO_NORMALIZATION_FAILED.value,
                WarningCode.PROVIDER_FETCH_FAILED.value,
            ]
        )
        updated_statuses.append(
            replace(status, warning_codes=warning_codes, diagnostics=diagnostics)
        )
    return updated_statuses


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


def _mark_tiger_normalization_failed(statuses: list[ProviderStatus]) -> list[ProviderStatus]:
    updated: list[ProviderStatus] = []
    for status in statuses:
        if status.provider_name != "tiger":
            updated.append(status)
            continue
        diagnostics = dict(status.diagnostics)
        warning_codes = [
            *diagnostics.get("warning_codes", []),
            WarningCode.TIGER_NORMALIZATION_FAILED.value,
            WarningCode.PROVIDER_FETCH_FAILED.value,
        ]
        diagnostics["warning_codes"] = _dedupe_text(warning_codes)
        stage_failures = dict(diagnostics.get("stage_failures", {}))
        stage_failures["normalization"] = "Tiger normalization failed"
        diagnostics["stage_failures"] = stage_failures
        diagnostics["normalized_rows"] = 0
        updated.append(
            replace(
                status,
                warning_codes=_dedupe_warning_codes(
                    [
                        *status.warning_codes,
                        WarningCode.TIGER_NORMALIZATION_FAILED,
                        WarningCode.PROVIDER_FETCH_FAILED,
                    ]
                ),
                diagnostics=diagnostics,
            )
        )
    return updated


def _dedupe_warning_codes(codes: list[WarningCode]) -> list[WarningCode]:
    seen: set[WarningCode] = set()
    result: list[WarningCode] = []
    for code in codes:
        if code not in seen:
            result.append(code)
            seen.add(code)
    return result


def _dedupe_text(values: list[object]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value)
        if text not in seen:
            result.append(text)
            seen.add(text)
    return result


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
        "--config-preflight",
        action="store_true",
        help="Run redacted Tiger config preflight without TigerOpen client initialization.",
    )
    parser.add_argument(
        "--sdk-config-probe",
        action="store_true",
        help="Run redacted TigerOpen SDK config compatibility probe without account data calls.",
    )
    parser.add_argument(
        "--ibkr-data-diagnostics",
        action="store_true",
        help="Print redacted IBKR live data-path diagnostics after a gated read.",
    )
    parser.add_argument(
        "--moomoo-data-diagnostics",
        action="store_true",
        help="Print redacted Moomoo live data-path diagnostics after a gated read.",
    )
    parser.add_argument(
        "--account-discovery",
        action="store_true",
        help="Run redacted Moomoo account-context discovery using get_acc_list only.",
    )
    parser.add_argument(
        "--read-context-probe",
        action="store_true",
        help="Run redacted Moomoo read-context diagnostics after account discovery.",
    )
    parser.add_argument(
        "--tiger-data-diagnostics",
        action="store_true",
        help="Print redacted Tiger live data-path diagnostics after a gated read.",
    )
    parser.add_argument(
        "--merge-provider-bundles",
        action="store_true",
        help="Merge existing normalized provider bundles offline without broker connections.",
    )
    parser.add_argument(
        "--input-root",
        type=Path,
        default=Path("reports/personal_cfo_agent"),
        help="Root folder containing provider report bundles for offline merge.",
    )
    parser.add_argument(
        "--fixture-mode",
        action="store_true",
        help="Generate and merge synthetic provider fixtures only.",
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
    if args.merge_provider_bundles:
        return _merge_provider_bundles_cli(args, parser)
    local_env_result = load_local_env_file()
    if local_env_result.exists and not (args.account_discovery or args.read_context_probe):
        print(f"Loaded local environment from {LOCAL_ENV_FILENAME}; values redacted")
    if args.write_manual_template is not None and args.validate_manual_snapshot is not None:
        parser.error("--write-manual-template and --validate-manual-snapshot cannot be combined")
    if args.write_manual_template is not None:
        path = write_manual_snapshot_template(args.write_manual_template)
        print(f"Manual snapshot template written to {path}")
        return 0
    if args.validate_manual_snapshot is not None:
        return _validate_manual_snapshot_cli(args.validate_manual_snapshot)
    if args.config_preflight and args.sdk_config_probe:
        parser.error("--config-preflight and --sdk-config-probe cannot be combined")
    if args.config_preflight:
        if args.provider != "tiger":
            parser.error("--config-preflight requires --provider tiger")
        if args.allow_live_read:
            parser.error("--config-preflight cannot be combined with --allow-live-read")
        if args.readiness_check or args.connection_diagnostics:
            parser.error(
                "--config-preflight cannot be combined with --readiness-check or --connection-diagnostics"
            )
        return _tiger_config_preflight_cli()
    if args.sdk_config_probe:
        if args.provider != "tiger":
            parser.error("--sdk-config-probe requires --provider tiger")
        if args.allow_live_read:
            parser.error("--sdk-config-probe cannot be combined with --allow-live-read")
        if args.readiness_check or args.connection_diagnostics:
            parser.error(
                "--sdk-config-probe cannot be combined with --readiness-check or --connection-diagnostics"
            )
        return _tiger_sdk_config_probe_cli()
    if args.connection_diagnostics:
        if args.provider not in {"ibkr", "moomoo", "tiger"}:
            parser.error(
                "--connection-diagnostics is currently implemented for --provider ibkr, moomoo, or tiger"
            )
        return _connection_diagnostics_cli(args.provider, local_env_result.exists)
    if args.account_discovery:
        if args.provider != "moomoo":
            parser.error("--account-discovery requires --provider moomoo")
        if args.readiness_check:
            parser.error("--account-discovery cannot be combined with --readiness-check")
        if args.connection_diagnostics:
            parser.error("--account-discovery cannot be combined with --connection-diagnostics")
        if args.moomoo_data_diagnostics:
            parser.error("--account-discovery cannot be combined with --moomoo-data-diagnostics")
        if args.read_context_probe:
            parser.error("--account-discovery cannot be combined with --read-context-probe")
        return _moomoo_account_discovery_cli()
    if args.read_context_probe:
        if args.provider != "moomoo":
            parser.error("--read-context-probe requires --provider moomoo")
        if args.readiness_check:
            parser.error("--read-context-probe cannot be combined with --readiness-check")
        if args.connection_diagnostics:
            parser.error(
                "--read-context-probe cannot be combined with --connection-diagnostics"
            )
        if args.moomoo_data_diagnostics:
            parser.error(
                "--read-context-probe cannot be combined with --moomoo-data-diagnostics"
            )
        if args.ibkr_data_diagnostics:
            parser.error(
                "--read-context-probe cannot be combined with --ibkr-data-diagnostics"
            )
        return _moomoo_read_context_probe_cli()
    if args.ibkr_data_diagnostics:
        if args.provider != "ibkr":
            parser.error("--ibkr-data-diagnostics requires --provider ibkr")
        if args.readiness_check:
            parser.error("--ibkr-data-diagnostics cannot be combined with --readiness-check")
        if not args.allow_live_read:
            parser.error("--ibkr-data-diagnostics requires --allow-live-read")
    if args.moomoo_data_diagnostics:
        if args.provider != "moomoo":
            parser.error("--moomoo-data-diagnostics requires --provider moomoo")
        if args.readiness_check:
            parser.error("--moomoo-data-diagnostics cannot be combined with --readiness-check")
        if not args.allow_live_read:
            parser.error("--moomoo-data-diagnostics requires --allow-live-read")
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
            moomoo_data_diagnostics=args.moomoo_data_diagnostics,
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
        if args.moomoo_data_diagnostics and status.provider_name == "moomoo":
            for line in _format_moomoo_data_diagnostics(status.diagnostics):
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


def _merge_provider_bundles_cli(
    args: argparse.Namespace, parser: argparse.ArgumentParser
) -> int:
    if args.allow_live_read:
        parser.error("--merge-provider-bundles cannot be combined with --allow-live-read")
    if args.readiness_check or args.connection_diagnostics:
        parser.error(
            "--merge-provider-bundles cannot be combined with readiness or connection diagnostics"
        )
    if args.account_discovery or args.read_context_probe:
        parser.error(
            "--merge-provider-bundles cannot be combined with Moomoo discovery probes"
        )
    if args.ibkr_data_diagnostics or args.moomoo_data_diagnostics or args.tiger_data_diagnostics:
        parser.error("--merge-provider-bundles cannot be combined with data diagnostics")
    if args.write_manual_template is not None or args.validate_manual_snapshot is not None:
        parser.error("--merge-provider-bundles cannot be combined with manual snapshot utilities")
    if args.out_dir is None:
        parser.error("--merge-provider-bundles requires --out-dir")

    result = merge_provider_bundles(
        input_root=None if args.fixture_mode else args.input_root,
        out_dir=args.out_dir,
        fixture_mode=args.fixture_mode,
    )
    for line in _format_merge_result(result):
        print(line)
    return 0


def _format_merge_result(result: MergeResult) -> list[str]:
    warnings = ", ".join(code.value for code in result.warning_codes) or "None"
    provider_counts = ", ".join(
        f"{provider}={count}" for provider, count in sorted(result.provider_counts.items())
    ) or "None"
    return [
        "Multi-provider normalized ledger merge (offline)",
        "Broker connections used: no",
        f"Output directory: {result.output_dir}",
        f"Source bundle count: {result.source_bundle_count}",
        f"Merged normalized rows: {result.row_count}",
        f"Provider row counts: {provider_counts}",
        f"Warning codes: {warnings}",
    ]


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


def _connection_diagnostics_cli(provider: str, local_env_loaded: bool) -> int:
    if provider == "ibkr":
        diagnostics = run_ibkr_connection_diagnostics(dict(os.environ))
        lines = _format_ibkr_connection_diagnostics(diagnostics)
    elif provider == "moomoo":
        diagnostics = run_moomoo_connection_diagnostics(
            dict(os.environ),
            local_env_loaded=local_env_loaded,
        )
        lines = _format_moomoo_connection_diagnostics(diagnostics)
    else:
        diagnostics = run_tiger_connection_diagnostics(dict(os.environ))
        lines = _format_tiger_connection_diagnostics(diagnostics)
    for line in lines:
        print(line)
    return 0


def _tiger_config_preflight_cli() -> int:
    diagnostics = run_tiger_config_preflight(dict(os.environ))
    for line in _format_tiger_config_preflight(diagnostics):
        print(line)
    if WarningCode.TIGER_CONFIG_PREFLIGHT_OK in diagnostics.warning_codes:
        return 0
    return 1


def _tiger_sdk_config_probe_cli() -> int:
    diagnostics = run_tiger_sdk_config_probe(dict(os.environ))
    for line in _format_tiger_sdk_config_probe(diagnostics):
        print(line)
    if diagnostics.sdk_config_constructed:
        return 0
    return 1


def _moomoo_account_discovery_cli() -> int:
    diagnostics = run_moomoo_account_discovery(dict(os.environ))
    print(json.dumps(diagnostics.to_redacted_dict(), indent=2))
    return 0


def _moomoo_read_context_probe_cli() -> int:
    diagnostics = run_moomoo_read_context_probe(dict(os.environ))
    print(json.dumps(diagnostics.to_redacted_dict(), indent=2))
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


def _format_moomoo_connection_diagnostics(
    diagnostics: MoomooConnectionDiagnostics,
) -> list[str]:
    warning_text = ", ".join(code.value for code in diagnostics.warning_codes) or "None"
    return [
        "Moomoo connection diagnostics (values redacted)",
        f"{LOCAL_ENV_FILENAME} loaded: {_yes_no(diagnostics.local_env_loaded)}",
        f"CFO_MOOMOO_ENABLED present and true: {_yes_no(diagnostics.enabled_present and diagnostics.enabled_true)}",
        f"CFO_MOOMOO_HOST present: {_yes_no(diagnostics.host_present)}",
        f"CFO_MOOMOO_PORT present: {_yes_no(diagnostics.port_present)}",
        f"CFO_ACCOUNT_HASH_SALT present: {_yes_no(diagnostics.hash_salt_present)}, redacted",
        f"Python executable: {diagnostics.python_executable}",
        f"futu import status: {'OK' if diagnostics.futu_import_ok else 'MISSING'}",
        f"OpenD socket reachable host/port: {_yes_no(diagnostics.opend_socket_reachable)}",
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
        f"Tiger ID present: {_yes_no(diagnostics.tiger_id_present)}, redacted",
        f"CFO_TIGER_ACCOUNT present: {_yes_no(diagnostics.account_present)}, redacted",
        f"Config account present: {_yes_no(diagnostics.config_account_present)}, redacted",
        f"Private key present: {_yes_no(diagnostics.private_key_present)}, redacted",
        f"Private key format detected: {diagnostics.private_key_format_detected}",
        f"CFO_ACCOUNT_HASH_SALT present: {_yes_no(diagnostics.hash_salt_present)}, redacted",
        f"Python executable: {diagnostics.python_executable}",
        f"tigeropen import status: {'OK' if diagnostics.tigeropen_import_ok else 'MISSING'}",
        f"diagnostic warning codes: {warning_text}",
    ]


def _format_tiger_config_preflight(diagnostics: TigerConfigPreflight) -> list[str]:
    warning_text = ", ".join(code.value for code in diagnostics.warning_codes) or "None"
    return [
        "Tiger config preflight (values redacted)",
        f"CFO_TIGER_ENABLED present and true: {_yes_no(diagnostics.enabled_present and diagnostics.enabled_true)}",
        f"CFO_TIGER_CONFIG_DIR present: {_yes_no(diagnostics.config_dir_present)}",
        f"Expected config file pattern: {diagnostics.expected_config_file_pattern}",
        f"Expected config filename: {diagnostics.expected_props_filename}",
        f"Adapter props_path expectation: {diagnostics.props_path_expectation}",
        "TigerOpen config private-key fields: private_key_pk1 or private_key_pk8",
        "TigerOpen env/private-key path option: TIGEROPEN_PRIVATE_KEY or private_key_path",
        f"Config dir exists: {_yes_no(diagnostics.config_dir_exists)}",
        f"Config dir is directory: {_yes_no(diagnostics.config_dir_is_directory)}",
        f"Adapter props_path shape valid: {_yes_no(diagnostics.props_path_matches_adapter)}",
        f"Config file exists: {_yes_no(diagnostics.config_file_exists)}",
        f"Config file readable: {_yes_no(diagnostics.config_file_readable)}",
        f"Config file outside repository: {_yes_no(diagnostics.config_file_outside_repo)}",
        f"Config file tracked by git: {_yes_no(diagnostics.config_file_tracked)}",
        f"Config history risk detected: {_yes_no(diagnostics.config_history_risk)}",
        f"Tiger ID present: {_yes_no(diagnostics.tiger_id_present)}, redacted",
        f"CFO_TIGER_ACCOUNT present: {_yes_no(diagnostics.account_present)}, redacted",
        f"Config account present: {_yes_no(diagnostics.config_account_present)}, redacted",
        f"Private key field present: {_yes_no(diagnostics.private_key_field_present)}, redacted",
        f"Private key path/env present: {_yes_no(diagnostics.private_key_path_present)}, redacted",
        f"Private key format category: {diagnostics.private_key_format_category}",
        f"Preflight warning codes: {warning_text}",
        "TigerOpen client initialized: no",
        "Tiger account APIs called: no",
    ]


def _format_tiger_sdk_config_probe(diagnostics: TigerSDKConfigProbe) -> list[str]:
    warning_text = ", ".join(code.value for code in diagnostics.warning_codes) or "None"
    required = diagnostics.required_keys_present_redacted
    lines = [
        "TigerOpen SDK config compatibility probe (values redacted)",
        f"SDK import OK: {_yes_no(diagnostics.sdk_import_ok)}",
        f"TigerOpen package path: {diagnostics.tigeropen_package_path}",
        f"Props path modes tested: {', '.join(diagnostics.props_path_modes_tested)}",
        f"Working props_path mode: {diagnostics.working_props_path_mode}",
        f"Expected config filename: {diagnostics.expected_config_filename}",
        f"Config file detected: {_yes_no(diagnostics.config_file_detected)}",
        f"Required key tiger_id present: {_yes_no(bool(required.get('tiger_id')))}, redacted",
        f"Required key account present: {_yes_no(bool(required.get('account')))}, redacted",
        f"Required key private_key present: {_yes_no(bool(required.get('private_key')))}, redacted",
        f"Private key format category: {diagnostics.private_key_format_category}",
        f"SDK config constructed: {_yes_no(diagnostics.sdk_config_constructed)}",
        f"SDK client constructed: {_yes_no(diagnostics.sdk_client_constructed)}",
        f"SDK exception class sanitized: {diagnostics.sdk_exception_class_sanitized}",
        f"SDK exception category: {diagnostics.sdk_exception_category}",
    ]
    for result in diagnostics.variant_results:
        variant_warning_text = (
            ", ".join(code.value for code in result.warning_codes) or "None"
        )
        lines.append(
            "Mode "
            f"{result.mode}: config={_yes_no(result.config_constructed)}; "
            f"client={_yes_no(result.client_constructed)}; "
            f"exception_class={result.exception_class_sanitized}; "
            f"category={result.exception_category}; "
            f"warning_codes={variant_warning_text}"
        )
    lines.extend(
        [
            f"Probe warning codes: {warning_text}",
            "Tiger account data APIs called: no",
            "Tiger order/cash-transfer APIs called: no",
        ]
    )
    return lines


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


def _format_moomoo_data_diagnostics(diagnostics: dict[str, object]) -> list[str]:
    if not diagnostics:
        return ["Moomoo data-path diagnostics (values redacted): unavailable"]
    warning_codes = diagnostics.get("warning_codes") or []
    warning_text = ", ".join(str(code) for code in warning_codes) or "None"
    terminal_warning_codes = diagnostics.get("terminal_warning_codes") or []
    terminal_warning_text = (
        ", ".join(str(code) for code in terminal_warning_codes) or "None"
    )
    variant_warning_codes = diagnostics.get("variant_warning_codes") or []
    variant_warning_text = ", ".join(str(code) for code in variant_warning_codes) or "None"
    stage_failures = diagnostics.get("stage_failures") or {}
    if isinstance(stage_failures, dict):
        stage_failure_text = (
            ", ".join(f"{stage}={summary}" for stage, summary in stage_failures.items())
            or "None"
        )
    else:
        stage_failure_text = "None"
    selected_account_hash = diagnostics.get("selected_account_hash") or "not selected"
    selected_context_mode = diagnostics.get("selected_context_mode") or "not selected"
    selected_discovery_context_mode = (
        diagnostics.get("selected_discovery_context_mode") or "not selected"
    )
    selected_read_context_mode = (
        diagnostics.get("selected_read_context_mode") or "not selected"
    )
    return [
        "Moomoo data-path diagnostics (values redacted)",
        f"SDK import OK: {_yes_no(bool(diagnostics.get('sdk_import_ok')))}",
        f"OpenD reachable: {_yes_no(bool(diagnostics.get('opend_socket_reachable')))}",
        f"Discovery success: {_yes_no(bool(diagnostics.get('discovery_success')))}",
        f"Context opened: {_yes_no(bool(diagnostics.get('context_opened')))}",
        f"Account list attempted: {_yes_no(bool(diagnostics.get('account_list_query_attempted')))}",
        f"Account list success: {_yes_no(bool(diagnostics.get('account_list_query_success')))}",
        f"Account count redacted: {diagnostics.get('account_count_redacted', 0)}",
        f"Selected account hash: {selected_account_hash}",
        f"Selected context mode: {selected_context_mode}",
        f"Selected discovery context mode: {selected_discovery_context_mode}",
        f"Selected read context mode: {selected_read_context_mode}",
        f"Account filter mismatch: {_yes_no(bool(diagnostics.get('account_filter_mismatch')))}",
        f"Account info attempted: {_yes_no(bool(diagnostics.get('account_info_query_attempted')))}",
        f"Account info success: {_yes_no(bool(diagnostics.get('account_info_query_success')))}",
        f"Accinfo query attempted: {_yes_no(bool(diagnostics.get('accinfo_query_attempted')))}",
        f"Accinfo query success: {_yes_no(bool(diagnostics.get('accinfo_query_success')))}",
        f"Accinfo failure stage: {diagnostics.get('accinfo_failure_stage') or 'None'}",
        f"Accinfo SDK ret code sanitized: {diagnostics.get('accinfo_sdk_ret_code_sanitized') or 'None'}",
        f"Accinfo exception category sanitized: {diagnostics.get('accinfo_exception_category_sanitized') or 'None'}",
        f"Positions attempted: {_yes_no(bool(diagnostics.get('position_query_attempted')))}",
        f"Positions success: {_yes_no(bool(diagnostics.get('position_query_success')))}",
        f"Position failure stage: {diagnostics.get('position_failure_stage') or 'None'}",
        f"Position SDK ret code sanitized: {diagnostics.get('position_sdk_ret_code_sanitized') or 'None'}",
        f"Position exception category sanitized: {diagnostics.get('position_exception_category_sanitized') or 'None'}",
        f"Position count: {diagnostics.get('position_count', 0)}",
        f"Cash/balance attempted: {_yes_no(bool(diagnostics.get('cash_query_attempted')))}",
        f"Cash/balance success: {_yes_no(bool(diagnostics.get('cash_query_success')))}",
        f"Cash currency count: {diagnostics.get('cash_currency_count', 0)}",
        f"Normalized rows count: {diagnostics.get('normalized_rows', 0)}",
        f"SDK output suppressed: {_yes_no(bool(diagnostics.get('sdk_output_suppressed')))}",
        f"Forbidden API called: {_yes_no(bool(diagnostics.get('forbidden_api_called')))}",
        f"Timeout seconds: {diagnostics.get('timeout_seconds', 0)}",
        f"Terminal warning codes: {terminal_warning_text}",
        f"Variant warning codes: {variant_warning_text}",
        f"Data diagnostic warning codes: {warning_text}",
        f"Stage failures: {stage_failure_text}",
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
        f"Config dir exists: {_yes_no(bool(diagnostics.get('config_dir_exists')))}",
        f"Config file exists: {_yes_no(bool(diagnostics.get('config_file_exists')))}",
        f"Config loaded: {_yes_no(bool(diagnostics.get('config_loaded')))}",
        f"Tiger config mode selected: {diagnostics.get('tiger_config_mode_selected', 'failed')}",
        f"Tiger config constructed: {_yes_no(bool(diagnostics.get('tiger_config_constructed')))}",
        f"Tiger client constructed: {_yes_no(bool(diagnostics.get('tiger_client_constructed')))}",
        "Tiger config warning codes: "
        + (
            ", ".join(str(code) for code in diagnostics.get("tiger_config_warning_codes", []))
            or "None"
        ),
        f"Tiger ID present: {_yes_no(bool(diagnostics.get('tiger_id_present_redacted')))}, redacted",
        f"Account present: {_yes_no(bool(diagnostics.get('account_present_redacted')))}, redacted",
        f"Private key present: {_yes_no(bool(diagnostics.get('private_key_present_redacted')))}, redacted",
        f"Private key format detected: {diagnostics.get('private_key_format_detected_redacted', 'missing')}",
        f"Client init attempted: {_yes_no(bool(diagnostics.get('client_init_attempted')))}",
        f"Client init success: {_yes_no(bool(diagnostics.get('client_init_success')))}",
        f"Client auth success: {_yes_no(bool(diagnostics.get('client_auth_success')))}",
        f"Account context observed: {_yes_no(bool(diagnostics.get('account_context_observed')))}",
        f"Selected account hash: {diagnostics.get('selected_account_hash', 'not configured')}",
        f"Account count redacted: {diagnostics.get('account_count_redacted', 0)}",
        f"Assets query attempted: {_yes_no(bool(diagnostics.get('assets_query_attempted')))}",
        f"Assets query success: {_yes_no(bool(diagnostics.get('assets_query_success')))}",
        f"Positions query attempted: {_yes_no(bool(diagnostics.get('positions_query_attempted')))}",
        f"Positions query success: {_yes_no(bool(diagnostics.get('positions_query_success')))}",
        f"Position count: {diagnostics.get('position_count', 0)}",
        f"Cash query attempted: {_yes_no(bool(diagnostics.get('cash_query_attempted')))}",
        f"Cash query success: {_yes_no(bool(diagnostics.get('cash_query_success')))}",
        f"Cash currency count: {diagnostics.get('cash_currency_count', 0)}",
        f"Normalized rows: {diagnostics.get('normalized_rows', 0)}",
        f"SDK output suppressed: {_yes_no(bool(diagnostics.get('sdk_output_suppressed')))}",
        f"Data diagnostic warning codes: {warning_text}",
        f"Stage failures: {stage_text}",
    ]


def _yes_no(value: bool) -> str:
    return "yes" if value else "no"
