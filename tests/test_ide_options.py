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


def test_boards_txt_is_generated_from_the_catalog_and_is_current():
    """The committed file and the catalog drifted once; they cannot again.

    A part added to boards.json used to be compilable from the command line
    and simply absent from the IDE menu, with nothing to say so.
    """
    from niusburner.ide import render_boards_txt

    committed = (PLATFORM / "boards.txt").read_text(encoding="utf-8")
    assert committed == render_boards_txt(), (
        "boards.txt is stale: run `python -m niusburner setup`")


def test_boards_txt_offers_every_catalog_board_with_safe_defaults():
    text = (PLATFORM / "boards.txt").read_text(encoding="utf-8")
    from niusburner import boards as boards_mod

    for board_id, board in boards_mod.all_boards().items():
        if board.family != "mcs51":
            continue          # each family has its own board package
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
    # stdout, not stderr: the IDE panel renders stderr red and can double it.
    captured = capsys.readouterr()
    assert "usbasp" in captured.out
    assert captured.err == ""


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
    bar = Progress("Programming", 1000, stream=out)
    for _ in range(1000):
        bar.step()
    bar.done()
    text = out.getvalue()
    lines = text.splitlines()
    assert "\r" not in text
    # One line per 10% plus the start and the summary, not one per byte.
    assert len(lines) <= 14
    assert "100%" in text
    # Every line is the house bar: two spaces, NIUS, the comet, a percent.
    assert all(line.startswith("  NIUS  ") for line in lines)
    assert all("%" in line for line in lines)


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
    assert "FAILED" in text
    assert "target went away" in text


# ------------------------------------------------------------ house style --

def test_banner_is_bracketed_by_the_only_star_rules():
    """The *** rules belong to the banner alone; a failure block uses dashes."""
    from niusburner import progress

    out = io.StringIO()
    progress.banner("8051 Flash Console - Target: at89s52", stream=out)
    lines = out.getvalue().splitlines()
    assert lines[0] == progress.BANNER_RULE
    assert lines[-3] == progress.BANNER_RULE
    assert lines[-2].strip() == "8051 Flash Console - Target: at89s52"
    assert all(line.startswith("*") for line in (lines[0], lines[-3]))


def test_the_bar_is_a_comet_on_a_dotted_track_without_brackets():
    from niusburner.progress import _bar

    assert _bar(0) == "." * 22
    assert _bar(100) == "=" * 22
    middle = _bar(50)
    assert middle.endswith(".")
    assert ">" in middle
    assert len(middle) == 22
    # Upstream's bar carries no bracket decorations at all.
    assert "[" not in middle and "]" not in middle


def test_everything_the_ide_reads_goes_to_stdout(capsys):
    """Arduino IDE 2 renders stderr red and can print it twice."""
    from niusburner import progress

    progress.banner("test", stream=None)
    progress.stage(50, "Programming", "1/2 B")
    progress.info("a line the operator sees")
    progress.error("something went wrong", title="failed",
                   hints=("try this",), details=("trace line",))
    progress.complete("Upload complete", "Soft reset        : done")
    captured = capsys.readouterr()
    assert captured.err == ""
    assert "NIUS" in captured.out
    assert "[nius][fail]" in captured.out
    assert " reason: something went wrong" in captured.out
    assert "  - try this" in captured.out
    assert "  > trace line" in captured.out


def test_internal_detail_lines_are_quiet_unless_asked_for(capsys, monkeypatch):
    from niusburner import progress

    monkeypatch.delenv("NIUSBURNER_VERBOSE", raising=False)
    progress.note("port resolution detail")
    assert capsys.readouterr().out == ""

    monkeypatch.setenv("NIUSBURNER_VERBOSE", "1")
    progress.note("port resolution detail")
    assert "[nius] port resolution detail" in capsys.readouterr().out


# ------------------------------------------------------- programmer routes --

def test_the_programmer_and_port_reach_the_backend_command(tmp_path):
    """A part with a serial bootloader has to be told which adapter it is on."""
    from niusburner import flash

    image = tmp_path / "firmware.ihx"
    image.write_text(":00000001FF\n", encoding="ascii")
    cmd = flash.burn_command(
        target="stc89c52rc", image=image, confirm="stc89c52rc",
        state_policy="replace", programmer="stcgal", port="COM33")
    assert "--programmer" in cmd and "stcgal" in cmd
    assert "--port" in cmd and "COM33" in cmd


def test_the_isp_route_carries_no_port():
    from niusburner import flash

    cmd = flash.probe_command(target="at89s52", confirm="at89s52",
                              programmer="usbisp_hid")
    assert "--port" not in cmd


def test_every_catalogued_programmer_is_either_driven_or_named(tmp_path):
    """A board is flashable when its programmer has a backend, not when a
    status field says so."""
    from niusburner import boards as boards_mod

    for board in boards_mod.all_boards().values():
        assert board.flashable == (board.programmer in board.DRIVEN)


def test_a_serial_bootloader_board_asks_the_ide_for_a_port():
    """Arduino only offers the port picker when the board requires one."""
    text = (PLATFORM / "boards.txt").read_text(encoding="utf-8")
    assert "stc89c52rc.upload.require_upload_port=true" in text
    assert "at89s52.upload.require_upload_port=false" in text


def test_menu_applies_follows_the_programmer():
    """A Tools menu is only offered where the board can act on it."""
    from niusburner import boards as boards_mod
    from niusburner.ide import _menu_applies

    stc = boards_mod.get_board("stc89c52rc")
    at89 = boards_mod.get_board("at89s52")
    pic = boards_mod.get_board("pic16f877a")

    # Rebooting into a bootloader, and switching a rail to reach one, are
    # bootloader-part ideas.
    assert _menu_applies("entry", stc) and not _menu_applies("entry", at89)
    assert not _menu_applies("entry", pic)
    assert _menu_applies("reset", stc) and not _menu_applies("reset", pic)
    # The debug configuration bits exist only on the PIC parts.
    assert _menu_applies("icd", pic) and not _menu_applies("icd", stc)
    # Everything else is offered everywhere.
    for board in (stc, at89, pic):
        assert _menu_applies("optimize", board)


def test_on_chip_debug_is_refused_off_pic16(tmp_path):
    """The option sets PIC configuration bits; nothing else has them."""
    import pytest
    from niusburner import workflow

    sketch = tmp_path / "s"
    sketch.mkdir()
    (sketch / "s.ino").write_text("void setup(){} void loop(){}\n")
    plan = workflow.plan_compile(sketch, "stc89c52rc", output=tmp_path / "o")
    with pytest.raises(ValueError, match="PIC16 feature"):
        workflow.compile_plan(plan, tmp_path / "o", icd=True)
