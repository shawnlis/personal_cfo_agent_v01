from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_root_readme_documents_current_v06_workflow() -> None:
    text = (ROOT / "README.md").read_text(encoding="utf-8")

    for marker in (
        "--init-private-input-center",
        "--private-input-center-form",
        "--validate-private-input-center",
        "--run-net-worth-refresh",
        "--refresh-brokers none",
        "--allow-live-read",
        "--dashboard-v4",
        "--net-worth-doctor",
    ):
        assert marker in text
    assert "v0.6.x" in text
    assert "Manual-only mode does not run broker reads." in text


def test_repo_agents_file_captures_project_safety_boundaries() -> None:
    text = (ROOT / "AGENTS.md").read_text(encoding="utf-8")

    assert "Do not print, commit, or stage `.env.local`" in text
    assert "Do not run broker live reads" in text
    assert "Manual-only refresh must use no external provider reads." in text
    assert "NEXT_CHAT_HANDOFF_2026-06-15.md" in text
    assert "reports/" in text


def test_legacy_v01_doc_is_marked_historical() -> None:
    text = (ROOT / "docs" / "PERSONAL_CFO_AGENT_V01.md").read_text(encoding="utf-8")

    assert "historical v0.1 project note" in text
    assert "v0.6.x local-first Personal CFO workflow" in text
    assert "--net-worth-doctor" in text
    assert "v0.1 Connector Roadmap" not in text


def test_operating_docs_have_no_private_values_or_secret_like_examples() -> None:
    for path in (
        ROOT / "README.md",
        ROOT / "AGENTS.md",
        ROOT / "docs" / "PERSONAL_CFO_AGENT_V01.md",
    ):
        text = path.read_text(encoding="utf-8")
        assert "9876543.21" not in text
        assert "7,931,561" not in text
        assert "AKIA" not in text
        assert "-----BEGIN" not in text
        assert re.search(r"(?im)^\s*token\s*=\s*\S+", text) is None
        assert re.search(r"(?im)^\s*password\s*=\s*\S+", text) is None
