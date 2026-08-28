"""Host-only guards for the STC UART backend."""

from __future__ import annotations

import subprocess
from types import SimpleNamespace

import pytest

from niusburner.backends import stc_uart


def identity(port="COM31", vid=0x1A86, pid=0x5523, location="1-7.3.1:x.0"):
    return (port, vid, pid, "", location, f"USB VID:PID={vid:04X}:{pid:04X}")


def test_guarded_stcgal_run_requires_same_uart_after_success(monkeypatch):
    snapshots = iter((identity(), identity()))
    monkeypatch.setattr(stc_uart, "serial_identity", lambda _port: next(snapshots))
    called = {}

    def run(command, **kwargs):
        called.update(kwargs)
        return subprocess.CompletedProcess(command, 0, "ok", "")

    monkeypatch.setattr(stc_uart.subprocess, "run", run)
    result = stc_uart._run_guarded(["stcgal"], "COM31")
    assert result.returncode == 0
    assert called["timeout"] == stc_uart.PROCESS_TIMEOUT_SECONDS


def test_guarded_stcgal_run_rejects_uart_identity_drift(monkeypatch):
    snapshots = iter((identity(), identity(location="different")))
    monkeypatch.setattr(stc_uart, "serial_identity", lambda _port: next(snapshots))
    monkeypatch.setattr(
        stc_uart.subprocess, "run",
        lambda command, **kwargs: subprocess.CompletedProcess(command, 0, "", ""),
    )
    with pytest.raises(RuntimeError, match="identity changed"):
        stc_uart._run_guarded(["stcgal"], "COM31")


def test_guarded_stcgal_run_checks_uart_after_process_failure(monkeypatch):
    snapshots = iter((identity(), identity()))
    monkeypatch.setattr(stc_uart, "serial_identity", lambda _port: next(snapshots))

    def fail(_command, **_kwargs):
        raise subprocess.TimeoutExpired("stcgal", 120)

    monkeypatch.setattr(stc_uart.subprocess, "run", fail)
    with pytest.raises(subprocess.TimeoutExpired):
        stc_uart._run_guarded(["stcgal"], "COM31")


def test_serial_identity_rejects_ambiguous_exact_port(monkeypatch):
    fake = SimpleNamespace(
        device="COM31", vid=0x1A86, pid=0x5523, serial_number=None,
        location="1-7.3.1:x.0", hwid="USB VID:PID=1A86:5523",
    )
    import serial.tools.list_ports
    monkeypatch.setattr(serial.tools.list_ports, "comports", lambda: [fake, fake])
    with pytest.raises(RuntimeError, match="found 2"):
        stc_uart.serial_identity("COM31")
