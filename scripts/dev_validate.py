"""Cross-platform repository validation for Personal CFO Agent."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACKAGE_DIRS = [
    ROOT / "src" / "personal_cfo_agent",
    ROOT / "src" / "personal_cfo_agent" / "providers",
    ROOT / "src" / "personal_cfo_agent" / "manual_snapshot",
    ROOT / "src" / "personal_cfo_agent" / "dashboard",
]
SCRIPT_FILES = [
    ROOT / "scripts" / "personal_cfo_agent.py",
    ROOT / "scripts" / "run_ibkr_readonly_sync.py",
]


def main() -> int:
    for directory in PACKAGE_DIRS:
        if directory.exists():
            for path in sorted(directory.glob("*.py")):
                _run([sys.executable, "-m", "py_compile", str(path)])
    for path in SCRIPT_FILES:
        if path.exists():
            _run([sys.executable, "-m", "py_compile", str(path)])
    _run([sys.executable, "-m", "pytest"])
    return 0


def _run(command: list[str]) -> None:
    display = " ".join(_display_part(part) for part in command)
    print(f"$ {display}", flush=True)
    subprocess.run(command, cwd=ROOT, check=True)


def _display_part(part: str) -> str:
    try:
        return str(Path(part).relative_to(ROOT))
    except ValueError:
        return part


if __name__ == "__main__":
    raise SystemExit(main())
