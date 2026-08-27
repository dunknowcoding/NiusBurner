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
_HARD = (
    re.compile(r"\bclass\s+\w+"),
    re.compile(r"\btemplate\s*<"),
    re.compile(r"\bnamespace\s+\w+"),
    re.compile(r"\bnew\s+\w+"),
    re.compile(r"\bString\s+\w+"),
    re.compile(r"\b(public|private|protected)\s*:"),
    re.compile(r"\b(virtual|override|typename|constexpr)\b"),
    re.compile(r"::"),
)

_UNSUPPORTED_HEADERS = {
    "wire.h",
    "spi.h",
    "softwareserial.h",
    "hardwareSerial.h",
}

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
    def __init__(self, hit: str, detail: str = "") -> None:
        self.hit = hit
        self.detail = detail
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


def _skip_non_code(text: str, i: int) -> int:
    n = len(text)
    while i < n:
        if text.startswith("//", i):
            nl = text.find("\n", i)
            return n if nl < 0 else nl + 1
        if text.startswith("/*", i):
            end = text.find("*/", i + 2)
            return n if end < 0 else end + 2
        if text.startswith("__asm", i) and (i + 5 == n or not _is_ident_char(text[i + 5])):
            end = text.find("__endasm", i + 5)
            if end < 0:
                return n
            end += len("__endasm")
            if end < n and text[end] == ";":
                end += 1
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
    body = _code_words(text)
    for pattern in _HARD:
        match = pattern.search(body)
        if match:
            return match.group(0)
    return None


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
            fn = "nius_serial_println_int" if nl else "nius_serial_print_int"
            return f"{fn}((int)({args[0]}), {args[1]})"
        if len(args) != 1:
            raise CxxLowerError(method, f"Serial.{method} takes 0, 1 or 2 arguments")
        arg = args[0]
        if _looks_like_string(arg):
            fn = "nius_serial_println_s" if nl else "nius_serial_print_s"
            return f"{fn}({arg})"
        if arg.strip().startswith("'"):
            call = f"nius_serial_write((unsigned char)({arg}))"
            return f"({call}, nius_serial_println())" if nl else call
        fn = "nius_serial_println_int" if nl else "nius_serial_print_int"
        return f"{fn}((int)({arg}), 10)"
    raise CxxLowerError(
        method,
        f"Serial.{method}() is not in the BASIC UART subset "
        "(begin/print/println/write/read/available/flush/end)",
    )


def _lower_serial(text: str) -> str:
    spans: list[tuple[int, int, str]] = []
    n = len(text)
    i = 0
    while i < n:
        jumped = _skip_non_code(text, i)
        if jumped != i:
            i = jumped
            continue
        if _at_word(text, i, "Serial"):
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


def _check_headers(text: str) -> None:
    for inc in _INCLUDE.findall(text):
        name = Path(inc).name.lower()
        if name in _UNSUPPORTED_HEADERS:
            raise CxxLowerError(
                inc,
                f"{inc} is an Arduino C++ library; there is no 8051 port here",
            )


def lower_with_info(
    text: str,
    *,
    mounts: list[Path] | None = None,
    adapters: list | None = None,
) -> tuple[str, object]:
    """Return (C text, adapter RewriteInfo)."""
    from . import adapter as adapter_mod

    hard = _hard_reason(text)
    if hard:
        raise CxxLowerError(
            hard,
            "this is real C++, not the BASIC facade "
            "(no class/template/String/namespace/::)",
        )
    _check_headers(text)
    had_serial = bool(re.search(r"\bSerial\b", _code_words(text)))
    out = _lower_f(text)
    out = _lower_serial(out)
    leftover_serial = re.search(r"\bSerial\b", _code_words(out))
    if leftover_serial:
        raise CxxLowerError(
            leftover_serial.group(0),
            "Serial was not fully rewritten to the 8051 UART runtime",
        )
    out = _replace_words(out, (("true", "1"), ("false", "0")))
    out = _replace_words(out, _TYPE_WORDS)
    loaded = adapters if adapters is not None else adapter_mod.load_adapters(mounts)
    try:
        out, info = adapter_mod.rewrite(out, loaded, host=sys.modules[__name__])
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


def lower_text(
    text: str,
    *,
    mounts: list[Path] | None = None,
    adapters: list | None = None,
) -> str:
    """Return C that SDCC can compile, or raise CxxLowerError."""
    out, _info = lower_with_info(text, mounts=mounts, adapters=adapters)
    return out


def lower_sketch(
    sk: Sketch,
    *,
    mounts: list[Path] | None = None,
    adapters: list | None = None,
) -> Sketch:
    """Return a Sketch whose text is C. Raises CxxLowerError if not BASIC."""
    new_text, info = lower_with_info(sk.text, mounts=mounts, adapters=adapters)
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
    args = parser.parse_args(argv)
    try:
        sk = resolve_sketch(args.sketch)
        if cxx_reason(sk.text) is None:
            text = sk.text
        else:
            text = lower_text(sk.text, mounts=args.mount or None)
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
