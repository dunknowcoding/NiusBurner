"""Arduino IDE board package install and recipe host. No hardware."""

from __future__ import annotations

import pathlib

from niusburner import ide


def test_install_arduino_platform_copies_board_package(tmp_path: pathlib.Path):
    book = tmp_path / "Arduino"
    dest = ide.install_arduino_platform(book)
    assert dest == book / "hardware" / "niusrobotlab" / "mcs51"
    assert (dest / "boards.txt").is_file()
    assert (dest / "platform.txt").is_file()
    assert (dest / "tools" / "nb_host.py").is_file()
    python_path = (dest / "tools" / "python.path").read_text(encoding="utf-8").strip()
    assert python_path
    assert "at89s52" in (dest / "boards.txt").read_text(encoding="utf-8")


def test_arduino_host_dummy_o_and_hex(tmp_path: pathlib.Path):
    obj = tmp_path / "nested" / "unit.o"
    assert ide.arduino_main(["dummy-o", str(obj)]) == 0
    assert obj.is_file()
    build = tmp_path / "build"
    build.mkdir()
    (build / "firmware.ihx").write_text(":00000001FF\n", encoding="ascii")
    assert ide.arduino_main(["hex", str(build), "blink"]) == 0
    assert (build / "blink.hex").is_file()
