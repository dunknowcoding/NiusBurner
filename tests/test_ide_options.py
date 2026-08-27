"""Board-menu options, compiler resolution and progress output.

Copyright 2026 dunknowcoding (NiusRobotLab)
SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

import io
import pathlib

import pytest

from niusburner import build, config, ide

ROOT = pathlib.Path(__file__).resolve().parents[1]
PLATFORM = ROOT / "niusburner" / "arduino" / "mcs51"


# ------------------------------------------------------------ board menus --

def test_menu_values_fall_back_to_the_documented_default():
    assert ide._menu("speed", ("size", "speed", "none"), "size") == "speed"
    # The IDE sends an empty string when a menu has no value.
    assert ide._menu("", ("size", "speed", "none"), "size") == "size"
    assert ide._menu(None, ("size", "speed", "none"), "size") == "size"
    assert ide._menu("nonsense", ("size", "speed", "none"), "size") == "size"


def test_boards_txt_offers_every_catalog_board_with_safe_defaults():
    text = (PLATFORM / "boards.txt").read_text(encoding="utf-8")
    from niusburner import boards as boards_mod

    for board_id in boards_mod.all_boards():
        assert f"{board_id}.name=" in text, f"{board_id} is missing from boards.txt"
        assert f"{board_id}.build.nb_board={board_id}" in text
        # Size and no debug info are the defaults every board must agree on.
        assert f"{board_id}.menu.optimize.size.build.nb_optimize=size" in text
        assert f"{board_id}.menu.debug.none.build.nb_debug=none" in text
        assert f"{board_id}.menu.compiler.auto.build.nb_compiler=auto" in text


def test_platform_txt_passes_the_menu_choices_to_the_host():
    text = (PLATFORM / "platform.txt").read_text(encoding="utf-8")
    assert "{build.nb_optimize}" in text
    assert "{build.nb_debug}" in text
    assert "{build.nb_compiler}" in text
    assert "{program.nb_programmer}" in text
    # Defaults must exist so a stale IDE preference cannot expand to nothing.
    assert "build.nb_optimize=size" in text
    assert "build.nb_debug=none" in text
    assert "build.nb_compiler=auto" in text


def test_programmers_txt_lists_the_verified_one_first():
    lines = (PLATFORM / "programmers.txt").read_text(encoding="utf-8").splitlines()
    names = [line.split(".", 1)[0] for line in lines if ".name=" in line]
    assert names[0] == "usbisp_hid"
    assert "usbasp" in names


def test_wrong_programmer_is_reported_before_anything_is_erased(tmp_path, capsys):
    image = tmp_path / "firmware.hex"
    image.write_text(":00000001FF\n", encoding="ascii")
    rc = ide.cmd_flash(image, "at89s52", programmer="usbasp")
    assert rc == 1
    assert "usbasp" in capsys.readouterr().err


# ------------------------------------------------------- compiler location --

def test_configured_compiler_is_required_when_the_menu_asks_for_it(monkeypatch):
    monkeypatch.setattr(config, "sdcc_path", lambda: None)
    with pytest.raises(ValueError) as exc:
        ide.resolve_compiler("configured")
    assert "setup --sdcc" in str(exc.value)


def test_auto_leaves_the_choice_to_detection(monkeypatch):
    monkeypatch.setattr(config, "sdcc_path", lambda: pathlib.Path("/nope/sdcc"))
    assert ide.resolve_compiler("auto") is None


def test_recorded_compiler_wins_over_path(tmp_path, monkeypatch):
    fake = tmp_path / "sdcc.exe"
    fake.write_bytes(b"")
    monkeypatch.setenv(config.ENV_VAR, str(tmp_path / "config.json"))
    config.set_sdcc(fake)
    assert build.find_sdcc() == fake.resolve()


def test_set_sdcc_accepts_an_install_root(tmp_path, monkeypatch):
    binary = tmp_path / "bin" / "sdcc.exe"
    binary.parent.mkdir()
    binary.write_bytes(b"")
    monkeypatch.setenv(config.ENV_VAR, str(tmp_path / "config.json"))
    config.set_sdcc(tmp_path)
    assert config.sdcc_path() == binary.resolve()


def test_set_sdcc_refuses_a_path_with_no_compiler(tmp_path, monkeypatch):
    monkeypatch.setenv(config.ENV_VAR, str(tmp_path / "config.json"))
    with pytest.raises(FileNotFoundError):
        config.set_sdcc(tmp_path / "nothing")


# ---------------------------------------------------------------- progress --

def test_progress_prints_whole_steps_when_the_stream_is_not_a_terminal():
    """The Arduino console renders \\r as a newline, so never emit one per byte."""
    from niusburner.progress import Progress

    out = io.StringIO()
    bar = Progress("write", 1000, stream=out)
    for _ in range(1000):
        bar.step()
    bar.done()
    text = out.getvalue()
    assert "\r" not in text
    # One line per 5% plus the start and the summary, not one per byte.
    assert len(text.splitlines()) <= 25
    assert "100.0%" in text
    assert "done" in text


def test_progress_reports_an_eta_once_it_has_something_to_go_on():
    from niusburner.progress import Progress, human_time

    out = io.StringIO()
    bar = Progress("write", 100, stream=out)
    bar.step(50)
    assert "ETA" in out.getvalue()
    assert human_time(65) == "01:05"
    assert human_time(float("nan")) == "--:--"
    bar.done()


def test_progress_failure_is_visible_and_closes_the_phase():
    from niusburner.progress import Progress

    out = io.StringIO()
    with pytest.raises(RuntimeError):
        with Progress("write", 10, stream=out):
            raise RuntimeError("target went away")
    text = out.getvalue()
    assert "failed" in text
    assert "target went away" in text
