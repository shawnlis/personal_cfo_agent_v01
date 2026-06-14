from __future__ import annotations

import re
from pathlib import Path

from personal_cfo_agent.config import connector_status


ROOT = Path(__file__).resolve().parents[1]


FORBIDDEN_IMPORT_OR_CALL_MARKERS = [
    r"\bselenium\b",
    r"\bplaywright\b",
    r"\bpyautogui\b",
    r"cpf\.gov\.sg",
    r"iras\.gov\.sg",
    r"\bplaceOrder\b",
    r"\bplace_order\b",
    r"\bsubmit_order\b",
    r"\bmodify_order\b",
    r"\bcancel_order\b",
    r"\bpreview_order\b",
    r"\btransfer_cash\b",
    r"\bwithdraw_cash\b",
    r"\bbuy\b",
    r"\bsell\b",
    r"\btrade\b",
    r"\broll\b",
    r"\bopen_position\b",
    r"\bclose_position\b",
]

SECRET_PATTERNS = [
    r"AKIA[0-9A-Z]{16}",
    r"gh[opsu]_[A-Za-z0-9_]{20,}",
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
    r"xox[baprs]-[A-Za-z0-9-]{20,}",
]


def test_provider_source_has_no_forbidden_operational_imports_or_calls() -> None:
    for path in _source_files():
        text = path.read_text(encoding="utf-8")
        for pattern in FORBIDDEN_IMPORT_OR_CALL_MARKERS:
            assert re.search(pattern, text, flags=re.IGNORECASE) is None, path


def test_unsupported_connectors_are_blocked() -> None:
    webull = connector_status("webull")
    poems = connector_status("poems")
    assert webull["status"] == "unsupported_until_official_api_verified"
    assert "UNOFFICIAL_API_BLOCKED" in webull["warning_codes"]
    assert poems["status"] == "unsupported_until_official_api_verified"
    assert "UNOFFICIAL_API_BLOCKED" in poems["warning_codes"]


def test_government_sources_are_manual_or_sgfindex_only() -> None:
    for name in ("cpf", "iras", "hdb"):
        status = connector_status(name)
        assert status["status"] == "indirect_via_sgfindex_or_manual_snapshot"
        assert status["implementation_priority"] == "manual_only"


def test_security_boundary_docs_cover_browser_identity_and_advice_limits() -> None:
    text = (ROOT / "docs" / "SECURITY_BOUNDARIES.md").read_text(encoding="utf-8")
    assert "No browser automation." in text
    assert "No Singpass automation." in text
    assert "No recommendation output." in text
    assert "No buy/sell/hold advice." in text
    assert "No AI PM Agent import path." in text


def test_secret_looking_values_are_not_committed() -> None:
    for path in _repo_text_files():
        text = path.read_text(encoding="utf-8")
        for pattern in SECRET_PATTERNS:
            assert re.search(pattern, text) is None, path


def test_generated_outputs_stay_under_ignored_reports_path() -> None:
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "reports/" in gitignore


def _source_files() -> list[Path]:
    return [
        *sorted((ROOT / "src" / "personal_cfo_agent").rglob("*.py")),
        *sorted((ROOT / "scripts").rglob("*.py")),
    ]


def _repo_text_files() -> list[Path]:
    ignored_parts = {".git", "__pycache__", ".pytest_cache", "reports"}
    files: list[Path] = []
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        if any(part in ignored_parts for part in path.parts):
            continue
        if path.suffix.lower() in {".py", ".md", ".toml", ".json", ".txt", ".csv"}:
            files.append(path)
    return files
