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


#: Tools a person can pin by hand, and what each one is.
TOOLS = {
    "sdcc": "the SDCC driver, for 8051 boards",
    "xc8": "the XC8 driver (xc8-cc), for PIC boards",
    "xc16": "the XC16 driver (xc16-gcc), for 16-bit PIC boards",
    "pickit3": "ipecmd, the command-line programmer that drives a PICkit 3",
}


def tool_path(name: str) -> Path | None:
    """The recorded path for *name*, if it is recorded and still there."""
    recorded = load().get(name)
    if not recorded:
        return None
    path = Path(str(recorded)).expanduser()
    return path if path.is_file() else None


def set_tool(name: str, path: Path) -> Path:
    """Record a tool after checking it exists. Returns the config file.

    A directory is accepted and searched, because the thing a person has to
    hand is usually the install root rather than the executable inside it.
    """
    if name not in TOOLS:
        raise ValueError(
            f"unknown tool {name!r}. Known: {', '.join(sorted(TOOLS))}.")
    resolved = Path(path).expanduser()
    if resolved.is_dir():
        resolved = _find_in(resolved, name) or resolved
    if not resolved.is_file():
        raise FileNotFoundError(
            f"no {name} executable at {path}. Point --{name} at the program "
            "itself, at its bin directory, or at the install root.")
    data = load()
    data[name] = str(resolved.resolve())
    return save(data)


#: What each tool's executable is called, most specific first.
_NAMES = {
    "sdcc": ("sdcc.exe", "sdcc"),
    "xc8": ("xc8-cc.exe", "xc8-cc"),
    "xc16": ("xc16-gcc.exe", "xc16-gcc"),
    "pickit3": ("ipecmd.exe", "ipecmd", "ipecmd.jar"),
}


def _find_in(root: Path, name: str) -> Path | None:
    """Look for a tool under *root*: beside it, in bin/, then one level down."""
    for leaf in _NAMES[name]:
        for candidate in (root / leaf, root / "bin" / leaf):
            if candidate.is_file():
                return candidate
    for child in sorted(root.iterdir(), reverse=True):
        if not child.is_dir():
            continue
        for leaf in _NAMES[name]:
            for candidate in (child / leaf, child / "bin" / leaf):
                if candidate.is_file():
                    return candidate
    return None


def sdcc_path() -> Path | None:
    """The recorded SDCC, if it is recorded and still there."""
    return tool_path("sdcc")


def set_sdcc(path: Path) -> Path:
    """Record an SDCC binary after checking it exists."""
    return set_tool("sdcc", path)


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
    rows.append(("config file", str(config_path())))
    data = load()
    for name, what in sorted(TOOLS.items()):
        value = data.get(name)
        rows.append((f"{name} (configured)",
                     str(value) if value else f"not set -- {what}"))
    root = os.environ.get(TOOLCHAIN_ROOT_VAR)
    rows.append((f"{TOOLCHAIN_ROOT_VAR}", root or "not set"))
    return rows
