"""The translator's contract: what it keeps, what it refuses, what it links.

Copyright 2026 dunknowcoding (NiusRobotLab)
SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from niusburner import boards, cxxlower, sketch as sketch_mod, workflow
from niusburner.adapter import AdapterError, _render
from niusburner.cxxlower import CxxLowerError

AT89S52 = boards.get_board("at89s52")


def lower(text: str, board=AT89S52) -> str:
    return cxxlower.lower_text(text, board=board)


# --------------------------------------------------------------- assembly ---

@pytest.mark.parametrize("block", [
    "__asm\n    nop\n    mov a, #0x55\n__endasm;",
    "_asm\n    nop\n_endasm;",
    'asm("nop");',
    '__asm__ volatile ("nop");',
])
def test_assembly_reaches_the_output_byte_for_byte(block):
    """Every rewrite pass steps over assembly; nothing in it may change."""
    src = f"void setup(){{ Serial.begin(9600); }}\nvoid loop(){{ {block} }}\n"
    assert block in lower(src)


def test_type_words_are_not_rewritten_inside_assembly():
    """`bool` inside an asm block is an operand, not a C type."""
    src = (
        "void setup(){}\n"
        "void loop(){ __asm\n"
        "  ; bool true false uint8_t\n"
        "  nop\n"
        "__endasm; }\n"
    )
    out = lower(src)
    assert "; bool true false uint8_t" in out
    assert "unsigned char true" not in out


def test_registers_are_left_alone():
    src = (
        "void setup(){ P1 = 0xFF; TMOD = (TMOD & 0x0F) | 0x20; }\n"
        "void loop(){ if (!(P3 & 0x10)) { P1_0 = 0; } }\n"
    )
    out = lower(src)
    assert "P1 = 0xFF;" in out
    assert "TMOD = (TMOD & 0x0F) | 0x20;" in out
    assert "P3 & 0x10" in out
    assert "P1_0 = 0;" in out


# ------------------------------------------------------------- structures ---

def test_struct_tag_gets_a_typedef_so_the_cxx_spelling_is_legal_c():
    out = lower(
        "struct P { int x; };\nvoid setup(){ P p; p.x = 1; }\nvoid loop(){}\n")
    assert "typedef struct P P;" in out
    assert "struct P { int x; };" in out


def test_existing_typedef_is_not_duplicated():
    src = "typedef struct P { int x; } P;\nvoid setup(){}\nvoid loop(){}\n"
    assert lower(src).count("typedef") == 1


def test_enum_tag_also_gets_one():
    out = lower(
        "enum C { A, B };\nvoid setup(){ C c = A; (void)c; }\nvoid loop(){}\n")
    assert "typedef enum C C;" in out


# --------------------------------------------------------------- refusals ---

@pytest.mark.parametrize("src, token", [
    ("class Foo { public: int x; };\nvoid setup(){}\nvoid loop(){}\n", "class"),
    ("template <class T> T f(T a){return a;}\nvoid setup(){}\nvoid loop(){}\n",
     "template"),
    ("void setup(){ int a = static_cast<int>(1); }\nvoid loop(){}\n",
     "static_cast"),
    ("enum class E { A };\nvoid setup(){}\nvoid loop(){}\n", "enum class"),
    ("void f(int &x){ x = 1; }\nvoid setup(){}\nvoid loop(){}\n", "&"),
    ("void setup(){ throw 1; }\nvoid loop(){}\n", "throw"),
    ("void setup(){ auto x = 1; (void)x; }\nvoid loop(){}\n", "auto"),
])
def test_real_cxx_is_refused(src, token):
    with pytest.raises(CxxLowerError) as exc:
        lower(src)
    assert token in exc.value.hit


@pytest.mark.parametrize("call, feature", [
    ("analogWrite(3, 128);", "pwm"),
    ("analogRead(0);", "adc"),
    ("tone(3, 440);", "pwm"),
])
def test_calls_needing_absent_peripherals_are_refused_by_name(call, feature):
    with pytest.raises(CxxLowerError) as exc:
        lower(f"void setup(){{}}\nvoid loop(){{ {call} }}\n")
    message = str(exc.value)
    assert feature in message
    assert "at89s52" in message
    # The message must say what is actually wrong, not just "unsupported".
    assert "boards --features" in message


def test_micros_is_refused_rather_than_returning_a_frozen_number():
    with pytest.raises(CxxLowerError) as exc:
        lower("void setup(){}\nvoid loop(){ micros(); }\n")
    assert "timebase" in str(exc.value)


def test_avr_headers_are_refused_with_the_8051_spelling():
    with pytest.raises(CxxLowerError) as exc:
        lower("#include <avr/interrupt.h>\nvoid setup(){}\nvoid loop(){}\n")
    assert "__interrupt" in str(exc.value)


# ----------------------------------------------------------- capabilities ---

def test_wire_lowers_on_a_board_that_can_bit_bang_it():
    src = (
        "#include <Wire.h>\n"
        "void setup(){ Wire.begin(); Wire.beginTransmission(0x27);"
        " Wire.write(0); Wire.endTransmission(); }\n"
        "void loop(){}\n"
    )
    out = lower(src)
    assert "nius_wire_begin()" in out
    assert "nius_wire_begin_transmission((unsigned char)(0x27))" in out
    assert "Wire" not in out.replace("nius_wire", "")


def test_spi_lowers_and_keeps_the_arduino_constants():
    src = (
        "#include <SPI.h>\n"
        "void setup(){ SPI.begin(); SPI.setDataMode(SPI_MODE0); }\n"
        "void loop(){ SPI.transfer(0xA5); }\n"
    )
    out = lower(src)
    assert "nius_spi_begin()" in out
    assert "nius_spi_set_data_mode((unsigned char)(SPI_MODE0))" in out
    assert "nius_spi_transfer((unsigned char)(0xA5))" in out


def test_wire_is_refused_on_a_board_with_no_i2c():
    no_i2c = replace(
        AT89S52, peripherals=(("gpio", "hardware"), ("i2c", "none")))
    with pytest.raises(CxxLowerError) as exc:
        lower("#include <Wire.h>\nvoid setup(){}\nvoid loop(){}\n", board=no_i2c)
    assert "i2c" in str(exc.value)


def test_spi_transaction_object_is_refused_with_the_alternative():
    src = (
        "#include <SPI.h>\n"
        "void setup(){ SPI.beginTransaction(SPISettings(1, MSBFIRST, 0)); }\n"
        "void loop(){}\n"
    )
    with pytest.raises(CxxLowerError) as exc:
        lower(src)
    assert "setDataMode" in str(exc.value)


def test_wire_buffer_write_is_refused_rather_than_guessed():
    src = (
        "#include <Wire.h>\n"
        "void setup(){ Wire.begin(); Wire.write(buf, 4); }\n"
        "void loop(){}\n"
    )
    with pytest.raises(CxxLowerError) as exc:
        lower(src)
    assert "loop over the bytes" in str(exc.value)


# ------------------------------------------------------------ side effects --

def test_an_argument_used_twice_must_not_have_side_effects():
    with pytest.raises(AdapterError) as exc:
        _render("f({0}, {0})", "obj", ["i++"], {})
    assert "evaluated" in str(exc.value)
    # A plain expression is safe to repeat.
    assert _render("f({0}, {0})", "obj", ["a + b"], {}) == "f(a + b, a + b)"


# ----------------------------------------------------------------- linking --

def test_only_the_runtime_units_a_sketch_calls_are_linked(tmp_path):
    """SDCC links whole modules, so an unused unit is dead flash."""
    folder = tmp_path / "bare"
    folder.mkdir()
    (folder / "bare.ino").write_text(
        "void setup(){ pinMode(0, OUTPUT); }\n"
        "void loop(){ digitalWrite(0, HIGH); }\n",
        encoding="ascii")
    plan = workflow.plan_compile(folder, "at89s52", output=tmp_path / "out")
    names = {p.name for p in plan.sources}
    assert "nius_sketch.c" in names
    for unused in ("nius_serial.c", "nius_wire.c", "nius_spi.c", "nius_extra.c"):
        assert unused not in names


def test_calling_map_pulls_in_the_extras_unit(tmp_path):
    folder = tmp_path / "mapper"
    folder.mkdir()
    (folder / "mapper.ino").write_text(
        "void setup(){}\n"
        "void loop(){ int v = map(1, 0, 10, 0, 100); (void)v; }\n",
        encoding="ascii")
    plan = workflow.plan_compile(folder, "at89s52", output=tmp_path / "out")
    assert "nius_extra.c" in {p.name for p in plan.sources}


def test_a_loose_ino_does_not_absorb_its_neighbours(tmp_path):
    """Arduino concatenates a sketch *folder*, not whatever sits beside a file."""
    (tmp_path / "mine.ino").write_text(
        "void setup(){}\nvoid loop(){}\n", encoding="ascii")
    (tmp_path / "someone_else.ino").write_text(
        "class NotMine { public: int x; };\n", encoding="ascii")

    sk = sketch_mod.resolve_sketch(tmp_path / "mine.ino")
    assert "NotMine" not in sk.text


# ----------------------------------------------- checks without any C++ ----

def test_board_refusals_apply_to_a_sketch_with_no_cxx_in_it(tmp_path):
    """The peripheral is missing whether or not the sketch spells any C++.

    A plain-C .ino used to skip lowering entirely, so `analogWrite` reached
    SDCC and came back as an undefined symbol instead of the reason.
    """
    folder = tmp_path / "plain"
    folder.mkdir()
    (folder / "plain.ino").write_text(
        "void setup(void){ pinMode(0, OUTPUT); }\n"
        "void loop(void){ analogWrite(0, 128); }\n", encoding="ascii")
    with pytest.raises(ValueError) as exc:
        workflow.plan_compile(folder, "at89s52", output=tmp_path / "out")
    message = str(exc.value)
    assert "pwm" in message
    # It is not a language problem, so it must not be reported as one.
    assert "uses C++" not in message


def test_a_board_refusal_is_not_phrased_as_a_cxx_problem():
    with pytest.raises(CxxLowerError) as exc:
        lower("void setup(){}\nvoid loop(){ analogRead(0); }\n")
    assert exc.value.kind == "board"


def test_real_cxx_keeps_the_cxx_phrasing():
    with pytest.raises(CxxLowerError) as exc:
        lower("class F { public: int x; };\nvoid setup(){}\nvoid loop(){}\n")
    assert exc.value.kind == "cxx"


# ------------------------------------------------- the interrupt-enable ----

def test_interrupts_lower_to_the_global_enable_bit():
    out = lower("void setup(){ noInterrupts(); interrupts(); }\nvoid loop(){}\n")
    assert "(EA = 0)" in out
    assert "(EA = 1)" in out
    assert "noInterrupts(" not in out
    assert "interrupts(" not in out.replace("noInterrupts(", "")


def test_interrupts_are_not_rewritten_inside_assembly():
    src = (
        "void setup(){}\n"
        "void loop(){ __asm\n"
        "  ; interrupts() here is a comment, not a call\n"
        "  nop\n"
        "__endasm; }\n"
    )
    out = lower(src)
    assert "; interrupts() here is a comment, not a call" in out


def test_a_call_with_arguments_is_left_alone():
    """Only the zero-argument Arduino spelling is the interrupt-enable bit."""
    out = lower("void interrupts(int n){ (void)n; }\n"
                "void setup(){ interrupts(1); }\nvoid loop(){}\n")
    assert "interrupts(1)" in out
    assert "EA" not in out


# ----------------------------------------------------- newly closed gaps ---

@pytest.mark.parametrize("call, needle", [
    ("v = pow(2, 3);", "floating point"),
    ("v = sqrt(9);", "floating point"),
    ("v = sin(1);", "floating point"),
    ("v = pgm_read_byte(p);", "__code"),
    ("memcpy_P(a, b, 2);", "__code"),
    ("v = pulseInLong(0, 1);", "timebase"),
])
def test_gaps_that_used_to_reach_sdcc_are_now_refused(call, needle):
    """Each of these passed through and failed at link time with no reason."""
    src = (f"unsigned long v; const char *p; char a[2], b[2];\n"
           f"void setup(){{}}\nvoid loop(){{ {call} (void)v; }}\n")
    with pytest.raises(CxxLowerError) as exc:
        lower(src)
    assert needle in str(exc.value)


def test_progmem_is_refused_with_the_storage_class_that_replaces_it():
    with pytest.raises(CxxLowerError) as exc:
        lower('const char t[] PROGMEM = "x";\nvoid setup(){}\nvoid loop(){}\n')
    assert "__code" in str(exc.value)
    assert exc.value.kind == "api"


def test_progmem_inside_assembly_is_left_alone():
    src = ("void setup(){ __asm\n  ; PROGMEM is a word in this comment\n"
           "  nop\n__endasm; }\nvoid loop(){}\n")
    assert "; PROGMEM is a word in this comment" in lower(src)


# ------------------------------------------------------- widths and casts --

def test_printing_a_number_keeps_its_width_and_sign():
    """Every print used to be forced through a 16-bit signed int.

    Serial.println(millis()) went negative after 32.7 s and wrapped at 65.5;
    println(70000) printed 4464. The generated call carries no cast now, and
    _Generic in nius_serial.h picks the right routine.
    """
    out = lower("void setup(){ Serial.begin(9600); }\n"
                "void loop(){ Serial.println(millis()); }\n")
    assert "nius_serial_println_num((millis()), 10)" in out
    assert "(int)" not in out


def test_a_character_literal_still_prints_as_a_character():
    out = lower("void setup(){ Serial.begin(9600); }\n"
                "void loop(){ Serial.print('A'); }\n")
    assert "nius_serial_write((unsigned char)('A'))" in out


def test_generic_dispatch_covers_unsigned_long_separately():
    header = (cxxlower.Path(__file__).resolve().parents[1] / "niusburner" /
              "adapters" / "Arduino" / "mcs51" / "nius_serial.h")
    text = header.read_text(encoding="utf-8")
    assert "_Generic" in text
    # Only unsigned long needs its own arm; everything narrower converts to
    # long without losing a value.
    assert "unsigned long: nius_serial_print_ulong" in text
    assert "default: nius_serial_print_long" in text


# ------------------------------------------------ Arduino spellings exist --

@pytest.mark.parametrize("snippet", [
    "byte b = 5; (void)b;",
    "word w = 5; (void)w;",
    "char *p = nullptr; (void)p;",
    "unsigned char m = _BV(3); (void)m;",
    "pinMode(LED_BUILTIN, OUTPUT);",
    "unsigned char t[4]; memset(t, 0, 4);",
    "static_assert(1, \"ok\");",
])
def test_common_arduino_spellings_are_not_refused(snippet):
    lower(f"void setup(){{ Serial.begin(9600); }}\nvoid loop(){{ {snippet} }}\n")


@pytest.mark.parametrize("snippet, needle", [
    ("pinMode(A0, INPUT);", "analog input"),
    ("int a[3]; for (int v : a) { (void)v; }", "real C++"),
])
def test_spellings_that_cannot_work_here_are_refused(snippet, needle):
    with pytest.raises(CxxLowerError) as exc:
        lower(f"void setup(){{}}\nvoid loop(){{ {snippet} }}\n")
    assert needle in str(exc.value)


def test_a_default_argument_is_refused_before_the_linker_sees_it():
    src = ("void f(int a, int b = 2) { (void)a; (void)b; }\n"
           "void setup(){}\nvoid loop(){ f(1); }\n")
    with pytest.raises(CxxLowerError):
        lower(src)


def test_a_three_part_for_loop_is_not_mistaken_for_a_range_for():
    """A ternary in the init clause has a colon too."""
    out = lower("void setup(){}\n"
                "void loop(){ int i; for (i = 0 ? 1 : 2; i < 3; i++) { } }\n")
    assert "for (i = 0 ? 1 : 2; i < 3; i++)" in out
