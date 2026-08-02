"""Delegation boundary for physical programming and recovery.

NiusBurner prepares images. an external programming backend owns probe identity, mutation,
verification, recovery, restoration, and USB safety.
"""

from __future__ import annotations

import os
import pathlib
import shutil
import subprocess


def resolve_backend() -> str:
    configured = os.environ.get("NIUSBURNER_BACKEND")
    if configured:
        path = pathlib.Path(configured).expanduser()
        if path.is_file():
            return str(path)
        raise FileNotFoundError("NIUSBURNER_BACKEND does not name an existing executable")
    found = shutil.which("niusprog") or shutil.which("niusprog.cmd")
    if not found:
        raise FileNotFoundError("niusprog is not on PATH; install an external programming backend")
    return found


def burn_command(*, target: str, image: pathlib.Path, confirm: str,
                 state_policy: str, address: int = 0,
                 config: pathlib.Path | None = None) -> list[str]:
    if not target or confirm != target:
        raise ValueError("confirm must exactly match target")
    if state_policy not in {"replace", "restore"}:
        raise ValueError("state policy must be replace or restore")
    if address < 0:
        raise ValueError("address must be non-negative")
    image = image.resolve(strict=True)
    command = [resolve_backend()]
    if config is not None:
        command += ["--config", str(config.resolve(strict=True))]
    if state_policy == "replace":
        command += ["burn", target, str(image), "--addr", hex(address),
                    "--confirm", target, "--ack-data-loss",
                    "--state-policy", "replace"]
    else:
        if address:
            raise ValueError("restore uses a complete backup and no load address")
        command += ["recover", target, "--confirm", target,
                    "--ack-data-loss", "--state-policy", "restore",
                    "--backup", str(image)]
    return command


def burn(**kwargs) -> int:
    return subprocess.run(burn_command(**kwargs), check=False).returncode
