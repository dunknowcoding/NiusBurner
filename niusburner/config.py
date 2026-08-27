"""Per-user settings: where the tools are, when PATH is not the answer.

Copyright 2026 dunknowcoding (NiusRobotLab)
SPDX-License-Identifier: Apache-2.0

Nothing here is required. Auto-detection looks on PATH, then in the usual
install directories, then under the toolchain root named by EMBD_TOOLCHAINS.
This file exists for the machine where SDCC is somewhere else and the Arduino
IDE has no way to ask.

    python -m niusburner setup --sdcc "D:/tools/sdcc/bin/sdcc.exe"

Written to NIUSBURNER_CONFIG, or ~/.niusburner/config.json.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

ENV_VAR = "NIUSBURNER_CONFIG"
TOOLCHAIN_ROOT_VAR = "EMBD_TOOLCHAINS"


def config_path() -> Path:
    override = os.environ.get(ENV_VAR)
    if override:
        return Path(override).expanduser()
    return Path.home() / ".niusburner" / "config.json"


def load() -> dict:
    path = config_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def save(data: dict) -> Path:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n",
                    encoding="utf-8", newline="\n")
    return path


def sdcc_path() -> Path | None:
    """The recorded SDCC, if it is recorded and still there."""
    recorded = load().get("sdcc")
    if not recorded:
        return None
    path = Path(str(recorded)).expanduser()
    return path if path.is_file() else None


def set_sdcc(path: Path) -> Path:
    """Record an SDCC binary after checking it exists. Returns the config file."""
    resolved = Path(path).expanduser()
    if resolved.is_dir():
        for name in ("sdcc.exe", "sdcc"):
            candidate = resolved / name
            if candidate.is_file():
                resolved = candidate
                break
            candidate = resolved / "bin" / name
            if candidate.is_file():
                resolved = candidate
                break
    if not resolved.is_file():
        raise FileNotFoundError(
            f"no SDCC executable at {path}. Point --sdcc at sdcc.exe, at its "
            "bin directory, or at the SDCC install root.")
    data = load()
    data["sdcc"] = str(resolved.resolve())
    return save(data)


def toolchain_root() -> Path | None:
    """The caller-selected toolchain root, if EMBD_TOOLCHAINS names one."""
    root = os.environ.get(TOOLCHAIN_ROOT_VAR)
    if not root:
        return None
    path = Path(root).expanduser()
    return path if path.is_dir() else None


def describe() -> list[tuple[str, str]]:
    """(label, value) pairs for `niusburner setup` to print."""
    rows: list[tuple[str, str]] = []
    recorded = load().get("sdcc")
    rows.append(("config file", str(config_path())))
    rows.append(("sdcc (configured)", str(recorded) if recorded else "not set"))
    root = os.environ.get(TOOLCHAIN_ROOT_VAR)
    rows.append((f"{TOOLCHAIN_ROOT_VAR}", root or "not set"))
    return rows
