from __future__ import annotations

import json
import pathlib

import pytest

from niusburner import debugger
from niusburner.package import package_image, verify_package


def test_package_is_reproducible_and_host_neutral(tmp_path: pathlib.Path):
    source = tmp_path / "firmware.bin"
    source.write_bytes(b"firmware")
    manifest = package_image(source, tmp_path / "out", target="example-target",
                             load_address=0x1000)
    first = manifest.read_bytes()
    assert verify_package(manifest)["target"] == "example-target"
    package_image(source, tmp_path / "out", target="example-target",
                  load_address=0x1000)
    assert manifest.read_bytes() == first
    assert str(tmp_path) not in first.decode()


def test_package_rejects_tampering(tmp_path: pathlib.Path):
    source = tmp_path / "firmware.bin"
    source.write_bytes(b"firmware")
    manifest = package_image(source, tmp_path / "out", target="example-target")
    (manifest.parent / "firmware.bin").write_bytes(b"changed")
    with pytest.raises(ValueError, match="digest|size"):
        verify_package(manifest)


def test_debug_mutation_delegates_to_the_backend(monkeypatch, tmp_path: pathlib.Path):
    image = tmp_path / "image.bin"
    image.write_bytes(b"x")
    tool = tmp_path / "niusprog"
    tool.write_text("placeholder", encoding="utf-8")
    monkeypatch.setenv("NIUSBURNER_BACKEND", str(tool))
    cmd = debugger.burn_command(target="target-a", image=image,
                                confirm="target-a", state_policy="replace")
    assert cmd[0] == str(tool)
    assert cmd[1:3] == ["burn", "target-a"]
    assert "--ack-data-loss" in cmd


def test_debug_delegation_fails_closed_on_identity_mismatch(
        monkeypatch, tmp_path: pathlib.Path):
    image = tmp_path / "image.bin"
    image.write_bytes(b"x")
    with pytest.raises(ValueError, match="exactly match"):
        debugger.burn_command(target="target-a", image=image,
                              confirm="target-b", state_policy="replace")


def test_restore_delegates_to_recover_with_backup(monkeypatch,
                                                  tmp_path: pathlib.Path):
    backup = tmp_path / "backup.bin"
    backup.write_bytes(b"saved")
    tool = tmp_path / "niusprog"
    tool.write_text("placeholder", encoding="utf-8")
    monkeypatch.setenv("NIUSBURNER_BACKEND", str(tool))
    cmd = debugger.burn_command(target="target-a", image=backup,
                                confirm="target-a", state_policy="restore")
    assert cmd[1:3] == ["recover", "target-a"]
    assert cmd[-2:] == ["--backup", str(backup.resolve())]
