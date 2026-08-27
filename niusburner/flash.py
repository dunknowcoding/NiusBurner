"""Delegation boundary for physical programming and recovery.

Copyright 2026 dunknowcoding (NiusRobotLab)
SPDX-License-Identifier: Apache-2.0

This is the only place NiusBurner asks another process to touch silicon.

Preparing a HEX file is pure computation and safe to get wrong; driving 12 V
into a part is not. Probe identity, mutation, verification, recovery,
restoration and USB safety therefore belong to an external backend.

The backend is named by NIUSBURNER_BACKEND, or `niusprog` on PATH, or
``python -m niusburner.prog`` if neither is installed. The CLI stays headless.
"""

from __future__ import annotations

import os
import pathlib
import shutil
import subprocess
import sys


#: Overridable so a site can point at whatever backend it actually uses.
BACKEND_ENV = "NIUSBURNER_BACKEND"


def resolve_backend() -> list[str]:
    """Locate the programming backend as a command prefix.

    Prefers NIUSBURNER_BACKEND / niusprog on PATH. If neither is installed,
    falls back to ``python -m niusburner.prog`` so the CLI is self-contained.
    """
    configured = os.environ.get(BACKEND_ENV)
    if configured:
        path = pathlib.Path(configured).expanduser()
        if path.is_file():
            return [str(path)]
        raise FileNotFoundError(
            f"{BACKEND_ENV} is set to {configured!r}, which is not an existing "
            "executable")
    name = os.environ.get("NIUSBURNER_BACKEND_NAME", "niusprog")
    found = shutil.which(name) or shutil.which(name + ".cmd")
    if found:
        return [found]
    return [sys.executable, "-m", "niusburner.prog"]


def burn_command(*, target: str, image: pathlib.Path, confirm: str,
                 state_policy: str, address: int = 0,
                 config: pathlib.Path | None = None,
                 hold_reset: bool = False) -> list[str]:
    if not target or confirm != target:
        raise ValueError("confirm must exactly match target")
    if state_policy not in {"replace", "restore"}:
        raise ValueError("state policy must be replace or restore")
    if address < 0:
        raise ValueError("address must be non-negative")
    image = image.resolve(strict=True)
    command = list(resolve_backend())
    if config is not None:
        command += ["--config", str(config.resolve(strict=True))]
    if state_policy == "replace":
        command += ["burn", target, str(image), "--addr", hex(address),
                    "--confirm", target, "--ack-data-loss",
                    "--state-policy", "replace"]
        if hold_reset:
            command += ["--hold-reset"]
    else:
        if address:
            raise ValueError("restore uses a complete backup and no load address")
        command += ["recover", target, "--confirm", target,
                    "--ack-data-loss", "--state-policy", "restore",
                    "--backup", str(image)]
    return command


def reset_command(*, target: str, confirm: str) -> list[str]:
    if not target or confirm != target:
        raise ValueError("confirm must exactly match target")
    return list(resolve_backend()) + ["reset", target, "--confirm", confirm]


def reset(*, target: str, confirm: str) -> int:
    return subprocess.run(reset_command(target=target, confirm=confirm),
                          check=False).returncode


def probe_command(*, target: str, confirm: str) -> list[str]:
    if not target or confirm != target:
        raise ValueError("confirm must exactly match target")
    return list(resolve_backend()) + ["probe", target, "--confirm", confirm]


def probe(*, target: str, confirm: str) -> int:
    return subprocess.run(probe_command(target=target, confirm=confirm),
                          check=False).returncode


def burn(**kwargs) -> int:
    return subprocess.run(burn_command(**kwargs), check=False).returncode
