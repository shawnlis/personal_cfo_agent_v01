from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from personal_cfo_agent.config import RuntimeConfig
from personal_cfo_agent.local_env import load_local_env_file
from personal_cfo_agent.models import ConnectionMode, WarningCode
from personal_cfo_agent.runner import collect_provider_snapshots


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "personal_cfo_agent.py"


def test_local_env_loader_loads_missing_keys(tmp_path) -> None:
    env_file = tmp_path / ".env.local"
    env_file.write_text(
        "\n".join(
            [
                "CFO_IBKR_ENABLED=true",
                "CFO_IBKR_HOST=127.0.0.1",
                "CFO_IBKR_PORT=7497",
                "CFO_IBKR_CLIENT_ID=101",
            ]
        ),
        encoding="utf-8",
    )
    env: dict[str, str] = {}

    result = load_local_env_file(env_file, env)

    assert result.exists is True
    assert set(result.loaded_keys) == {
        "CFO_IBKR_ENABLED",
        "CFO_IBKR_HOST",
        "CFO_IBKR_PORT",
        "CFO_IBKR_CLIENT_ID",
    }
    assert env["CFO_IBKR_ENABLED"] == "true"
    assert env["CFO_IBKR_HOST"] == "127.0.0.1"


def test_local_env_loader_accepts_utf8_bom(tmp_path) -> None:
    env_file = tmp_path / ".env.local"
    env_file.write_text(
        "\ufeffCFO_IBKR_ENABLED=true\nCFO_IBKR_HOST=127.0.0.1\n",
        encoding="utf-8",
    )
    env: dict[str, str] = {}

    result = load_local_env_file(env_file, env)

    assert result.ignored_lines == ()
    assert env["CFO_IBKR_ENABLED"] == "true"
    assert env["CFO_IBKR_HOST"] == "127.0.0.1"


def test_os_environment_values_override_local_env(tmp_path) -> None:
    env_file = tmp_path / ".env.local"
    env_file.write_text(
        "\n".join(
            [
                "CFO_IBKR_HOST=127.0.0.1",
                "CFO_IBKR_PORT=7497",
            ]
        ),
        encoding="utf-8",
    )
    env = {"CFO_IBKR_HOST": "192.0.2.10"}

    result = load_local_env_file(env_file, env)

    assert env["CFO_IBKR_HOST"] == "192.0.2.10"
    assert env["CFO_IBKR_PORT"] == "7497"
    assert result.skipped_existing_keys == ("CFO_IBKR_HOST",)
    assert result.loaded_keys == ("CFO_IBKR_PORT",)


def test_loading_local_env_does_not_attempt_live_read_without_flag(tmp_path) -> None:
    env_file = tmp_path / ".env.local"
    env_file.write_text(
        "\n".join(
            [
                "CFO_IBKR_ENABLED=true",
                "CFO_IBKR_HOST=127.0.0.1",
                "CFO_IBKR_PORT=7497",
                "CFO_IBKR_CLIENT_ID=101",
            ]
        ),
        encoding="utf-8",
    )
    env: dict[str, str] = {}
    load_local_env_file(env_file, env)

    snapshot = collect_provider_snapshots(
        RuntimeConfig(env=env, provider="ibkr", allow_live_read=False)
    )[0]

    assert snapshot.status.connection_mode == ConnectionMode.API_STUB
    assert WarningCode.LIVE_READ_NOT_ALLOWED in snapshot.status.warning_codes
    assert not snapshot.has_data()


def test_cli_readiness_uses_local_env_without_printing_raw_values(tmp_path) -> None:
    env_file = tmp_path / ".env.local"
    env_file.write_text(
        "\n".join(
            [
                "CFO_IBKR_ENABLED=true",
                "CFO_IBKR_HOST=198.51.100.44",
                "CFO_IBKR_PORT=4002",
                "CFO_IBKR_CLIENT_ID=7331",
            ]
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--provider",
            "ibkr",
            "--readiness-check",
        ],
        cwd=tmp_path,
        env=_without_cfo_env(),
        capture_output=True,
        text=True,
        check=False,
    )

    combined = result.stdout + result.stderr
    assert result.returncode == 0
    assert "Loaded local environment from .env.local; values redacted" in result.stdout
    assert "ibkr: api_contract_stub; warnings=None" in result.stdout
    assert "198.51.100.44" not in combined
    assert "4002" not in combined
    assert "7331" not in combined


def test_local_env_is_ignored_and_example_is_not_ignored() -> None:
    assert _git_returncode("check-ignore", "-q", ".env.local") == 0
    assert _git_returncode("check-ignore", "-q", ".env.example") != 0


def test_env_example_contains_placeholders_only() -> None:
    text = (ROOT / ".env.example").read_text(encoding="utf-8")
    assert "CFO_IBKR_ENABLED=false" in text
    assert "CFO_IBKR_ACCOUNT=\n" in text
    assert "CFO_ACCOUNT_HASH_SALT=\n" in text
    assert "CFO_TIGER_ACCOUNT=\n" in text
    assert "password=" not in text.lower()
    assert "private_key=" not in text.lower()
    assert "token=" not in text.lower()


def _without_cfo_env() -> dict[str, str]:
    return {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("CFO_IBKR_")
        and not key.startswith("CFO_MOOMOO_")
        and not key.startswith("CFO_TIGER_")
        and key != "CFO_ACCOUNT_HASH_SALT"
    }


def _git_returncode(*args: str) -> int:
    return subprocess.run(["git", *args], cwd=ROOT, check=False).returncode
