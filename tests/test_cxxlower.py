"""BASIC Arduino C++ → C lowerer. No hardware."""

from __future__ import annotations

import pathlib

import pytest

from niusburner import cxxlower, sketch, workflow
from niusburner.__main__ import main
from niusburner.cxxlower import CxxLowerError, lower_text


ROOT = pathlib.Path(__file__).resolve().parents[1]
NIUSDISPLAY = ROOT.parent / "NiusDisplay"
OFFICIAL_TM1637 = (
    NIUSDISPLAY / "examples" / "tm1637_clock_basic" / "tm1637_clock_basic.ino"
)
OFFICIAL_HD44780 = (
    NIUSDISPLAY / "examples" / "hd44780_menu_adv" / "hd44780_menu_adv.ino"
)
EXAMPLE_HD44780 = ROOT / "examples" / "niusdisplay_hd44780"
EXAMPLE_MAX7219 = ROOT / "examples" / "niusdisplay_max7219"

BASIC = """\
#include <NiusDisplay.h>

#define CLK_PIN 4
#define DIO_PIN 5

NiusSegment seg(CLK_PIN, DIO_PIN, 4);

void setup() {
  Serial.begin(115200);

  if (!seg.begin()) {
    Serial.println(F("TM1637 did not acknowledge"));
    while (1) delay(1000);
  }

  seg.setLevel(3);
}

void loop() {
  static uint8_t hh = 12, mm = 0;
  static bool colon = true;

  seg.showTime(hh, mm, colon);
  colon = !colon;
  delay(500);

  if (!colon) {
    if (++mm >= 60) { mm = 0; if (++hh >= 24) hh = 0; }
  }
}
"""


def test_lower_basic_niussegment():
    out = lower_text(BASIC)
    code = cxxlower._code_words(out)
    assert "NiusSegment" not in code
    assert "NiusDisplay.h" not in out
    assert '#include "NiusDuino.h"' in out
    assert '#include "nd_tm1637.h"' in out
    assert "static nd_tm1637 seg;" in out
    assert "nd_tm1637_init(&seg, CLK_PIN, DIO_PIN, 4)" in out
    assert "nd_tm1637_show_time(&seg, hh, mm, colon)" in out
    assert "nd_tm1637_brightness(&seg, 3)" in out
    assert "Serial" not in cxxlower._code_words(out)
    assert "nius_serial_begin(115200)" in out
    assert "nius_serial_println_s" in out
    assert "F(" not in cxxlower._code_words(out)
    assert "void setup(void)" in out
    assert "void loop(void)" in out
    assert "unsigned char hh" in out
    assert sketch.cxx_reason(out) is None


def test_lower_maps_serial_to_uart():
    src = (
        '#include <Arduino.h>\n'
        "void setup() { Serial.begin(9600); pinMode(0, OUTPUT); }\n"
        'void loop() { Serial.println(F("hi")); digitalWrite(0, HIGH); }\n'
    )
    out = lower_text(src)
    assert "NiusDuino.h" not in out
    assert "Arduino.h" not in out
    assert "nius_serial_begin(9600)" in out
    assert 'nius_serial_println_s("hi")' in out
    assert '#include "nius_serial.h"' in out
    assert "F(" not in cxxlower._code_words(out)
    assert sketch.cxx_reason(out) is None


def test_lower_refuses_niustft():
    src = (
        "#include <NiusDisplay.h>\n"
        "NiusTFT tft(ND_MOD_ST7789_240X240_1IN3, 5, 2, 4);\n"
        "void setup() { tft.begin(); }\n"
        "void loop() {}\n"
    )
    with pytest.raises(CxxLowerError, match="NiusTFT"):
        lower_text(src)


def test_lower_refuses_class_and_string():
    with pytest.raises(CxxLowerError, match="class"):
        lower_text("class Foo {}; void setup() {} void loop() {}\n")
    with pytest.raises(CxxLowerError, match="String"):
        lower_text("String s = \"x\"; void setup() {} void loop() {}\n")


def test_lower_cli_writes_file(tmp_path: pathlib.Path):
    sketch_dir = tmp_path / "clock"
    sketch_dir.mkdir()
    (sketch_dir / "clock.ino").write_text(BASIC, encoding="utf-8")
    dest = tmp_path / "out.c"
    assert main(["lower", str(sketch_dir), "-o", str(dest)]) == 0
    text = dest.read_text(encoding="utf-8")
    assert "nd_tm1637_init" in text


def test_official_tm1637_lowers():
    if not OFFICIAL_TM1637.is_file():
        pytest.skip("NiusDisplay checkout not next to this repo")
    sk = sketch.resolve_sketch(OFFICIAL_TM1637)
    lowered = cxxlower.lower_sketch(sk)
    assert lowered.lowered
    assert sketch.cxx_reason(lowered.text) is None
    assert "nd_tm1637_show_time" in lowered.text
    assert "nius_serial_println_s" in lowered.text
    assert "NB TM1637" in lowered.text


def test_monitor_refuses_com35():
    from niusburner.monitor import monitor
    assert monitor("COM35", 9600, seconds=0.1) == 2


def test_upload_yes_monitor_refuses_com35(monkeypatch, tmp_path):
    from niusburner.__main__ import main
    from niusburner import build, workflow

    sketch_dir = tmp_path / "x"
    sketch_dir.mkdir()
    (sketch_dir / "x.ino").write_text(
        "void setup(void) {}\nvoid loop(void) {}\n", encoding="utf-8")
    out = tmp_path / "out"
    plan = workflow.plan_compile(sketch_dir, "at89s52", output=out)
    image = out / "firmware.ihx"
    result = build.Mcs51Build(
        image=image,
        map_file=out / "firmware.map",
        memory_file=out / "firmware.mem",
        manifest=out / "build-manifest.json",
        program_bytes=10,
        kernel_data_bytes=None,
    )
    monkeypatch.setattr(workflow, "plan_compile", lambda *a, **k: plan)
    monkeypatch.setattr(workflow, "compile_plan", lambda *a, **k: result)
    monkeypatch.setattr(workflow, "upload_image", lambda *a, **k: 0)
    rc = main([
        "upload", str(sketch_dir), "--board", "at89s52", "--yes",
        "--port", "COM35", "--expect", "NB TM1637",
    ])
    assert rc == 2


def test_uart_baud_from_sketch():
    from niusburner.monitor import uart_baud_from_sketch

    assert uart_baud_from_sketch('Serial.begin(9600);') == 9600
    assert uart_baud_from_sketch("nius_serial_begin(115200UL);") == 115200
    assert uart_baud_from_sketch("void setup() {}") is None


def test_monitor_clears_dtr_before_open(monkeypatch):
    from niusburner import monitor as mon
    import sys
    import types

    seen = {}

    class FakeSerial:
        def __init__(self):
            self.port = None
            self.baudrate = None
            self.timeout = None
            self.dtr = True
            self.rts = True

        def open(self):
            seen["dtr_at_open"] = self.dtr
            seen["rts_at_open"] = self.rts

        def read(self, _n):
            return b""

        def close(self):
            pass

    fake = types.ModuleType("serial")
    fake.Serial = FakeSerial
    monkeypatch.setitem(sys.modules, "serial", fake)
    assert mon.monitor("COM31", 9600, seconds=0.05) == 0
    assert seen.get("dtr_at_open") is False
    assert seen.get("rts_at_open") is False


def test_official_tm1637_compiles_with_sdcc(tmp_path: pathlib.Path):
    from niusburner import build

    if not OFFICIAL_TM1637.is_file() or build.find_sdcc() is None:
        pytest.skip("needs a NiusDisplay checkout and SDCC")
    out = tmp_path / "out"
    plan = workflow.plan_compile(
        OFFICIAL_TM1637, "at89s52", library=NIUSDISPLAY, output=out)
    result = workflow.compile_plan(plan, out)
    assert 0 < result.program_bytes <= 8192
    assert (out / "firmware.ihx").is_file()


def test_official_hd44780_lowers():
    if not OFFICIAL_HD44780.is_file():
        pytest.skip("NiusDisplay checkout not next to this repo")
    sk = sketch.resolve_sketch(OFFICIAL_HD44780)
    lowered = cxxlower.lower_sketch(sk)
    assert lowered.lowered
    assert sketch.cxx_reason(lowered.text) is None
    assert "nd_nb_charlcd_begin_i2c" in lowered.text
    assert "NB HD44780" in lowered.text
    assert any(p.name == "nd_nb_charlcd.c" for p in lowered.extra_c)


def test_official_hd44780_menu_fits_8kb(tmp_path: pathlib.Path):
    from niusburner import build

    if not OFFICIAL_HD44780.is_file() or build.find_sdcc() is None:
        pytest.skip("needs a NiusDisplay checkout and SDCC")
    out = tmp_path / "out"
    plan = workflow.plan_compile(
        OFFICIAL_HD44780, "at89s52", library=NIUSDISPLAY, output=out)
    result = workflow.compile_plan(plan, out)
    assert 0 < result.program_bytes <= 8192
    assert (out / "firmware.ihx").is_file()


def test_lower_refuses_matrix_fill_screen():
    src = (
        "#include <NiusDisplay.h>\n"
        "NiusMatrix matrix(1, 10);\n"
        "void setup() { matrix.begin(); matrix.fillScreen(0); }\n"
        "void loop() {}\n"
    )
    with pytest.raises(CxxLowerError, match="fillScreen"):
        lower_text(src)


def test_example_hd44780_and_max7219_compile_with_sdcc(tmp_path: pathlib.Path):
    from niusburner import build

    if not NIUSDISPLAY.is_dir() or build.find_sdcc() is None:
        pytest.skip("needs a NiusDisplay checkout and SDCC")
    for sketch_dir, cap in (
        (EXAMPLE_HD44780, 8192),
        (EXAMPLE_MAX7219, 8192),
        (ROOT / "examples" / "niusdisplay_tm1637", 8192),
    ):
        if not sketch_dir.is_dir():
            pytest.skip(f"missing {sketch_dir}")
        out = tmp_path / sketch_dir.name
        plan = workflow.plan_compile(
            sketch_dir, "at89s52", library=NIUSDISPLAY, output=out)
        result = workflow.compile_plan(plan, out)
        assert 0 < result.program_bytes <= cap, sketch_dir.name
        assert (out / "firmware.ihx").is_file()
