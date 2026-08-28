"""Arduino IDE board package install and recipe host. No hardware."""

from __future__ import annotations

import pathlib

from niusburner import ide


def test_install_arduino_platform_copies_every_board_package(tmp_path):
    """One package per architecture: the IDE keys its toolchain off that name."""
    book = tmp_path / "Arduino"
    vendor = ide.install_arduino_platform(book)
    assert vendor == book / "hardware" / "niusrobotlab"

    for architecture in ide.ARCHITECTURES:
        dest = vendor / architecture
        assert (dest / "boards.txt").is_file(), architecture
        assert (dest / "platform.txt").is_file(), architecture
        assert (dest / "tools" / "nb_host.py").is_file(), architecture
        recorded = (dest / "tools" / "python.path").read_text(
            encoding="utf-8").strip()
        assert recorded, architecture

    boards_8051 = (vendor / "mcs51" / "boards.txt").read_text(encoding="utf-8")
    boards_pic = (vendor / "pic16" / "boards.txt").read_text(encoding="utf-8")
    assert "at89s52" in boards_8051
    assert "pic16f877a" in boards_pic
    # A part belongs to exactly one package, or the IDE offers it twice.
    assert "pic16f877a" not in boards_8051
    assert "at89s52" not in boards_pic


def test_arduino_host_dummy_o_and_hex(tmp_path: pathlib.Path):
    obj = tmp_path / "nested" / "unit.o"
    assert ide.arduino_main(["dummy-o", str(obj)]) == 0
    assert obj.is_file()
    build = tmp_path / "build"
    build.mkdir()
    (build / "firmware.ihx").write_text(":00000001FF\n", encoding="ascii")
    assert ide.arduino_main(["hex", str(build), "blink"]) == 0
    assert (build / "blink.hex").is_file()
