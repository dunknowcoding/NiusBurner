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
# displays do not. MAX7219 keeps an 8-byte-per-device buffer in IRAM.
_XRAM_STEMS = {
    "nd_gfx", "nd_text", "nd_font5x7", "nd_color", "nd_ui", "nd_touch",
    "nd_st77xx", "nd_st7789", "nd_st7735", "nd_st7796",
    "nd_ili9341", "nd_ili9488", "nd_gc9a01",
    "nd_ssd1306", "nd_pcd8544", "nd_st7920", "nd_ssd1680",
    "nd_ft6x36", "nd_xpt2046",
}

# Pixel-panel drivers that actually call nd_bus_* / nd_panel_*. Character
# LCD talks to I2C through nd_hal_i2c_write on a filled nd_bus struct, so
# linking nd_bus.c (SPI+I2C+parallel vtables) blew past 8 KB.
_NEEDS_BUS_IMPL = _XRAM_STEMS | {"nd_max7219"}


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


def _sketchbook_from_cli_yaml(path: Path) -> Path | None:
    """Read directories.user from an arduino-cli.yaml."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    block = re.search(r"(?ms)^directories:\s*\n((?:[ \t].*\n)+)", text)
    if not block:
        return None
    match = re.search(r"(?m)^[ \t]+user:\s*[\"']?(.+?)[\"']?\s*$", block.group(1))
    if not match:
        return None
    return Path(match.group(1).strip().strip('"').strip("'"))


def _sketchbook_from_preferences(path: Path) -> Path | None:
    """Read sketchbook.path from Arduino IDE preferences.txt."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    match = re.search(r"(?m)^sketchbook\.path=(.*)$", text)
    if not match:
        return None
    value = match.group(1).strip()
    return Path(value) if value else None


def arduino_sketchbooks() -> list[Path]:
    """Sketchbook directories Arduino IDE / arduino-cli would use on this machine."""
    found: list[Path] = []
    seen: set[Path] = set()

    def add(candidate: Path | None) -> None:
        if candidate is None:
            return
        try:
            resolved = candidate.expanduser().resolve()
        except OSError:
            return
        if resolved in seen:
            return
        seen.add(resolved)
        found.append(resolved)

    for key in ("ARDUINO_SKETCHBOOK", "ARDUINO_DIRECTORIES_USER"):
        value = os.environ.get(key)
        if value:
            add(Path(value))

    home = Path.home()
    for yaml_path in (
        home / "AppData" / "Local" / "Arduino15" / "arduino-cli.yaml",
        home / "AppData" / "Roaming" / "arduino-cli" / "arduino-cli.yaml",
        home / ".arduino15" / "arduino-cli.yaml",
    ):
        if yaml_path.is_file():
            add(_sketchbook_from_cli_yaml(yaml_path))
    for prefs in (
        home / "AppData" / "Local" / "Arduino15" / "preferences.txt",
        home / "AppData" / "Roaming" / "Arduino15" / "preferences.txt",
        home / ".arduino15" / "preferences.txt",
    ):
        if prefs.is_file():
            add(_sketchbook_from_preferences(prefs))
    add(home / "Documents" / "Arduino")
    add(home / "Arduino")
    return found


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
    for book in arduino_sketchbooks():
        candidates.append(book / "libraries" / "NiusDisplay")
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

    stems = {path.stem for path in wanted.values()}
    if "nd_max7219" in stems:
        add_stem("nd_panel")
        add_stem("nd_bus")
    if not (stems & _NEEDS_BUS_IMPL) and "nd_max7219" not in stems:
        wanted.pop("nd_bus", None)
        wanted.pop("nd_panel", None)

    ordered = tuple(wanted.values())
    needs_xram = bool(graphics_stems(ordered))
    needs_text = any(path.stem in {"nd_text", "nd_font5x7"} for path in ordered)
    # ND_TINY drops nd_text_state. Do not force it when the sketch compiled
    # the font engine; those builds still need SRAM and usually miss 8 KB.
    defines: list[str] = []
    if not needs_text:
        defines.append("ND_TINY=1")
    if sketch.has_setup_loop and not sketch.has_main:
        defines.append("ND_NIUSDUINO_MAIN")
    bus_stems = _NEEDS_BUS_IMPL | {
        "nd_hd44780", "nd_bus", "nd_nb_matrix", "nd_nb_charlcd",
    }
    if not any(path.stem in bus_stems for path in ordered):
        defines.append("ND_HAL_BUSES=0")
    charlcd = "nd_hd44780" in stems or "nd_nb_charlcd" in stems
    matrix = "nd_max7219" in stems or "nd_nb_matrix" in stems
    gfx = bool(stems & _XRAM_STEMS)
    if charlcd and not matrix and not gfx:
        defines.append("ND_HAL_SPI=0")
        defines.append("ND_HAL_PAR=0")
        defines.append("ND_HAL_I2C_READ=0")
    if matrix and not charlcd and not gfx:
        defines.append("ND_HAL_I2C=0")
        defines.append("ND_HAL_PAR=0")
    return DisplayLib(
        root=root,
        sources=ordered,
        includes=tuple(include_dirs(root)),
        needs_xram=needs_xram,
        defines=tuple(defines),
    )


def missing_library_error() -> FileNotFoundError:
    return FileNotFoundError(
        "this sketch uses NiusDisplay, but the library was not found.\n"
        "  - Pass --library <path-to-NiusDisplay>\n"
        "  - Or set NIUSDISPLAY to that path\n"
        "  - A checkout next to NiusBurner is detected automatically"
    )
