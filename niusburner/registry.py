"""Find out what is actually installed, rather than what is supposed to be.

Copyright 2026 dunknowcoding (NiusRobotLab)
SPDX-License-Identifier: Apache-2.0

Every entry in toolchains.json carries a `detect` rule, and this module runs
it. That is the whole point of the file: a path in a config is a claim, and a
claim that a compiler exists is worth nothing when the usual failure is a
half-finished install that left the directory behind but not the binary.

Three detection forms, in the order they are cheapest:

    cmd   run it and match its output   -- proves it runs, not merely exists
    path  an exact file                 -- for tools that are not on PATH
    glob  a versioned directory         -- Microchip installs as xc8/2.46/...

`cmd` is preferred wherever a tool has a --version, because it is the only one
that distinguishes "installed" from "present but broken".
"""

from __future__ import annotations

import glob as _glob
import json
import os
import pathlib
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Any

HERE = pathlib.Path(__file__).parent
REGISTRY_PATH = HERE / "toolchains.json"


@dataclass
class Found:
    """The result of probing one entry."""

    name: str
    kind: str                    # "compiler" or "programmer"
    present: bool
    where: str = ""
    version: str = ""
    reason: str = ""             # why it was not found, when it was not
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def status(self) -> str:
        return "ready" if self.present else "missing"


def load_registry(path: pathlib.Path | None = None) -> dict[str, Any]:
    with open(path or REGISTRY_PATH, "r", encoding="utf-8") as fh:
        registry = json.load(fh)

    default_root = pathlib.Path(registry.get("root", "~/.local/share/niusburner/toolchains"))
    root = pathlib.Path(os.environ.get("EMBD_TOOLCHAINS", default_root)).expanduser()

    def expand(value: Any) -> Any:
        if isinstance(value, str):
            return os.path.expandvars(
                value.replace("${EMBD_TOOLCHAINS}", str(root)))
        if isinstance(value, list):
            return [expand(item) for item in value]
        if isinstance(value, dict):
            return {key: expand(item) for key, item in value.items()}
        return value

    registry = expand(registry)
    registry["root"] = str(root)
    return registry


def _first_line(text: str) -> str:
    for line in text.splitlines():
        line = line.strip()
        if line:
            return line
    return ""


def _probe_cmd(rule: dict[str, Any]) -> tuple[bool, str, str, str]:
    """Run a command and match its output."""
    exe = shutil.which(rule["cmd"])
    if not exe:
        return False, "", "", f"{rule['cmd']} is not on PATH"

    try:
        proc = subprocess.run(
            [exe, *rule.get("args", [])],
            capture_output=True, text=True, timeout=20,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return False, exe, "", f"{rule['cmd']} found but would not run: {exc}"

    # Several of these write their banner to stderr, so both are considered.
    out = (proc.stdout or "") + (proc.stderr or "")
    want = rule.get("match", "")
    if want and want.lower() not in out.lower():
        return False, exe, "", (
            f"{rule['cmd']} ran but did not identify itself as {want!r} -- "
            "a different tool of the same name is ahead on PATH"
        )
    return True, exe, _first_line(out), ""


def _probe_path(rule: dict[str, Any]) -> tuple[bool, str, str, str]:
    p = pathlib.Path(rule["path"])
    if p.is_file():
        return True, str(p), "", ""
    return False, "", "", f"not present at {p}"


def _probe_glob(rule: dict[str, Any]) -> tuple[bool, str, str, str]:
    hits = sorted(_glob.glob(rule["glob"]))
    if not hits:
        return False, "", "", f"nothing matched {rule['glob']}"
    # Highest version last once sorted, which is what a user expects to get.
    chosen = hits[-1]
    extra = ""
    if len(hits) > 1:
        extra = f"{len(hits)} versions installed; using the newest"
    return True, chosen, "", extra


def probe(entry: dict[str, Any]) -> tuple[bool, str, str, str]:
    rule = entry.get("detect")
    if not rule:
        return False, "", "", "no detection rule; presence cannot be confirmed"
    if "cmd" in rule:
        return _probe_cmd(rule)
    if "path" in rule:
        return _probe_path(rule)
    if "glob" in rule:
        return _probe_glob(rule)
    return False, "", "", "detection rule has no cmd, path or glob"


def scan(registry: dict[str, Any] | None = None) -> list[Found]:
    """Probe every compiler and programmer in the registry."""
    reg = registry if registry is not None else load_registry()
    results: list[Found] = []

    for kind, section in (("compiler", "compilers"), ("programmer", "programmers")):
        for name, entry in reg.get(section, {}).items():
            ok, where, version, reason = probe(entry)
            results.append(Found(
                name=name, kind=kind, present=ok, where=where,
                version=version, reason=reason, meta=entry,
            ))
    return results


def toolchain_root(registry: dict[str, Any] | None = None) -> pathlib.Path:
    reg = registry if registry is not None else load_registry()
    return pathlib.Path(reg["root"]).expanduser()


def for_family(family: str, registry: dict[str, Any] | None = None) -> list[Found]:
    """Every compiler that claims to build for `family`."""
    return [f for f in scan(registry)
            if f.kind == "compiler" and family in f.meta.get("family", [])]


def programmers_for(part: str, registry: dict[str, Any] | None = None) -> list[Found]:
    """
    Every programmer that can write `part`.

    Returns all of them rather than picking one. An STC89C52RC can be done over
    SPI ISP with a USB-ISP *or* through the serial bootloader, and which is
    right depends on how the board is wired -- so the choice belongs to whoever
    can see the bench.
    """
    part = part.lower()
    return [f for f in scan(registry)
            if f.kind == "programmer"
            and part in [p.lower() for p in f.meta.get("programs", [])]]
