"""Locate NiusDisplay and pick the C sources a sketch actually uses.

Copyright 2026 dunknowcoding (NiusRobotLab)
SPDX-License-Identifier: Apache-2.0

NiusBurner does not import NiusDisplay. It finds the tree the same way a
user would: `--library`, `NIUSDISPLAY` / `NIUSDISPLAY_ROOT`, a sibling of
this repo, a sibling of the sketch, or the Arduino libraries folder.

SDCC has no `--gc-sections`, so the source list *is* dead-code elimination.
Headers the sketch includes are mapped to same-named `.c` files and those
are scanned recursively. Linking every driver would blow past 8 KB for no
benefit.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from .sketch import Sketch, _INCLUDE, cxx_reason

HERE = Path(__file__).parent
REPO = HERE.parent

_HAL_CANDIDATES = (
    Path("ports/8051-sdcc/nd_hal_8051.c"),
)
_NIUSDUINO = Path("src/compat/NiusDuino.c")

# Colour / framebuffer / UI paths need XRAM on 8051. Segment and character
# displays do not.
_XRAM_STEMS = {
    "nd_gfx", "nd_text", "nd_font5x7", "nd_color", "nd_ui", "nd_touch",
    "nd_st77xx", "nd_st7789", "nd_st7735", "nd_st7796",
    "nd_ili9341", "nd_ili9488", "nd_gc9a01",
    "nd_ssd1306", "nd_pcd8544", "nd_st7920", "nd_ssd1680",
    "nd_ft6x36", "nd_xpt2046",
}


@dataclass(frozen=True)
class DisplayLib:
    root: Path
    sources: tuple[Path, ...]
    includes: tuple[Path, ...]
    needs_xram: bool
    defines: tuple[str, ...]


def _looks_like_niusdisplay(root: Path) -> bool:
    return (root / "src" / "NiusDisplay.h").is_file() or (
        root / "src" / "compat" / "NiusDuino.h"
    ).is_file()


def find_niusdisplay(
    explicit: Path | None = None,
    *,
    sketch_dir: Path | None = None,
) -> Path | None:
    """Return the NiusDisplay root, or None if it is not on this machine."""
    if explicit is not None:
        root = explicit.expanduser().resolve()
        if not _looks_like_niusdisplay(root):
            raise FileNotFoundError(
                f"{root} is not a NiusDisplay tree "
                "(expected src/NiusDisplay.h or src/compat/NiusDuino.h)"
            )
        return root

    for key in ("NIUSDISPLAY", "NIUSDISPLAY_ROOT"):
        value = os.environ.get(key)
        if value:
            root = Path(value).expanduser().resolve()
            if _looks_like_niusdisplay(root):
                return root

    candidates: list[Path] = []
    if sketch_dir is not None:
        candidates.append(sketch_dir.resolve() / "NiusDisplay")
        candidates.append(sketch_dir.resolve().parent / "NiusDisplay")
        # ports/8051-sdcc lives inside the library.
        for parent in sketch_dir.resolve().parents:
            if _looks_like_niusdisplay(parent):
                return parent
    candidates.append(REPO.parent / "NiusDisplay")
    home = Path.home()
    candidates.append(home / "Documents" / "Arduino" / "libraries" / "NiusDisplay")
    candidates.append(home / "Arduino" / "libraries" / "NiusDisplay")
    for root in candidates:
        if _looks_like_niusdisplay(root):
            return root
    return None


def graphics_stems(sources: tuple[Path, ...] | list[Path]) -> list[str]:
    """Source stems that need XRAM on an 8051 (graphics, UI, touch)."""
    return [path.stem for path in sources if path.stem in _XRAM_STEMS]


def include_dirs(root: Path) -> list[Path]:
    src = root / "src"
    paths = [
        src, src / "core", src / "compat", src / "modules",
        src / "panels" / "color", src / "panels" / "mono",
        src / "panels" / "led", src / "panels" / "char", src / "panels" / "epaper",
        src / "touch", src / "ui",
        root / "ports" / "8051-sdcc",
    ]
    return [p for p in paths if p.is_dir()]


def _index_sources(root: Path) -> dict[str, Path]:
    index: dict[str, Path] = {}
    for c_file in root.rglob("*.c"):
        if any(part in {".git", "_work", "tests", "examples"} for part in c_file.parts):
            continue
        index[c_file.stem.lower()] = c_file
    return index


def _stem_of_include(inc: str) -> str:
    return Path(inc).stem


def collect_for_sketch(root: Path, sketch: Sketch) -> DisplayLib:
    """Sources implied by the sketch's includes, plus HAL and NiusDuino."""
    index = _index_sources(root)
    wanted: dict[str, Path] = {}

    def add_stem(stem: str) -> None:
        if stem in wanted:
            return
        path = index.get(stem.lower())
        if path is None:
            return
        wanted[stem] = path
        text = path.read_text(encoding="utf-8", errors="replace")
        reason = cxx_reason(text)
        if reason:
            return
        for inc in _INCLUDE.findall(text):
            add_stem(_stem_of_include(inc))

    for inc in sketch.includes:
        name = Path(inc).name
        if name.lower() == "niusdisplay.h":
            raise ValueError(
                "this sketch includes NiusDisplay.h, which is the Arduino C++ "
                "facade. On 8051/SDCC include NiusDuino.h and the C driver "
                f"header instead (for example panels/led/nd_tm1637.h)."
            )
        add_stem(_stem_of_include(inc))

    hal = None
    for rel in _HAL_CANDIDATES:
        candidate = root / rel
        if candidate.is_file():
            hal = candidate
            break
    if hal is None:
        raise FileNotFoundError(
            f"{root} has no 8051 HAL (expected ports/8051-sdcc/nd_hal_8051.c)"
        )
    wanted.setdefault(hal.stem, hal)

    duino = root / _NIUSDUINO
    if duino.is_file() and sketch.has_setup_loop:
        wanted.setdefault(duino.stem, duino)

    ordered = tuple(wanted.values())
    needs_xram = bool(graphics_stems(ordered))
    defines = ("ND_TINY=1", "ND_NIUSDUINO_MAIN") if sketch.has_setup_loop else ("ND_TINY=1",)
    if sketch.has_main:
        defines = ("ND_TINY=1",)
    return DisplayLib(
        root=root,
        sources=ordered,
        includes=tuple(include_dirs(root)),
        needs_xram=needs_xram,
        defines=defines,
    )


def missing_library_error() -> FileNotFoundError:
    return FileNotFoundError(
        "this sketch uses NiusDisplay, but the library was not found.\n"
        "  - Pass --library <path-to-NiusDisplay>\n"
        "  - Or set NIUSDISPLAY to that path\n"
        "  - A checkout next to NiusBurner is detected automatically"
    )
