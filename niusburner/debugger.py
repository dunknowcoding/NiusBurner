"""Delegation boundary for physical programming and recovery.

NiusBurner prepares images and stops there. Everything that touches real
hardware -- probe identity, device mutation, verification, recovery,
restoration and USB safety -- belongs to an external programming backend, and
this module is the whole of the interface to it.

The split is deliberate. Preparing a HEX file is pure computation and safe to
get wrong; driving 12 V into a part is not, and the two should not live in the
same process or be reviewed to the same standard.

The backend is named by the NIUSBURNER_BACKEND environment variable, or found
on PATH. It is not hardcoded: which programmer is correct depends on the bench,
and a tool that assumes one is a tool that fights the user who has another.
"""

from __future__ import annotations

import os
import pathlib
import shutil
import subprocess


#: Overridable so a site can point at whatever backend it actually uses.
BACKEND_ENV = "NIUSBURNER_BACKEND"


def resolve_backend() -> str:
    """Locate the external programming backend, or explain what is missing."""
    configured = os.environ.get(BACKEND_ENV)
    if configured:
        path = pathlib.Path(configured).expanduser()
        if path.is_file():
            return str(path)
        raise FileNotFoundError(
            f"{BACKEND_ENV} is set to {configured!r}, which is not an existing "
            "executable")
    name = os.environ.get("NIUSBURNER_BACKEND_NAME", "niusprog")
    found = shutil.which(name) or shutil.which(name + ".cmd")
    if not found:
        raise FileNotFoundError(
            f"no programming backend found: {name!r} is not on PATH. "
            f"Set {BACKEND_ENV} to the executable that drives your programmer.")
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
