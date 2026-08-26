from __future__ import annotations

import pathlib

import pytest

from niusburner import flash


def test_burn_delegates_to_the_backend(monkeypatch, tmp_path: pathlib.Path):
    image = tmp_path / "image.bin"
    image.write_bytes(b"x")
    tool = tmp_path / "niusprog"
    tool.write_text("placeholder", encoding="utf-8")
    monkeypatch.setenv("NIUSBURNER_BACKEND", str(tool))
    cmd = flash.burn_command(target="target-a", image=image,
                             confirm="target-a", state_policy="replace")
    assert cmd[0] == str(tool)
    assert cmd[1:3] == ["burn", "target-a"]
    assert "--ack-data-loss" in cmd


def test_burn_fails_closed_on_identity_mismatch(tmp_path: pathlib.Path):
    image = tmp_path / "image.bin"
    image.write_bytes(b"x")
    with pytest.raises(ValueError, match="exactly match"):
        flash.burn_command(target="target-a", image=image,
                           confirm="target-b", state_policy="replace")


def test_restore_delegates_to_recover_with_backup(monkeypatch,
                                                  tmp_path: pathlib.Path):
    backup = tmp_path / "backup.bin"
    backup.write_bytes(b"saved")
    tool = tmp_path / "niusprog"
    tool.write_text("placeholder", encoding="utf-8")
    monkeypatch.setenv("NIUSBURNER_BACKEND", str(tool))
    cmd = flash.burn_command(target="target-a", image=backup,
                             confirm="target-a", state_policy="restore")
    assert cmd[1:3] == ["recover", "target-a"]
    assert cmd[-2:] == ["--backup", str(backup.resolve())]


def test_falls_back_to_python_module(monkeypatch, tmp_path: pathlib.Path):
    image = tmp_path / "image.bin"
    image.write_bytes(b"x")
    monkeypatch.delenv("NIUSBURNER_BACKEND", raising=False)
    monkeypatch.setattr(flash.shutil, "which", lambda *_: None)
    cmd = flash.burn_command(target="target-a", image=image,
                             confirm="target-a", state_policy="replace")
    assert cmd[:3] == [flash.sys.executable, "-m", "niusburner.prog"]
    assert cmd[3:5] == ["burn", "target-a"]


def test_probe_command_matches_confirm(monkeypatch, tmp_path: pathlib.Path):
    tool = tmp_path / "niusprog"
    tool.write_text("x", encoding="utf-8")
    monkeypatch.setenv("NIUSBURNER_BACKEND", str(tool))
    cmd = flash.probe_command(target="at89s52", confirm="at89s52")
    assert cmd[0] == str(tool)
    assert cmd[1:] == ["probe", "at89s52", "--confirm", "at89s52"]
    with pytest.raises(ValueError, match="exactly match"):
        flash.probe_command(target="at89s52", confirm="other")
