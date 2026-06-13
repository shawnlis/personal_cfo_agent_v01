"""Write Personal CFO Agent v0.1 report artifacts."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from personal_cfo_agent.asset_ledger import write_normalized_asset_ledger
from personal_cfo_agent.fire_engine import build_fire_snapshot
from personal_cfo_agent.models import NormalizedAsset, ProviderStatus, RiskSummary, WarningCode


DISCLAIMER = (
    "“This is a personal finance aggregation and risk dashboard, not investment, "
    "tax, estate, insurance, or trading advice.”"
)


def write_report_bundle(
    output_dir: Path,
    statuses: list[ProviderStatus],
    ledger_rows: list[NormalizedAsset],
    risk_summary: RiskSummary,
) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "markdown_report": output_dir / "PERSONAL_CFO_AGENT_V01.md",
        "provider_sync_summary": output_dir / "provider_sync_summary.json",
        "normalized_asset_ledger": output_dir / "normalized_asset_ledger.csv",
        "net_worth_summary": output_dir / "net_worth_summary.csv",
        "liquidity_summary": output_dir / "liquidity_summary.csv",
        "currency_exposure": output_dir / "currency_exposure.csv",
        "provider_warning_summary": output_dir / "provider_warning_summary.csv",
        "warnings_report": output_dir / "personal_cfo_warnings.md",
    }
    _write_provider_sync_summary(paths["provider_sync_summary"], statuses, ledger_rows)
    write_normalized_asset_ledger(paths["normalized_asset_ledger"], ledger_rows)
    _write_net_worth(paths["net_worth_summary"], risk_summary)
    _write_liquidity(paths["liquidity_summary"], risk_summary)
    _write_currency(paths["currency_exposure"], risk_summary)
    _write_provider_warnings(paths["provider_warning_summary"], statuses)
    _write_warnings_report(paths["warnings_report"], statuses, risk_summary)
    _write_markdown_report(paths["markdown_report"], statuses, ledger_rows, risk_summary)
    return paths


def _write_provider_sync_summary(
    path: Path, statuses: list[ProviderStatus], ledger_rows: list[NormalizedAsset]
) -> None:
    payload = {
        "disclaimer": DISCLAIMER,
        "provider_status": [status.to_dict() for status in statuses],
        "normalized_row_count": len(ledger_rows),
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _write_net_worth(path: Path, risk_summary: RiskSummary) -> None:
    _write_rows(
        path,
        ["metric", "value"],
        [
            {"metric": "total_assets", "value": f"{risk_summary.total_assets:.2f}"},
            {"metric": "total_liabilities", "value": f"{risk_summary.total_liabilities:.2f}"},
            {"metric": "net_worth", "value": f"{risk_summary.net_worth:.2f}"},
            {
                "metric": "provider_coverage_ratio",
                "value": f"{risk_summary.provider_coverage_ratio:.4f}",
            },
            {"metric": "manual_asset_share", "value": f"{risk_summary.manual_asset_share:.4f}"},
        ],
    )


def _write_liquidity(path: Path, risk_summary: RiskSummary) -> None:
    _write_rows(
        path,
        ["metric", "value"],
        [
            {"metric": "liquid_assets", "value": f"{risk_summary.liquid_assets:.2f}"},
            {"metric": "investable_assets", "value": f"{risk_summary.investable_assets:.2f}"},
        ],
    )


def _write_currency(path: Path, risk_summary: RiskSummary) -> None:
    rows = [
        {"currency": currency, "market_value": f"{value:.2f}"}
        for currency, value in sorted(risk_summary.currency_exposure.items())
    ]
    _write_rows(path, ["currency", "market_value"], rows)


def _write_provider_warnings(path: Path, statuses: list[ProviderStatus]) -> None:
    rows: list[dict[str, str]] = []
    for status in statuses:
        if not status.warning_codes:
            rows.append({"provider": status.provider_name, "warning_code": ""})
            continue
        for code in status.warning_codes:
            rows.append({"provider": status.provider_name, "warning_code": code.value})
    _write_rows(path, ["provider", "warning_code"], rows)


def _write_warnings_report(
    path: Path, statuses: list[ProviderStatus], risk_summary: RiskSummary
) -> None:
    lines = ["# Personal CFO Warnings", "", DISCLAIMER, "", "## Provider Warnings"]
    for status in statuses:
        codes = ", ".join(code.value for code in status.warning_codes) or "None"
        lines.append(f"- {status.provider_name}: {codes}")
    lines.extend(["", "## Risk Warnings"])
    if risk_summary.warning_codes:
        for code in risk_summary.warning_codes:
            lines.append(f"- {code.value}")
    else:
        lines.append("- None")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_markdown_report(
    path: Path,
    statuses: list[ProviderStatus],
    ledger_rows: list[NormalizedAsset],
    risk_summary: RiskSummary,
) -> None:
    fire_snapshot = build_fire_snapshot(risk_summary)
    manual_rows = [row for row in ledger_rows if row.provider == "manual_snapshot"]
    disabled_or_empty = [
        status.provider_name
        for status in statuses
        if not status.last_sync_time and status.provider_name != "manual_snapshot"
    ]
    lines = [
        "# Personal CFO Agent v0.1",
        "",
        DISCLAIMER,
        "",
        "## Provider sync status",
    ]
    for status in statuses:
        codes = ", ".join(code.value for code in status.warning_codes) or "None"
        lines.append(
            f"- {status.provider_name}: {status.connection_mode.value}; "
            f"read_only={str(status.read_only).lower()}; warnings={codes}"
        )

    lines.extend(
        [
            "",
            "## Asset summary",
            f"- Normalized ledger rows: {len(ledger_rows)}",
            f"- Manual snapshot rows: {len(manual_rows)}",
            "",
            "## Net worth summary",
            f"- Total assets: {risk_summary.total_assets:.2f}",
            f"- Total liabilities: {risk_summary.total_liabilities:.2f}",
            f"- Net worth: {risk_summary.net_worth:.2f}",
            "",
            "## Liquidity summary",
            f"- Liquid assets: {risk_summary.liquid_assets:.2f}",
            f"- Investable assets: {risk_summary.investable_assets:.2f}",
            f"- FIRE snapshot: {fire_snapshot.notes}",
            "",
            "## Currency exposure",
        ]
    )
    for currency, value in sorted(risk_summary.currency_exposure.items()):
        lines.append(f"- {currency}: {value:.2f}")

    lines.extend(["", "## Manual snapshot gaps"])
    if disabled_or_empty:
        for provider_name in disabled_or_empty:
            lines.append(f"- {provider_name}: manual snapshot or future connector proof required")
    else:
        lines.append("- None")

    lines.extend(["", "## Warning summary"])
    all_codes = [code.value for code in risk_summary.warning_codes]
    if all_codes:
        for code in all_codes:
            lines.append(f"- {code}")
    else:
        lines.append("- None")

    lines.extend(
        [
            "",
            "## Next manual actions",
            "- Refresh unsupported-provider snapshots only through approved manual exports.",
            "- Review stale or missing-value rows before relying on dashboard totals.",
            "",
            "## Safety boundaries",
            "- No trading, account-write, cash-movement, browser-session, identity-login, scraping, recommendation, tax, estate, or insurance workflow is implemented.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_rows(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
