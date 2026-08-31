"""Lower a BASIC Arduino C++ sketch to C that SDCC can parse.

Copyright 2026 dunknowcoding (NiusRobotLab)
SPDX-License-Identifier: Apache-2.0

SDCC has no C++ mode. This is not a C++ compiler. Mounted library adapters
(``<Lib>/niusburner/adapter.json``) rewrite BASIC facades such as NiusSegment
onto the portable C core. Classes, templates, String, Print, and unmapped
devices stay refused.
"""

from __future__ import annotations

import re
import sys
from dataclasses import replace
from pathlib import Path

from .sketch import Sketch, _INCLUDE, _strip_comments, cxx_reason

BANNER = (
    "/* niusburner: Arduino BASIC C++ lowered to C. Do not edit. */\n"
)

_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

# Library-specific tokens (NiusTFT, …) live in adapter.json, not here.
#
# Everything listed here is C++ whose meaning C cannot carry. It is refused
# rather than approximated, because an approximation of a destructor or an
# overload is a silent behaviour change. Syntax that C simply rejects --
# default arguments, references, overloads -- is left to SDCC, which reports
# it with a line number.
_HARD = (
    re.compile(r"\bclass\s+\w+"),
    re.compile(r"\btemplate\s*<"),
    re.compile(r"\bnamespace\s+\w+"),
    re.compile(r"\bnew\s+\w+"),
    re.compile(r"\bdelete\s*(\[\s*\])?\s+\w+"),
    re.compile(r"\bString\s+\w+"),
    re.compile(r"\b(public|private|protected)\s*:"),
    re.compile(r"\b(virtual|override|typename|constexpr|explicit|friend|mutable)\b"),
    re.compile(r"\b(static_cast|dynamic_cast|reinterpret_cast|const_cast)\s*<"),
    re.compile(r"\benum\s+class\b"),
    re.compile(r"\boperator\b"),
    re.compile(r"\b(try|catch|throw)\b"),
    re.compile(r"\busing\s+namespace\b"),
    re.compile(r"\bauto\s+\w+\s*="),
    re.compile(r"\bthis\s*->"),
    # `int &x` cannot be an expression -- a type name followed by & is a
    # reference declaration, and C has no references.
    re.compile(
        r"\b(?:void|char|short|int|long|float|double|unsigned|signed|bool|"
        r"boolean|u?int(?:8|16|32|64)_t|size_t)\s*&\s*\w"
    ),
    re.compile(r"::"),
    # Range-based for. SDCC reports this as a bare syntax error on the
    # colon, which says nothing about why.
    re.compile(
        r"\bfor\s*\(\s*(?:const\s+)?"
        r"(?:void|char|short|int|long|unsigned|signed|float|double|bool|"
        r"boolean|byte|word|auto|u?int(?:8|16|32|64)_t)\b[\w\s*&]*\s+"
        r"\w+\s*:"
    ),
    # A default argument in a declaration. Without it SDCC compiles the
    # call and the linker complains about `_f_PARM_2`, which is nobody's
    # idea of a useful message.
    re.compile(
        r"\b(?:void|char|short|int|long|unsigned|signed|float|double|bool|"
        r"boolean|byte|word|u?int(?:8|16|32|64)_t)\s+\w+\s*\("
        r"[^;{)]*\w\s*=\s*[^;{)]*\)\s*[;{]"
    ),
)

#: Arduino headers whose facade needs a peripheral. If the board can drive it,
#: hardware or bit-banged, the matching adapter lowers the calls; if it cannot,
#: the include is refused here with the reason.
_HEADER_FEATURE = {
    "wire.h": "i2c",
    "spi.h": "spi",
    "eeprom.h": "eeprom",
    "servo.h": "pwm",
}

#: Headers refused whatever the board is, with the reason.
_HEADER_REFUSED = {
    "softwareserial.h": (
        "SoftwareSerial is a C++ class and its receive path needs a "
        "pin-change interrupt. Use the hardware UART through Serial."
    ),
    "hardwareserial.h": (
        "HardwareSerial is the AVR core's C++ class. Serial is already "
        "lowered onto this part's UART; the header is not needed."
    ),
    "avr/io.h": (
        "avr/io.h is AVR register naming. On an 8051 the SFRs come from "
        "<8052.h>, which the sketch runtime already includes."
    ),
    "avr/interrupt.h": (
        "avr/interrupt.h is AVR-specific. SDCC spells an 8051 interrupt "
        "handler `void isr(void) __interrupt(n)`."
    ),
    "avr/pgmspace.h": (
        "avr/pgmspace.h is AVR flash addressing. SDCC uses the __code "
        "storage class, and F(\"...\") already lowers to a plain literal."
    ),
}

#: Arduino calls that need a peripheral the part may not have.
_CALL_FEATURE = {
    "analogWrite": "pwm",
    "analogRead": "adc",
    "analogReference": "adc",
    "tone": "pwm",
    "noTone": "pwm",
}

#: Arduino calls refused whatever the board is, with the reason.
_CALL_REFUSED = {
    "attachInterrupt": (
        "attachInterrupt() installs a C++-style handler through a vector "
        "table this runtime does not build. SDCC spells it directly: "
        "`void on_int0(void) __interrupt(0) { ... }`."
    ),
    "detachInterrupt": (
        "detachInterrupt() pairs with attachInterrupt(), which is not "
        "lowered. Clear the enable bit instead: EX0 = 0."
    ),
    "micros": (
        "micros() needs a free-running microsecond timebase. This runtime "
        "counts milliseconds inside delay() and has no timer running, so "
        "micros() would return a number that never advances."
    ),
    "pulseIn": (
        "pulseIn() measures against a microsecond timebase this runtime "
        "does not have. Time the pin with a timer of your own."
    ),
    "yield": (
        "yield() is the Arduino core's cooperative hook. There is no "
        "scheduler here; the call would do nothing."
    ),
    "pulseInLong": (
        "pulseInLong() measures against a microsecond timebase this runtime "
        "does not have, the same as pulseIn(). Time the pin with a timer of "
        "your own."
    ),
    "pgm_read_byte": (
        "pgm_read_byte() is the AVR way to reach a separate program-memory "
        "address space. The 8051 reads code memory directly: declare the "
        "table `__code` and index it, `const __code unsigned char t[] = ...` "
        "then `t[i]`."
    ),
    "pgm_read_word": (
        "pgm_read_word() is AVR-only. Declare the table `__code` and index "
        "it directly."
    ),
    "pgm_read_dword": (
        "pgm_read_dword() is AVR-only. Declare the table `__code` and index "
        "it directly."
    ),
    "memcpy_P": (
        "memcpy_P() is AVR-only. A `__code` array is readable with plain "
        "memcpy() on this part."
    ),
    "strcpy_P": (
        "strcpy_P() is AVR-only. A `__code` string is readable with plain "
        "strcpy() on this part."
    ),
}

#: Floating point. SDCC can compile it, but every one of these drags in the
#: soft-float library, and 8 KB of flash does not have room for it next to a
#: sketch. Refusing names the cost instead of letting the linker report it.
_FLOAT_MATH = (
    "pow", "sqrt", "sin", "cos", "tan", "asin", "acos", "atan", "atan2",
    "exp", "log", "log10", "sinh", "cosh", "tanh", "ceil", "floor", "fabs",
    "fmod", "modf", "frexp", "ldexp",
)
for _name in _FLOAT_MATH:
    _CALL_REFUSED.setdefault(_name, (
        f"{_name}() is floating point. On this part every float operation "
        "goes through SDCC's software library, which does not fit next to a "
        "sketch in 8 KB and has no fixed cost to reason about. Use integer "
        "arithmetic, or a lookup table declared `__code`."
    ))

#: Bare identifiers, not calls: AVR storage attributes that SDCC has never
#: heard of. Left alone they reach the compiler as an undefined identifier
#: pointing at the declaration, which says nothing about what to do instead.
_IDENT_REFUSED = {
    # A0..A7 name the analog inputs. On a part with no converter they are
    # not pin numbers that happen to be missing, they are nothing at all.
    **{f"A{i}": (
        f"A{i} names an analog input, and this part has no converter to "
        "read one. Digital pins are plain numbers: 0-7 are P1.0-P1.7 and "
        "8-15 are P2.0-P2.7."
    ) for i in range(8)},
    "PROGMEM": (
        "PROGMEM is the AVR attribute for putting a table in flash. The 8051 "
        "has a storage class for it: `const __code unsigned char t[] = {...};`"
        " and then plain `t[i]`, with no accessor macro."
    ),
    "PGM_P": (
        "PGM_P is an AVR pointer-into-flash type. On this part the type is "
        "`const __code char *`."
    ),
}

#: Calls with an exact 8051 spelling. Rewritten rather than refused, because
#: the meaning carries over unchanged.
_CALL_EMIT = {
    # The global interrupt enable is one bit in the SFR space. `interrupts()`
    # and `noInterrupts()` are that bit, so they lower rather than refuse.
    "interrupts": "(EA = 1)",
    "noInterrupts": "(EA = 0)",
}

_EMPTY_CALL = re.compile(r"\(\s*\)")

_TYPE_WORDS = (
    ("uint8_t", "unsigned char"),
    ("int8_t", "signed char"),
    ("uint16_t", "unsigned short"),
    ("int16_t", "signed short"),
    ("uint32_t", "unsigned long"),
    ("int32_t", "signed long"),
    ("size_t", "unsigned int"),
    ("boolean", "unsigned char"),
    ("bool", "unsigned char"),
)


class CxxLowerError(ValueError):
    """A refusal, and what kind it is.

    `kind` decides how the caller phrases it. "cxx" is C++ the translator
    will not carry into C; "board" is a peripheral this part does not have,
    which is not a language problem and must not be reported as one.
    """

    def __init__(self, hit: str, detail: str = "", kind: str = "cxx") -> None:
        self.hit = hit
        self.detail = detail
        self.kind = kind
        super().__init__(detail or hit)


def _skip_quoted(text: str, i: int) -> int:
    quote = text[i]
    i += 1
    n = len(text)
    while i < n:
        if text[i] == "\\" and i + 1 < n:
            i += 2
            continue
        if text[i] == quote:
            return i + 1
        i += 1
    return n


#: Assembly spellings this translator steps over without reading. Every
#: rewrite pass walks the source through `_skip_non_code`, so anything listed
#: here reaches the C output byte for byte -- the one guarantee that lets a
#: sketch hand-write a timing loop or a port sequence and keep it.
_ASM_BLOCKS = (("__asm", "__endasm"), ("_asm", "_endasm"))
_ASM_CALLS = ("__asm__", "asm")
_ASM_QUALIFIERS = ("volatile", "__volatile__", "goto", "const")


def _skip_asm_call(text: str, i: int, keyword: str) -> int | None:
    """Index after `asm [volatile] ( ... )`, or None if this is not one."""
    n = len(text)
    j = i + len(keyword)
    while True:
        while j < n and text[j].isspace():
            j += 1
        for qualifier in _ASM_QUALIFIERS:
            if _at_word(text, j, qualifier):
                j += len(qualifier)
                break
        else:
            break
    if j < n and text[j] == "(":
        return _matching_close(text, j) + 1
    return None


def _at_include(text: str, i: int) -> bool:
    """True at the `#` of an `#include` line.

    Include lines are not expressions: `#include <Wire.h>` contains the token
    `Wire.h`, which a method-call scanner would otherwise read as `Wire`
    followed by a member access. Other directives are left alone, because a
    `#define` body is real code and does need the type rewrites.
    """
    if text[i] != "#":
        return False
    start = text.rfind("\n", 0, i) + 1
    if text[start:i].strip():
        return False
    j = i + 1
    while j < len(text) and text[j] in " \t":
        j += 1
    return text.startswith("include", j)


def _skip_non_code(text: str, i: int) -> int:
    n = len(text)
    while i < n:
        if _at_include(text, i):
            nl = text.find("\n", i)
            return n if nl < 0 else nl + 1
        if text.startswith("//", i):
            nl = text.find("\n", i)
            return n if nl < 0 else nl + 1
        if text.startswith("/*", i):
            end = text.find("*/", i + 2)
            return n if end < 0 else end + 2
        for opener, closer in _ASM_BLOCKS:
            if _at_word(text, i, opener):
                end = text.find(closer, i + len(opener))
                if end < 0:
                    return n
                end += len(closer)
                if end < n and text[end] == ";":
                    end += 1
                return end
        for keyword in _ASM_CALLS:
            if _at_word(text, i, keyword):
                end = _skip_asm_call(text, i, keyword)
                if end is not None:
                    return end
        if text[i] in "'\"":
            return _skip_quoted(text, i)
        return i
    return n


def _is_ident_char(ch: str) -> bool:
    return ch.isalnum() or ch == "_"


def _at_word(text: str, i: int, word: str) -> bool:
    if not text.startswith(word, i):
        return False
    if i and _is_ident_char(text[i - 1]):
        return False
    j = i + len(word)
    if j < len(text) and _is_ident_char(text[j]):
        return False
    return True


def _matching_close(text: str, open_i: int) -> int:
    opener = text[open_i]
    closer = {"(": ")", "[": "]", "{": "}"}[opener]
    depth = 0
    i = open_i
    n = len(text)
    while i < n:
        jumped = _skip_non_code(text, i)
        if jumped != i:
            i = jumped
            continue
        if text[i] == opener:
            depth += 1
            i += 1
            continue
        if text[i] == closer:
            depth -= 1
            i += 1
            if depth == 0:
                return i - 1
            continue
        i += 1
    raise CxxLowerError(opener, f"unbalanced {opener!r} starting at {open_i}")


def _split_args(inner: str) -> list[str]:
    inner = inner.strip()
    if not inner:
        return []
    args: list[str] = []
    start = 0
    depth = 0
    i = 0
    n = len(inner)
    while i < n:
        jumped = _skip_non_code(inner, i)
        if jumped != i:
            i = jumped
            continue
        if inner[i] in "([{":
            depth += 1
            i += 1
            continue
        if inner[i] in ")]}":
            depth -= 1
            i += 1
            continue
        if inner[i] == "," and depth == 0:
            args.append(inner[start:i].strip())
            start = i + 1
        i += 1
    args.append(inner[start:].strip())
    return [a for a in args if a]


def _apply(text: str, spans: list[tuple[int, int, str]]) -> str:
    for start, end, repl in sorted(spans, key=lambda item: item[0], reverse=True):
        text = text[:start] + repl + text[end:]
    return text


def _walk_code(text: str):
    i = 0
    n = len(text)
    while i < n:
        jumped = _skip_non_code(text, i)
        if jumped != i:
            i = jumped
            continue
        yield i
        i += 1


_STRING_LIT = re.compile(r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'')


def _code_words(text: str) -> str:
    """Comment- and string-stripped source, so `::` inside F("a::b") is not C++."""
    return _STRING_LIT.sub('""', _strip_comments(text))


def _hard_reason(text: str) -> str | None:
    """The first piece of real C++ in *text*, as it is written.

    The earliest match wins, and the longest one at that position breaks a
    tie, so `enum class E` is reported as `enum class` rather than `class E`
    and `template <class T>` as `template <`. Reporting the wrong half of a
    construct sends people looking in the wrong place.
    """
    body = _code_words(text)
    best: tuple[int, int, str] | None = None
    for pattern in _HARD:
        match = pattern.search(body)
        if not match:
            continue
        found = (match.start(), -len(match.group(0)), match.group(0))
        if best is None or found[:2] < best[:2]:
            best = found
    return best[2] if best else None


def _lower_f(text: str) -> str:
    spans: list[tuple[int, int, str]] = []
    n = len(text)
    i = 0
    while i < n:
        jumped = _skip_non_code(text, i)
        if jumped != i:
            i = jumped
            continue
        if _at_word(text, i, "F"):
            j = i + 1
            while j < n and text[j].isspace():
                j += 1
            if j < n and text[j] == "(":
                close = _matching_close(text, j)
                inner = text[j + 1:close].strip()
                if inner.startswith('"'):
                    spans.append((i, close + 1, inner))
                    i = close + 1
                    continue
        i += 1
    return _apply(text, spans)


def _looks_like_string(arg: str) -> bool:
    a = arg.strip()
    return a.startswith('"') or a.startswith("PSTR")


def _looks_like_float(arg: str) -> bool:
    return bool(re.match(r"^-?\d+\.\d+", arg.strip()))


def _serial_call(method: str, args: list[str]) -> str:
    if method == "begin":
        baud = args[0] if args else "9600"
        return f"nius_serial_begin({baud})"
    if method == "end":
        return "nius_serial_end()"
    if method == "flush":
        return "nius_serial_flush()"
    if method == "available":
        return "nius_serial_available()"
    if method == "read":
        return "nius_serial_read()"
    if method == "write":
        if len(args) != 1:
            raise CxxLowerError("write", "Serial.write(byte) only")
        return f"nius_serial_write((unsigned char)({args[0]}))"
    if method in ("print", "println"):
        nl = method == "println"
        if not args:
            return "nius_serial_println()" if nl else "(void)0"
        if _looks_like_float(args[0]):
            raise CxxLowerError(
                method,
                "Serial.print(float) is not lowered (SDCC float runtime is huge)",
            )
        if len(args) == 2:
            fn = "nius_serial_println_num" if nl else "nius_serial_print_num"
            # No cast: the width and signedness of the expression are the
            # caller's, and _Generic in nius_serial.h keeps them.
            return f"{fn}(({args[0]}), {args[1]})"
        if len(args) != 1:
            raise CxxLowerError(method, f"Serial.{method} takes 0, 1 or 2 arguments")
        arg = args[0]
        if _looks_like_string(arg):
            fn = "nius_serial_println_s" if nl else "nius_serial_print_s"
            return f"{fn}({arg})"
        if arg.strip().startswith("'"):
            call = f"nius_serial_write((unsigned char)({arg}))"
            return f"({call}, nius_serial_println())" if nl else call
        fn = "nius_serial_println_num" if nl else "nius_serial_print_num"
        return f"{fn}(({arg}), 10)"
    raise CxxLowerError(
        method,
        f"Serial.{method}() is not in the BASIC UART subset "
        "(begin/print/println/write/read/available/flush/end)",
    )


def _lower_serial(text: str, board=None) -> str:
    spans: list[tuple[int, int, str]] = []
    n = len(text)
    i = 0
    while i < n:
        jumped = _skip_non_code(text, i)
        if jumped != i:
            i = jumped
            continue
        if _at_word(text, i, "Serial"):
            # Serial is a peripheral like any other: a part with no UART
            # should be told so here, not by a page of compiler errors
            # about registers it does not have.
            if board is not None and not board.provides("uart"):
                raise CxxLowerError(
                    "Serial", _feature_refusal("Serial", "uart", board),
                    kind="board")
            j = i + 6
            while j < n and text[j].isspace():
                j += 1
            if j < n and text[j] == ".":
                j += 1
                while j < n and text[j].isspace():
                    j += 1
                m = _IDENT.match(text, j)
                if not m:
                    raise CxxLowerError("Serial", "Serial. is not a method call")
                method = m.group(0)
                j = m.end()
                while j < n and text[j].isspace():
                    j += 1
                if j >= n or text[j] != "(":
                    raise CxxLowerError(
                        "Serial",
                        "only Serial.method(...) is rewritten to the 8051 UART",
                    )
                close = _matching_close(text, j)
                args = _split_args(text[j + 1:close])
                spans.append((i, close + 1, _serial_call(method, args)))
                i = close + 1
                continue
            # Arduino USB cores treat `if (Serial)` as "host attached".
            # On this UART that is always true.
            spans.append((i, i + 6, "1"))
            i += 6
            continue
        i += 1
    return _apply(text, spans)


def _replace_words(text: str, mapping: tuple[tuple[str, str], ...]) -> str:
    spans: list[tuple[int, int, str]] = []
    n = len(text)
    i = 0
    while i < n:
        jumped = _skip_non_code(text, i)
        if jumped != i:
            i = jumped
            continue
        hit = False
        for word, repl in mapping:
            if _at_word(text, i, word):
                spans.append((i, i + len(word), repl))
                i += len(word)
                hit = True
                break
        if not hit:
            i += 1
    return _apply(text, spans)


_INC_ARDUINO = re.compile(
    r'^[ \t]*#[ \t]*include[ \t]*[<"]Arduino\.h[>"][ \t]*\r?$',
    re.M | re.I,
)


def _inject_include(text: str, line: str) -> str:
    if line in text:
        return text
    matches = list(re.finditer(r"^[ \t]*#[ \t]*include[ \t].*$", text, re.M))
    if not matches:
        return line + "\n" + text
    at = matches[-1].end()
    return text[:at] + "\n" + line + text[at:]


def _lower_setup_loop(text: str) -> str:
    text = re.sub(r"\bvoid\s+setup\s*\(\s*\)", "void setup(void)", text)
    text = re.sub(r"\bvoid\s+loop\s*\(\s*\)", "void loop(void)", text)
    return text


#: Why a missing peripheral is refused rather than emulated. Each of these is
#: a fact about the silicon, so the message says what is actually wrong
#: instead of "unsupported".
_FEATURE_WHY = {
    "pwm": (
        "This part has no PWM unit and no timer output pin, so faking it "
        "means a timer interrupt firing through everything else. Measured "
        "here, one I2C transaction takes 1.06 ms and delay() is a busy-wait "
        "accurate to 0.03 %: an interrupt frequent enough to be PWM lands "
        "inside both."
    ),
    "adc": (
        "There is no analogue input on this part at all. A reading has to "
        "come from an external converter, read over I2C or SPI."
    ),
    "i2c": (
        "Two-wire signalling needs port pins that can be released to a "
        "pull-up, which this part does not have."
    ),
    "spi": (
        "Three-wire signalling needs three usable port pins, which this "
        "part does not have free."
    ),
    "eeprom": (
        "There is no byte-erasable data memory here; the flash array erases "
        "whole, so a single-byte write is not something to emulate."
    ),
    "uart": (
        "This part has no hardware serial port. Bit-banging one means "
        "holding the CPU for a whole frame at an exact rate, which "
        "stops everything else the sketch is doing."
    ),
    "gpio": "This part has no general-purpose port pins.",
}


def _feature_refusal(what: str, feature: str, board) -> str:
    """Why *what* cannot be lowered for *board*, in the board's own terms."""
    if board is None:
        return (
            f"{what} needs {feature}. Pass --board so NiusBurner can say "
            "whether this part has it."
        )
    if board.provides(feature):
        return (
            f"{board.id} does provide {feature} "
            f"({board.capability(feature)}), but NiusBurner has no lowering "
            f"for {what} on it yet."
        )
    why = _FEATURE_WHY.get(feature, "")
    return (
        f"{what} needs {feature}, and {board.id} has none. {why} "
        "It is refused rather than approximated, because an approximation "
        "here changes when the rest of the sketch runs. "
        "`python -m niusburner boards --features` lists what each board has."
    ).replace("  ", " ")


def _check_headers(text: str, board=None) -> None:
    for inc in _INCLUDE.findall(text):
        name = Path(inc).name.lower()
        lower_inc = inc.lower().replace("\\", "/")
        for refused, detail in _HEADER_REFUSED.items():
            if name == refused or lower_inc.endswith(refused):
                raise CxxLowerError(inc, detail, kind="api")
        feature = _HEADER_FEATURE.get(name)
        if feature and (board is None or not board.provides(feature)):
            raise CxxLowerError(
                inc, _feature_refusal(inc, feature, board), kind="board")


def _lower_direct_calls(text: str) -> str:
    """Rewrite the calls that have an exact 8051 spelling.

    Only the zero-argument form is rewritten, and only outside strings,
    comments and assembly -- the same walker every other pass uses, so an
    `interrupts` mnemonic operand inside __asm is left alone.
    """
    out: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        jumped = _skip_non_code(text, i)
        if jumped != i:
            out.append(text[i:jumped])
            i = jumped
            continue
        match = _IDENT.match(text, i)
        if not match:
            out.append(text[i])
            i += 1
            continue
        name = match.group(0)
        emit = _CALL_EMIT.get(name)
        if emit is not None:
            call = _EMPTY_CALL.match(text, match.end())
            if call:
                out.append(emit)
                i = call.end()
                continue
        out.append(name)
        i = match.end()
    return "".join(out)


def _check_calls(text: str, board=None) -> None:
    """Refuse Arduino calls whose peripheral this part does not have."""
    n = len(text)
    i = 0
    while i < n:
        jumped = _skip_non_code(text, i)
        if jumped != i:
            i = jumped
            continue
        match = _IDENT.match(text, i)
        if not match:
            i += 1
            continue
        name = match.group(0)
        if name in _IDENT_REFUSED:
            raise CxxLowerError(name, _IDENT_REFUSED[name], kind="api")
        j = match.end()
        while j < n and text[j].isspace():
            j += 1
        if j < n and text[j] == "(":
            if name in _CALL_REFUSED:
                raise CxxLowerError(name, _CALL_REFUSED[name], kind="api")
            feature = _CALL_FEATURE.get(name)
            if feature:
                raise CxxLowerError(
                    name, _feature_refusal(f"{name}()", feature, board),
                    kind="board")
        i = match.end()


_TAGGED = ("struct", "union", "enum")


def _lower_struct_tags(text: str) -> str:
    """Give every tagged type a typedef of the same name.

    C++ lets `struct Point { int x; }; Point p;` name the type without the
    tag; C does not. Emitting `typedef struct Point Point;` after the
    definition makes the C++ spelling legal C without touching the sketch's
    own declarations, so the layout, the field order and every use site stay
    exactly as written.
    """
    inserts: list[tuple[int, int, str]] = []
    n = len(text)
    i = 0
    while i < n:
        jumped = _skip_non_code(text, i)
        if jumped != i:
            i = jumped
            continue
        keyword = None
        for word in _TAGGED:
            if _at_word(text, i, word):
                keyword = word
                break
        if keyword is None:
            i += 1
            continue
        if text[:i].rstrip().endswith("typedef"):
            i += len(keyword)
            continue
        j = i + len(keyword)
        while j < n and text[j].isspace():
            j += 1
        match = _IDENT.match(text, j)
        if not match:
            i += len(keyword)
            continue
        tag = match.group(0)
        j = match.end()
        while j < n and text[j].isspace():
            j += 1
        if j >= n or text[j] != "{":
            # A forward declaration or a use, not a definition.
            i = match.end()
            continue
        close = _matching_close(text, j)
        end = close + 1
        while end < n and text[end] != ";":
            end += 1
        if end >= n:
            i = close + 1
            continue
        already = re.search(
            rf"\btypedef\s+{keyword}\s+{re.escape(tag)}\s+{re.escape(tag)}\s*;",
            text,
        )
        if not already:
            inserts.append((end + 1, end + 1,
                            f"\ntypedef {keyword} {tag} {tag};"))
        i = end + 1
    return _apply(text, inserts)


def lower_with_info(
    text: str,
    *,
    mounts: list[Path] | None = None,
    adapters: list | None = None,
    board=None,
) -> tuple[str, object]:
    """Return (C text, adapter RewriteInfo).

    *board* is a `boards.Board`. It decides which peripherals exist, so the
    same sketch can lower on a part that can bit-bang a bus and be refused,
    with the reason, on one that cannot.
    """
    from . import adapter as adapter_mod

    hard = _hard_reason(text)
    if hard:
        raise CxxLowerError(
            hard,
            "this is real C++, not the BASIC facade "
            "(no class/template/String/namespace/::)",
        )
    _check_headers(text, board)
    _check_calls(text, board)
    had_serial = bool(re.search(r"\bSerial\b", _code_words(text)))
    out = _lower_f(text)
    out = _lower_serial(out, board)
    leftover_serial = re.search(r"\bSerial\b", _code_words(out))
    if leftover_serial:
        raise CxxLowerError(
            leftover_serial.group(0),
            "Serial was not fully rewritten to the 8051 UART runtime",
        )
    out = _replace_words(out, (("true", "1"), ("false", "0")))
    out = _replace_words(out, _TYPE_WORDS)
    out = _lower_struct_tags(out)
    out = _lower_direct_calls(out)
    loaded = adapters if adapters is not None else adapter_mod.load_adapters(mounts)
    try:
        out, info = adapter_mod.rewrite(
            out, loaded, host=sys.modules[__name__], board=board)
    except adapter_mod.AdapterError as exc:
        raise CxxLowerError(exc.hit, exc.detail) from exc
    out = _INC_ARDUINO.sub("", out)
    if had_serial:
        out = _inject_include(out, '#include "nius_serial.h"')
    out = _lower_setup_loop(out)
    leftover = cxx_reason(out)
    if leftover:
        raise CxxLowerError(
            leftover,
            "still C++ after lowering the BASIC subset",
        )
    if not out.startswith("/* niusburner:"):
        out = BANNER + out
    return out, info


def check_text(text: str, *, board=None) -> str:
    """Board checks and API rewrites that apply to any Arduino sketch.

    Lowering C++ is conditional on the sketch actually being C++. These are
    not. A peripheral the part does not have is missing whether or not the
    sketch spells anything in C++, and `interrupts()` needs the same rewrite
    either way -- so a plain-C .ino gets the refusal with its reason instead
    of an undefined symbol from the linker.
    """
    _check_headers(text, board)
    _check_calls(text, board)
    return _lower_direct_calls(text)


def check_sketch(sk: Sketch, *, board=None) -> Sketch:
    """`check_text` over a Sketch, leaving `lowered` alone when nothing moved."""
    new_text = check_text(sk.text, board=board)
    if new_text == sk.text:
        return sk
    return replace(sk, text=new_text)


def lower_text(
    text: str,
    *,
    mounts: list[Path] | None = None,
    adapters: list | None = None,
    board=None,
) -> str:
    """Return C that SDCC can compile, or raise CxxLowerError."""
    out, _info = lower_with_info(
        text, mounts=mounts, adapters=adapters, board=board)
    return out


def lower_sketch(
    sk: Sketch,
    *,
    mounts: list[Path] | None = None,
    adapters: list | None = None,
    board=None,
) -> Sketch:
    """Return a Sketch whose text is C. Raises CxxLowerError if not BASIC."""
    new_text, info = lower_with_info(
        sk.text, mounts=mounts, adapters=adapters, board=board)
    includes = tuple(_INCLUDE.findall(new_text))
    stripped = _strip_comments(new_text)
    from .sketch import _MAIN, _SETUP, _LOOP

    extra_c = list(sk.extra_c)
    extra_includes = list(sk.extra_includes)
    seen_c = {path.resolve() for path in extra_c}
    seen_inc = {path.resolve() for path in extra_includes}
    for path in info.bind_sources:
        resolved = path.resolve()
        if resolved not in seen_c:
            extra_c.append(path)
            seen_c.add(resolved)
        parent = path.parent.resolve()
        if parent not in seen_inc:
            extra_includes.append(path.parent)
            seen_inc.add(parent)
    return replace(
        sk,
        text=new_text,
        includes=includes,
        extra_c=tuple(extra_c),
        extra_includes=tuple(extra_includes),
        extra_defines=tuple(dict.fromkeys((*sk.extra_defines, *info.defines))),
        has_main=bool(_MAIN.search(stripped)),
        has_setup_loop=bool(_SETUP.search(stripped) and _LOOP.search(stripped)),
        lowered=True,
    )


def main(argv: list[str] | None = None) -> int:
    """CLI entry: `python -m niusburner.cxxlower` or `niusburner lower`."""
    import argparse

    from .sketch import resolve_sketch

    parser = argparse.ArgumentParser(
        prog="niusburner lower",
        description=(
            "Rewrite a BASIC Arduino C++ sketch into C that SDCC can compile. "
            "This is not a C++ compiler: NiusTFT/String/class stay refused."
        ),
    )
    parser.add_argument("sketch", type=Path, help="`.ino`, `.c`, or a sketch directory")
    parser.add_argument(
        "-o", "--output", type=Path,
        help="write C to this file (default: stdout)",
    )
    parser.add_argument(
        "--mount", action="append", type=Path, default=[],
        help="library root with niusburner/adapter.json; repeatable",
    )
    parser.add_argument(
        "--board", default="at89s52",
        help="target board, so a refusal can say which peripheral is missing",
    )
    args = parser.parse_args(argv)
    try:
        from .boards import get_board

        board = get_board(args.board)
        sk = resolve_sketch(args.sketch)
        if cxx_reason(sk.text) is None:
            # Not C++, but still an Arduino sketch: the board checks and the
            # API rewrites apply either way.
            text = check_text(sk.text, board=board)
        else:
            text = lower_text(sk.text, mounts=args.mount or None, board=board)
    except CxxLowerError as exc:
        print(f"lower failed ({exc.hit!r}): {exc.detail}", file=sys.stderr)
        return 2
    except (OSError, ValueError) as exc:
        print(f"lower failed: {exc}", file=sys.stderr)
        return 2
    if not text.endswith("\n"):
        text += "\n"
    if args.output is None:
        sys.stdout.write(text)
        return 0
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(text, encoding="utf-8", newline="\n")
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
