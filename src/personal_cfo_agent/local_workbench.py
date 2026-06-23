"""Static local workbench launcher for the Personal CFO workflow."""

from __future__ import annotations

import html
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from personal_cfo_agent.models import WarningCode


SCHEMA_VERSION = "v0.6.6"
SUMMARY_NAME = "local_workbench_summary.json"
HTML_NAME = "LOCAL_WORKBENCH_V066.html"
REPORT_NAME = "LOCAL_WORKBENCH_V066.md"


@dataclass(frozen=True)
class LocalWorkbenchResult:
    output_dir: Path
    output_paths: dict[str, Path] = field(default_factory=dict)
    generated: bool = False
    warning_codes: list[WarningCode] = field(default_factory=list)


def write_local_workbench(
    *,
    out_dir: Path,
    input_file: Path | None = None,
    refresh_dir: Path | None = None,
    fx_rates_file: Path | None = None,
    dashboard_dir: Path | None = None,
) -> LocalWorkbenchResult:
    """Write a static local launcher without reading private values."""

    input_file = input_file or Path("private_inputs/personal_cfo_input.local.json")
    refresh_dir = refresh_dir or Path("reports/personal_cfo_agent/net_worth_refresh_local")
    fx_rates_file = fx_rates_file or Path("private_inputs/fx_rates.local.json")
    dashboard_dir = dashboard_dir or Path("reports/personal_cfo_agent/dashboard_current")
    out_dir.mkdir(parents=True, exist_ok=True)
    artifacts = {
        "input_file_present": input_file.exists(),
        "refresh_dir_present": refresh_dir.exists(),
        "fx_rates_file_present": fx_rates_file.exists(),
        "dashboard_html_present": (dashboard_dir / "PERSONAL_CFO_DASHBOARD_V060.html").exists(),
        "snapshot_review_html_present": (refresh_dir / "snapshot_review" / "snapshot_review.html").exists(),
        "doctor_summary_present": (refresh_dir.parent / "net_worth_doctor_v062_local" / "net_worth_doctor_summary.json").exists(),
    }
    warnings = []
    if not artifacts["input_file_present"]:
        warnings.append(WarningCode.LOCAL_WORKBENCH_INPUT_MISSING)
    if not artifacts["refresh_dir_present"]:
        warnings.append(WarningCode.LOCAL_WORKBENCH_REFRESH_MISSING)
    if not artifacts["fx_rates_file_present"]:
        warnings.append(WarningCode.LOCAL_WORKBENCH_FX_MISSING)
    warnings.append(
        WarningCode.LOCAL_WORKBENCH_GENERATED_WITH_WARNINGS
        if warnings
        else WarningCode.LOCAL_WORKBENCH_GENERATED_OK
    )
    output_paths = {
        "summary": out_dir / SUMMARY_NAME,
        "html": out_dir / HTML_NAME,
        "report": out_dir / REPORT_NAME,
    }
    summary: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "redacted": True,
        "external_connections_used": False,
        "broker_live_reads_used": False,
        "input_file": str(input_file),
        "refresh_dir": str(refresh_dir),
        "fx_rates_file": str(fx_rates_file),
        "dashboard_dir": str(dashboard_dir),
        "artifacts": artifacts,
        "warning_codes": [code.value for code in warnings],
    }
    output_paths["summary"].write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    markdown = _markdown(summary)
    output_paths["report"].write_text(markdown, encoding="utf-8")
    output_paths["html"].write_text(_html(markdown, summary), encoding="utf-8")
    return LocalWorkbenchResult(
        output_dir=out_dir,
        output_paths=output_paths,
        generated=True,
        warning_codes=warnings,
    )


def _markdown(summary: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# Personal CFO Local Workbench v0.6.6",
            "",
            "Static local launcher. It does not run broker reads or upload data.",
            "",
            "## Current Local Paths",
            "",
            f"- Private input file: `{summary['input_file']}`",
            f"- Refresh directory: `{summary['refresh_dir']}`",
            f"- FX rates file: `{summary['fx_rates_file']}`",
            f"- Dashboard directory: `{summary['dashboard_dir']}`",
            "",
            "## Safe Commands",
            "",
            "- Start editable input center:",
            "  `python .\\scripts\\personal_cfo_agent.py --private-input-center-local-app --input-file .\\private_inputs\\personal_cfo_input.local.json`",
            "- Manual-only refresh:",
            "  `python .\\scripts\\personal_cfo_agent.py --run-net-worth-refresh --refresh-brokers none --input-file .\\private_inputs\\personal_cfo_input.local.json --out-dir .\\reports\\personal_cfo_agent\\net_worth_refresh_local`",
            "- Dashboard v4:",
            "  `python .\\scripts\\personal_cfo_agent.py --dashboard-v4 --refresh-dir .\\reports\\personal_cfo_agent\\net_worth_refresh_local --fx-rates-file .\\private_inputs\\fx_rates.local.json --out-dir .\\reports\\personal_cfo_agent\\dashboard_v4_local`",
            "- Doctor:",
            "  `python .\\scripts\\personal_cfo_agent.py --net-worth-doctor --input-file .\\private_inputs\\personal_cfo_input.local.json --refresh-dir .\\reports\\personal_cfo_agent\\net_worth_refresh_local --fx-rates-file .\\private_inputs\\fx_rates.local.json --out-dir .\\reports\\personal_cfo_agent\\net_worth_doctor_v062_local`",
            "",
            "## Warning Codes",
            "",
            *[f"- `{code}`" for code in summary["warning_codes"]],
        ]
    ) + "\n"


def _html(markdown: str, summary: dict[str, Any]) -> str:
    blocks: list[str] = []
    for line in markdown.splitlines():
        if line.startswith("# "):
            blocks.append(f"<h1>{html.escape(line[2:])}</h1>")
        elif line.startswith("## "):
            blocks.append(f"<h2>{html.escape(line[3:])}</h2>")
        elif line.startswith("- "):
            blocks.append(f"<p class=\"bullet\">{html.escape(line[2:])}</p>")
        elif line.startswith("  `"):
            blocks.append(f"<pre>{html.escape(line.strip().strip('`'))}</pre>")
        elif line:
            blocks.append(f"<p>{html.escape(line)}</p>")
    dashboard_link = _file_link(
        Path(str(summary["dashboard_dir"])) / "PERSONAL_CFO_DASHBOARD_V060.html"
    )
    review_link = _file_link(
        Path(str(summary["refresh_dir"])) / "snapshot_review" / "snapshot_review.html"
    )
    if dashboard_link:
        blocks.append(f"<p class=\"action\"><a href=\"{dashboard_link}\">Open current Dashboard v4</a></p>")
    if review_link:
        blocks.append(f"<p class=\"action\"><a href=\"{review_link}\">Open snapshot review</a></p>")
    return (
        "<!doctype html>\n<html><head><meta charset=\"utf-8\">"
        "<title>Personal CFO Local Workbench</title><style>"
        "body{margin:0;background:#fbfaf7;color:#16202a;font-family:Segoe UI,Arial,sans-serif;}"
        "main{max-width:980px;margin:0 auto;padding:42px 28px 68px;}"
        "h1{font-size:34px;margin:0 0 18px;}h2{font-size:20px;margin:30px 0 12px;padding-top:18px;border-top:1px solid #d8dedb;}"
        ".bullet,.action{background:#fff;border:1px solid #d8dedb;border-radius:8px;padding:10px 12px;color:#16202a;}"
        "a{color:#0f766e;font-weight:700;text-decoration:none;}pre{white-space:pre-wrap;background:#16202a;color:#fff;border-radius:8px;padding:12px;}"
        "</style></head><body><main>"
        + "\n".join(blocks)
        + "</main></body></html>\n"
    )


def _file_link(path: Path) -> str:
    if not path.exists():
        return ""
    return path.resolve().as_uri()
