"""CLI runner and orchestration for Personal CFO Agent v0.1."""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
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
from personal_cfo_agent.models import NormalizedAsset, ProviderStatus, RawProviderSnapshot
from personal_cfo_agent.normalizer import normalize_snapshots
from personal_cfo_agent.providers import (
    IBKRProvider,
    ManualSnapshotProvider,
    MoomooProvider,
    TigerProvider,
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
    as_of_date = config.as_of_date or datetime.now(timezone.utc).strftime("%Y%m%d")
    snapshots = collect_provider_snapshots(config)
    statuses = [snapshot.status for snapshot in snapshots]
    data_snapshots = [snapshot for snapshot in snapshots if snapshot.has_data()]
    normalized_assets = normalize_snapshots(data_snapshots)
    if not normalized_assets:
        return RunnerResult(
            exit_code=0,
            statuses=statuses,
            normalized_assets=[],
            output_dir=None,
            output_paths={},
        )

    risk_summary = calculate_risk_summary(
        normalized_assets,
        expected_provider_count=len(snapshots),
        as_of_date=as_of_date,
    )
    output_dir = config.output_dir or config.output_root / as_of_date
    output_paths = write_report_bundle(output_dir, statuses, normalized_assets, risk_summary)
    return RunnerResult(
        exit_code=0,
        statuses=statuses,
        normalized_assets=normalized_assets,
        output_dir=output_dir,
        output_paths=output_paths,
    )


def collect_provider_snapshots(config: RuntimeConfig) -> list[RawProviderSnapshot]:
    providers = [
        IBKRProvider(load_ibkr_config(config.env), allow_live_read=config.allow_live_read),
        MoomooProvider(load_moomoo_config(config.env), allow_live_read=config.allow_live_read),
        TigerProvider(load_tiger_config(config.env), allow_live_read=config.allow_live_read),
        ManualSnapshotProvider(
            load_manual_config(config.env, config.manual_snapshot_path),
            allow_live_read=False,
        ),
    ]
    return [provider.sync() for provider in providers]


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Personal CFO Agent v0.1 runner")
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
    if args.as_of_date is not None:
        _validate_as_of_date(args.as_of_date, parser)
    result = run(
        RuntimeConfig(
            allow_live_read=args.allow_live_read,
            manual_snapshot_path=args.manual_snapshot,
            output_root=args.output_root,
            output_dir=args.out_dir,
            as_of_date=args.as_of_date,
        )
    )
    if result.output_dir is None:
        print("No provider produced data; no reports generated.")
    else:
        print(f"Report bundle written to {result.output_dir}")
        print(f"Normalized ledger rows: {len(result.normalized_assets)}")
    return result.exit_code


def _validate_as_of_date(value: str, parser: argparse.ArgumentParser) -> None:
    try:
        datetime.strptime(value, "%Y%m%d")
    except ValueError:
        parser.error("--as-of-date must use YYYYMMDD")
