"""Turn a sketch path into C sources SDCC can compile.

Copyright 2026 dunknowcoding (NiusRobotLab)
SPDX-License-Identifier: Apache-2.0

Arduino concatenates `.ino` files into C++. SDCC has no C++ mode. A sketch
that is already C -- `setup()`/`loop()`, optional Arduino GPIO names -- is
wrapped and compiled. BASIC Arduino C++ (NiusSegment, F(), Serial.method)
is rewritten to C by `cxxlower` before SDCC sees it. Sibling `.S` / `.asm`
is assembled with sdas8051. Real C++ (classes, templates, String) is refused.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).parent
ADAPTERS = HERE / "adapters"
#: Arduino API translated to C, per target family. `adapters/<Library>/<family>`
#: is where every C++ facade this tool lowers keeps its C support code.
ARDUINO_MCS51 = ADAPTERS / "Arduino" / "mcs51"
ARDUINO_PIC16 = ADAPTERS / "Arduino" / "pic16"

#: The Arduino runtime is per instruction set, not per part: one
#: directory of C for every board in a family.
ARDUINO_RUNTIME = {"mcs51": ARDUINO_MCS51, "pic16": ARDUINO_PIC16}


def runtime_dir(family: str):
    """Where the Arduino API lives for *family*."""
    try:
        return ARDUINO_RUNTIME[family]
    except KeyError:
        raise ValueError(
            f"no Arduino runtime for the {family} family yet. "
            f"Known: {', '.join(sorted(ARDUINO_RUNTIME))}."
        ) from None

_COMMENT_LINE = re.compile(r"//.*?$", re.M)
_COMMENT_BLOCK = re.compile(r"/\*.*?\*/", re.S)
_ASM_BLOCK = re.compile(r"__asm(?:__)?[\s\S]*?__endasm(?:__)?\s*;?", re.I)
_INCLUDE = re.compile(r'^\s*#\s*include\s*[<"]([^>"]+)[>"]', re.M)
_MAIN = re.compile(r"\b(?:void|int)\s+main\s*\(")
_SETUP = re.compile(r"\bvoid\s+setup\s*\(")
_LOOP = re.compile(r"\bvoid\s+loop\s*\(")

# Tokens that mean the sketch is C++ (Arduino IDE), not C (SDCC / NiusDuino).
_CXX_PATTERNS = (
    re.compile(r"\bNiusDisplay\.h\b"),
    re.compile(r"\bNiusSegment\b"),
    re.compile(r"\bNiusCharLCD\b"),
    re.compile(r"\bNiusMatrix\b"),
    re.compile(r"\bNiusTFT\b"),
    re.compile(r"\bNiusOLED\b"),
    re.compile(r"\bclass\s+\w+"),
    re.compile(r"\btemplate\s*<"),
    re.compile(r"\bnamespace\s+\w+"),
    re.compile(r"\bSerial\s*\."),
    re.compile(r"\bString\s+\w+"),
    re.compile(r"\bnew\s+\w+"),
    re.compile(r"\b(public|private|protected)\s*:"),
    re.compile(r"\bF\s*\("),
    re.compile(r"::"),
)


@dataclass(frozen=True)
class Sketch:
    path: Path
    directory: Path
    kind: str                          # "ino" | "c"
    text: str
    includes: tuple[str, ...]
    extra_c: tuple[Path, ...] = ()
    extra_asm: tuple[Path, ...] = ()
    extra_includes: tuple[Path, ...] = ()
    extra_defines: tuple[str, ...] = ()
    has_main: bool = False
    has_setup_loop: bool = False
    from_directory: bool = False
    lowered: bool = False


def _strip_comments(text: str) -> str:
    text = _COMMENT_BLOCK.sub(" ", text)
    text = _ASM_BLOCK.sub(" ", text)
    return _COMMENT_LINE.sub(" ", text)


def cxx_reason(text: str) -> str | None:
    """Why this sketch cannot be compiled as C, or None if it looks like C."""
    body = _strip_comments(text)
    for pattern in _CXX_PATTERNS:
        match = pattern.search(body)
        if match:
            return match.group(0)
    return None


def cxx_error(sketch: Sketch, hit: str, detail: str | None = None,
              kind: str = "cxx") -> ValueError:
    extra = f" {detail}" if detail else ""
    if kind == "board":
        # Not a language problem: the part is missing the peripheral. Saying
        # "uses C++" here sends people to rewrite code that is already fine.
        return ValueError(
            f"{sketch.path.name} cannot run on this part ({hit!r}).{extra}"
        )
    if kind == "api":
        # An Arduino API this runtime does not carry. Also not C++, and the
        # detail already names the 8051 spelling to use instead.
        return ValueError(
            f"{sketch.path.name} uses an Arduino API this runtime does not "
            f"provide ({hit!r}).{extra}"
        )
    return ValueError(
        f"{sketch.path.name} uses C++ that SDCC cannot compile ({hit!r}).{extra}\n"
        "SDCC has no C++ compiler. `python -m niusburner lower` rewrites a BASIC "
        "subset (NiusSegment, F(), Serial on the 8051 UART) into C.\n"
        "  - NiusTFT / NiusOLED / String / class / Print / float cannot be lowered, "
        "and colour/OLED also need XRAM on a minimum AT89S52.\n"
        "  - Assembly uses sdas8051 (`.S` / `.asm` or SDCC `__asm`); not AVR GNU as.\n"
        "  - Or keep the C++ .ino on AVR/ESP, or use NiusDisplay's IAR 8051 core."
    )


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _concat_ino(directory: Path, primary: Path) -> str:
    parts = [_read(primary)]
    for extra in sorted(directory.glob("*.ino")):
        if extra.resolve() == primary.resolve():
            continue
        parts.append(f"\n/* --- {extra.name} --- */\n")
        parts.append(_read(extra))
    return "".join(parts)


def resolve_sketch(path: Path) -> Sketch:
    """Accept a file or a sketch directory the way Arduino does."""
    path = path.expanduser().resolve()
    from_directory = path.is_dir()
    if from_directory:
        named_ino = path / f"{path.name}.ino"
        named_c = path / f"{path.name}.c"
        inos = sorted(path.glob("*.ino"))
        c_files = sorted(path.glob("*.c"))
        if named_ino.is_file():
            primary = named_ino
        elif named_c.is_file() and not inos:
            primary = named_c
        elif len(inos) == 1:
            primary = inos[0]
        elif len(c_files) == 1 and not inos:
            primary = c_files[0]
        elif inos:
            raise ValueError(
                f"{path} has several .ino files and none named {path.name}.ino"
            )
        else:
            raise ValueError(f"{path} contains no .ino or .c sketch")
        directory = path
    else:
        if not path.is_file():
            raise FileNotFoundError(f"sketch not found: {path}")
        primary = path
        directory = path.parent

    suffix = primary.suffix.lower()
    if suffix not in {".ino", ".c"}:
        raise ValueError(f"expected a .ino or .c sketch, got {primary.name}")

    if suffix == ".ino":
        kind = "ino"
    else:
        kind = "c"

    # Arduino concatenates the .ino files of a *sketch folder*: the folder is
    # the sketch, and it is named after it. A path to a loose .ino sitting
    # beside unrelated ones is not that, and pulling its neighbours in would
    # compile code the caller never named -- so a loose file stays alone.
    is_sketch_folder = from_directory or primary.stem == directory.name
    if kind == "ino" and is_sketch_folder:
        text = _concat_ino(directory, primary)
    else:
        text = _read(primary)

    extra_c: tuple[Path, ...] = ()
    extra_asm: tuple[Path, ...] = ()
    if is_sketch_folder:
        extra_c = tuple(
            p for p in sorted(directory.glob("*.c"))
            if p.resolve() != primary.resolve()
        )
        seen: set[Path] = set()
        asm: list[Path] = []
        for pat in ("*.S", "*.s", "*.asm"):
            for path in sorted(directory.glob(pat)):
                resolved = path.resolve()
                if resolved == primary.resolve() or resolved in seen:
                    continue
                seen.add(resolved)
                asm.append(path)
        extra_asm = tuple(asm)
    includes = tuple(_INCLUDE.findall(text))
    stripped = _strip_comments(text)
    return Sketch(
        path=primary,
        directory=directory,
        kind=kind,
        text=text,
        includes=includes,
        extra_c=extra_c,
        extra_asm=extra_asm,
        has_main=bool(_MAIN.search(stripped)),
        has_setup_loop=bool(_SETUP.search(stripped) and _LOOP.search(stripped)),
        from_directory=from_directory,
    )


def uses_niusdisplay(sketch: Sketch) -> bool:
    """True when the sketch names NiusDisplay / NiusDuino / nd_* headers."""
    for inc in sketch.includes:
        name = Path(inc).name.lower()
        if name in {"niusdisplay.h", "niusduino.h"}:
            return True
        if name.startswith("nd_") and name.endswith(".h"):
            return True
    body = _strip_comments(sketch.text)
    return bool(re.search(r"\bnd_\w+\s*\(", body))


def wrap_ino(sketch: Sketch, output: Path, *, runtime_header: str) -> Path:
    """Write a generated .c that SDCC can compile from a C-shaped .ino."""
    header = (
        f"/* Generated by niusburner from {sketch.path.name}. Do not edit. */\n"
        f"#include \"{runtime_header}\"\n\n"
    )
    already = any(
        Path(inc).name.lower() == runtime_header.lower()
        for inc in sketch.includes
    )
    body = sketch.text if already else header + sketch.text
    if not body.endswith("\n"):
        body += "\n"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(body, encoding="utf-8", newline="\n")
    return output
