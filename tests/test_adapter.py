"""Mounted library adapters. No hardware."""

from __future__ import annotations

import json
import pathlib

from niusburner import adapter, cxxlower, sketch
from niusburner.cxxlower import lower_text


def _imu_tree(tmp_path: pathlib.Path) -> pathlib.Path:
    root = tmp_path / "NiusIMU"
    nb = root / "niusburner"
    nb.mkdir(parents=True)
    (nb / "adapter.json").write_text(json.dumps({
        "name": "NiusIMU",
        "match_includes": ["NiusIMU.h"],
        "drop_includes": ["NiusIMU.h"],
        "bare_include_headers": ["nius_imu.h"],
        "classes": {
            "NiusIMU": {
                "headers": ["nius_imu.h"],
                "stems": ["nius_imu"],
                "c_decl": "static nius_imu {name};",
                "ctor": {"min_args": 0, "max_args": 0, "fields": []},
                "methods": {
                    "begin": {"args": 0, "emit": "nius_imu_begin(&{name})"},
                    "read": {"args": 0, "emit": "nius_imu_read(&{name})"},
                },
            }
        },
    }, indent=2), encoding="utf-8")
    return root


def test_niussegment_still_comes_from_the_niusdisplay_adapter():
    src = (
        "#include <NiusDisplay.h>\n"
        "NiusSegment seg(4, 5, 4);\n"
        "void setup() { seg.begin(); }\n"
        "void loop() { seg.showTime(12, 0); }\n"
    )
    out = lower_text(src)
    assert "static nd_tm1637 seg;" in out
    assert "nd_tm1637_init(&seg, 4, 5, 4)" in out
    assert "nd_tm1637_show_time(&seg, 12, 0, 1)" in out
    assert "NiusSegment" not in cxxlower._code_words(out)
    assert "NiusDisplay.h" not in out


def test_mount_niusimu_without_editing_cxxlower(tmp_path: pathlib.Path):
    lib = _imu_tree(tmp_path)
    src = (
        "#include <NiusIMU.h>\n"
        "NiusIMU imu;\n"
        "void setup() { imu.begin(); }\n"
        "void loop() { imu.read(); }\n"
    )
    bundled = lower_text(src, adapters=adapter.bundled_adapters())
    assert "nius_imu_begin" not in bundled
    out = lower_text(src, mounts=[lib])
    assert "static nius_imu imu;" in out
    assert "nius_imu_begin(&imu)" in out
    assert "nius_imu_read(&imu)" in out
    assert "NiusIMU.h" not in out
    assert "NiusIMU" not in cxxlower._code_words(out)


def test_mounted_niusimu_plan_does_not_require_niusdisplay(tmp_path: pathlib.Path):
    lib = _imu_tree(tmp_path)
    sketch_dir = tmp_path / "imu"
    sketch_dir.mkdir()
    (sketch_dir / "imu.ino").write_text(
        "#include <NiusIMU.h>\n"
        "NiusIMU imu;\n"
        "void setup() { imu.begin(); }\n"
        "void loop() {}\n",
        encoding="utf-8",
    )
    sk = sketch.resolve_sketch(sketch_dir)
    lowered = cxxlower.lower_sketch(sk, mounts=[lib])
    assert not sketch.uses_niusdisplay(lowered)
    assert "nius_imu_begin" in lowered.text


def test_bundled_niusdisplay_adapter_is_loadable():
    names = [a.name for a in adapter.bundled_adapters()]
    assert "NiusDisplay" in names


def test_niuscharlcd_lowers_i2c_begin_and_print():
    src = (
        "#include <NiusDisplay.h>\n"
        "NiusCharLCD lcd(16, 2, 0x27);\n"
        "void setup() {\n"
        "  Serial.begin(115200);\n"
        "  lcd.begin();\n"
        "  lcd.print(\"hi\");\n"
        "  lcd.print(' ');\n"
        "}\n"
        "void loop() {}\n"
    )
    out = lower_text(src)
    assert "nd_nb_charlcd_begin_i2c(&lcd, &lcd_bus, 16, 2, 0x27)" in out
    assert 'nd_hd44780_print(&lcd, "hi")' in out
    assert "nd_hd44780_write_char(&lcd, (unsigned char)(' '))" in out
    assert "NiusCharLCD" not in cxxlower._code_words(out)
    assert "nius_serial_begin(115200)" in out


def test_niusmatrix_lowers_without_gfx():
    src = (
        "#include <NiusDisplay.h>\n"
        "NiusMatrix matrix(1, 2, 0);\n"
        "void setup() { matrix.begin(); matrix.testAll(1); }\n"
        "void loop() {}\n"
    )
    out = lower_text(src)
    assert "nd_nb_matrix_begin(&matrix, 1, 2, 0)" in out
    assert "nd_nb_matrix_test(&matrix, 1)" in out
    assert "NiusMatrix" not in cxxlower._code_words(out)
