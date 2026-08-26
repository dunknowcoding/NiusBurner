"""Workflow: boards, sketches, NiusDisplay source picking. No hardware."""

from __future__ import annotations

import pathlib

import pytest

from niusburner import boards, display, sketch, workflow
from niusburner.__main__ import main


ROOT = pathlib.Path(__file__).resolve().parents[1]


def _fake_sdcc(monkeypatch, tmp_path: pathlib.Path, program_bytes: int = 200):
    from niusburner import build

    compiler = tmp_path / "sdcc.exe"
    compiler.write_bytes(b"")

    def fake_run(command: list[str], cwd: pathlib.Path) -> str:
        if "--version" in command:
            return "SDCC 4.5.0 #15242\n"
        output = command[command.index("-o") + 1]
        if "-c" in command:
            (cwd / output).write_text("object", encoding="ascii")
            (cwd / pathlib.Path(output).with_suffix(".asm")).write_text(
                "; asm\n", encoding="ascii")
        else:
            (cwd / "firmware.ihx").write_text(":00000001FF\n", encoding="ascii")
            (cwd / "firmware.map").write_text("map\n", encoding="ascii")
            (cwd / "firmware.mem").write_text(
                f"ROM/EPROM/FLASH  0x0000 0x02b5 {program_bytes} 8192\n",
                encoding="ascii")
        return ""

    monkeypatch.setattr(build, "_run", fake_run)
    monkeypatch.setattr(build, "find_sdcc", lambda: compiler)
    return compiler


def _niusdisplay_tree(tmp_path: pathlib.Path) -> pathlib.Path:
    root = tmp_path / "NiusDisplay"
    (root / "src" / "compat").mkdir(parents=True)
    (root / "src" / "core").mkdir(parents=True)
    (root / "src" / "panels" / "led").mkdir(parents=True)
    (root / "src" / "panels" / "color").mkdir(parents=True)
    (root / "ports" / "8051-sdcc").mkdir(parents=True)
    (root / "src" / "NiusDisplay.h").write_text("/* C++ facade */\n", encoding="utf-8")
    (root / "src" / "compat" / "NiusDuino.h").write_text(
        "void setup(void); void loop(void);\n", encoding="utf-8")
    (root / "src" / "compat" / "NiusDuino.c").write_text(
        "#include \"NiusDuino.h\"\n#ifdef ND_NIUSDUINO_MAIN\nint main(void) { setup(); for (;;) loop(); }\n#endif\n",
        encoding="utf-8")
    (root / "ports" / "8051-sdcc" / "nd_hal_8051.c").write_text(
        "void nd_hal_gpio_write(int pin, int v) { (void)pin; (void)v; }\n",
        encoding="utf-8")
    (root / "src" / "panels" / "led" / "nd_tm1637.h").write_text(
        "#include \"nd_hal.h\"\n", encoding="utf-8")
    (root / "src" / "panels" / "led" / "nd_tm1637.c").write_text(
        "#include \"nd_tm1637.h\"\nvoid nd_tm1637_init(void) {}\n",
        encoding="utf-8")
    (root / "src" / "core" / "nd_hal.h").write_text("/* hal */\n", encoding="utf-8")
    (root / "src" / "panels" / "color" / "nd_st7789.h").write_text(
        "/* tft */\n", encoding="utf-8")
    (root / "src" / "panels" / "color" / "nd_st7789.c").write_text(
        "#include \"nd_st7789.h\"\nvoid nd_st7789_init(void) {}\n",
        encoding="utf-8")
    (root / "src" / "core" / "nd_gfx.c").write_text("void nd_gfx_init(void) {}\n",
                                                   encoding="utf-8")
    return root


def test_boards_lists_at89s52():
    board = boards.get_board("AT89S52")
    assert board.id == "at89s52"
    assert board.code_size == 8192
    assert board.programmer == "usbisp_hid"
    assert board.flashable


def test_unknown_board_names_the_catalog():
    with pytest.raises(KeyError, match="at89s52"):
        boards.get_board("not-a-chip")


def test_gpio_ino_is_c_shaped(tmp_path: pathlib.Path):
    sketch_dir = tmp_path / "blink"
    sketch_dir.mkdir()
    (sketch_dir / "blink.ino").write_text(
        "void setup(void) { pinMode(0, OUTPUT); }\n"
        "void loop(void) { digitalWrite(0, HIGH); delay(200); }\n",
        encoding="utf-8")
    sk = sketch.resolve_sketch(sketch_dir)
    assert sk.has_setup_loop
    assert sketch.cxx_reason(sk.text) is None
    assert not sketch.uses_niusdisplay(sk)


def test_arduino_cpp_sketch_is_refused(tmp_path: pathlib.Path):
    sketch_dir = tmp_path / "clock"
    sketch_dir.mkdir()
    (sketch_dir / "clock.ino").write_text(
        "#include <NiusDisplay.h>\n"
        "NiusSegment seg(4, 5, 4);\n"
        "void setup() { Serial.begin(115200); seg.begin(); }\n"
        "void loop() { seg.showTime(12, 0, true); }\n",
        encoding="utf-8")
    with pytest.raises(ValueError, match="C\\+\\+|NiusDisplay"):
        workflow.plan_compile(sketch_dir, "at89s52")


def test_lone_c_file_does_not_pull_sibling_demos(tmp_path: pathlib.Path):
    port = tmp_path / "ports" / "8051-sdcc"
    port.mkdir(parents=True)
    (port / "demo.c").write_text("int main(void) { return 0; }\n", encoding="utf-8")
    (port / "other.c").write_text("int unused(void) { return 1; }\n", encoding="utf-8")
    sk = sketch.resolve_sketch(port / "demo.c")
    assert sk.extra_c == ()


def test_sketch_directory_includes_sibling_c(tmp_path: pathlib.Path):
    d = tmp_path / "app"
    d.mkdir()
    (d / "app.ino").write_text(
        "void helper(void);\nvoid setup(void) { helper(); }\nvoid loop(void) {}\n",
        encoding="utf-8")
    (d / "helper.c").write_text("void helper(void) {}\n", encoding="utf-8")
    sk = sketch.resolve_sketch(d)
    assert [p.name for p in sk.extra_c] == ["helper.c"]


def test_niusdisplay_tm1637_sources(tmp_path: pathlib.Path):
    lib = _niusdisplay_tree(tmp_path)
    sketch_dir = tmp_path / "clock"
    sketch_dir.mkdir()
    (sketch_dir / "clock.ino").write_text(
        "#include \"NiusDuino.h\"\n"
        "#include \"nd_tm1637.h\"\n"
        "void setup(void) { nd_tm1637_init(); }\n"
        "void loop(void) {}\n",
        encoding="utf-8")
    sk = sketch.resolve_sketch(sketch_dir)
    collected = display.collect_for_sketch(lib, sk)
    stems = {p.stem for p in collected.sources}
    assert "nd_tm1637" in stems
    assert "nd_hal_8051" in stems
    assert "NiusDuino" in stems
    assert "nd_st7789" not in stems
    assert not collected.needs_xram


def test_graphics_without_xram_is_refused(tmp_path: pathlib.Path):
    lib = _niusdisplay_tree(tmp_path)
    sketch_dir = tmp_path / "tft"
    sketch_dir.mkdir()
    (sketch_dir / "tft.ino").write_text(
        "#include \"NiusDuino.h\"\n"
        "#include \"nd_st7789.h\"\n"
        "void setup(void) { nd_st7789_init(); }\n"
        "void loop(void) {}\n",
        encoding="utf-8")
    with pytest.raises(ValueError, match="XRAM"):
        workflow.plan_compile(sketch_dir, "at89s52", library=lib)


def test_compile_gpio_ino_with_fake_sdcc(tmp_path: pathlib.Path, monkeypatch):
    _fake_sdcc(monkeypatch, tmp_path)
    sketch_dir = tmp_path / "blink"
    sketch_dir.mkdir()
    (sketch_dir / "blink.ino").write_text(
        "void setup(void) { pinMode(0, OUTPUT); }\n"
        "void loop(void) { digitalWrite(0, HIGH); delay(1); }\n",
        encoding="utf-8")
    plan = workflow.plan_compile(sketch_dir, "at89s52")
    assert plan.runtime == "sketch"
    result = workflow.compile_plan(plan, tmp_path / "out")
    assert result.program_bytes == 200
    assert (tmp_path / "out" / "firmware.ihx").is_file()


def test_cli_boards_and_compile_refuse_without_yes(tmp_path, monkeypatch, capsys):
    _fake_sdcc(monkeypatch, tmp_path)
    sketch_dir = tmp_path / "blink"
    sketch_dir.mkdir()
    (sketch_dir / "blink.ino").write_text(
        "void setup(void) { pinMode(0, OUTPUT); }\nvoid loop(void) {}\n",
        encoding="utf-8")
    assert main(["boards"]) == 0
    out = capsys.readouterr().out
    assert "at89s52" in out
    assert main(["compile", str(sketch_dir), "--board", "at89s52",
                 "--output", str(tmp_path / "out")]) == 0
    rc = main(["upload", str(sketch_dir), "--board", "at89s52",
               "--output", str(tmp_path / "out2")])
    assert rc == 2
    err = capsys.readouterr().err
    assert "--yes" in err


def test_example_blink_resolves():
    path = ROOT / "examples" / "at89s52_blink"
    sk = sketch.resolve_sketch(path)
    assert sk.has_setup_loop
    assert sketch.cxx_reason(sk.text) is None
    plan = workflow.plan_compile(path, "at89s52")
    assert plan.runtime == "sketch"
    assert plan.board.id == "at89s52"
