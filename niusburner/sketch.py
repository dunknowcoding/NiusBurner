"""Turn a sketch path into C sources SDCC can compile.

Copyright 2026 dunknowcoding (NiusRobotLab)
SPDX-License-Identifier: Apache-2.0

Arduino concatenates `.ino` files into C++. SDCC has no C++ mode, so this
module is honest about that: a sketch that uses classes, `Serial`, or
`NiusDisplay.h` is refused with a pointer to the C API (NiusDuino) rather
than being fed to a compiler that cannot parse it.

A sketch that is already C -- `setup()`/`loop()`, optional Arduino GPIO
names -- is wrapped and compiled. That is the NiusDisplay Tier 3 contract.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).parent
RUNTIME_MCS51 = HERE / "runtime" / "mcs51"

_COMMENT_LINE = re.compile(r"//.*?$", re.M)
_COMMENT_BLOCK = re.compile(r"/\*.*?\*/", re.S)
_INCLUDE = re.compile(r'^\s*#\s*include\s*[<"]([^>"]+)[>"]', re.M)
_MAIN = re.compile(r"\b(?:void|int)\s+main\s*\(")
_SETUP = re.compile(r"\bvoid\s+setup\s*\(")
_LOOP = re.compile(r"\bvoid\s+loop\s*\(")

# Tokens that mean the sketch is C++ (Arduino IDE), not C (SDCC / NiusDuino).
_CXX_PATTERNS = (
    re.compile(r"\bNiusDisplay\.h\b"),
    re.compile(r"\bNiusSegment\b"),
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
    has_main: bool = False
    has_setup_loop: bool = False
    from_directory: bool = False


def _strip_comments(text: str) -> str:
    text = _COMMENT_BLOCK.sub(" ", text)
    return _COMMENT_LINE.sub(" ", text)


def cxx_reason(text: str) -> str | None:
    """Why this sketch cannot be compiled as C, or None if it looks like C."""
    body = _strip_comments(text)
    for pattern in _CXX_PATTERNS:
        match = pattern.search(body)
        if match:
            return match.group(0)
    return None


def cxx_error(sketch: Sketch, hit: str) -> ValueError:
    return ValueError(
        f"{sketch.path.name} is an Arduino C++ sketch ({hit!r}). "
        "SDCC has no C++ compiler, so this file cannot be built for an 8051.\n"
        "  - Rewrite it as C that reads like a sketch: #include \"NiusDuino.h\", "
        "setup()/loop(), and the C driver headers (nd_tm1637.h, nd_ssd1306.h, ...).\n"
        "  - Or keep the C++ .ino and use the IAR 8051 Arduino core in NiusDisplay "
        "(cores/mcs51-iar) with arduino-cli.\n"
        "  - A GPIO blink without NiusDisplay can stay an .ino if it only uses "
        "pinMode/digitalWrite/delay."
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
        text = _concat_ino(directory, primary)
        kind = "ino"
    else:
        text = _read(primary)
        kind = "c"

    # Sibling .c files belong to a sketch directory, not to a lone file in a
    # port tree (ports/8051-sdcc holds several demos next to each other).
    extra_c: tuple[Path, ...] = ()
    if from_directory or kind == "ino":
        extra_c = tuple(
            p for p in sorted(directory.glob("*.c"))
            if p.resolve() != primary.resolve()
        )
    includes = tuple(_INCLUDE.findall(text))
    stripped = _strip_comments(text)
    return Sketch(
        path=primary,
        directory=directory,
        kind=kind,
        text=text,
        includes=includes,
        extra_c=extra_c,
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
