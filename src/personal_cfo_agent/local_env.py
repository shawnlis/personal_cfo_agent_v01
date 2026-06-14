"""Project-local .env.local loading with OS environment precedence."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import MutableMapping


LOCAL_ENV_FILENAME = ".env.local"
_KEY_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@dataclass(frozen=True)
class LocalEnvLoadResult:
    path: Path
    exists: bool
    loaded_keys: tuple[str, ...] = ()
    skipped_existing_keys: tuple[str, ...] = ()
    ignored_lines: tuple[int, ...] = ()


def load_local_env_file(
    path: Path | None = None,
    environ: MutableMapping[str, str] | None = None,
) -> LocalEnvLoadResult:
    """Load project-local env values without overriding existing OS variables."""

    env_path = path or Path(LOCAL_ENV_FILENAME)
    target = environ if environ is not None else os.environ
    if not env_path.exists():
        return LocalEnvLoadResult(path=env_path, exists=False)

    loaded: list[str] = []
    skipped: list[str] = []
    ignored: list[int] = []
    for line_number, raw_line in enumerate(
        env_path.read_text(encoding="utf-8-sig").splitlines(), 1
    ):
        parsed = _parse_env_line(raw_line)
        if parsed is None:
            stripped = raw_line.strip()
            if stripped and not stripped.startswith("#"):
                ignored.append(line_number)
            continue
        key, value = parsed
        if key in target:
            skipped.append(key)
            continue
        target[key] = value
        loaded.append(key)

    return LocalEnvLoadResult(
        path=env_path,
        exists=True,
        loaded_keys=tuple(loaded),
        skipped_existing_keys=tuple(skipped),
        ignored_lines=tuple(ignored),
    )


def _parse_env_line(raw_line: str) -> tuple[str, str] | None:
    line = raw_line.strip()
    if not line or line.startswith("#"):
        return None
    if line.startswith("export "):
        line = line[len("export ") :].strip()
    if "=" not in line:
        return None
    key, value = line.split("=", 1)
    key = key.strip()
    if not _KEY_PATTERN.fullmatch(key):
        return None
    return key, _strip_value(value.strip())


def _strip_value(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value
