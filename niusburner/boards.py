"""First-class boards for compile and upload.

Copyright 2026 dunknowcoding (NiusRobotLab)
SPDX-License-Identifier: Apache-2.0

A board is a part plus the memory map and programmer a minimum board of that
part actually has. The CLI asks for `--board at89s52` rather than a pile of
`--code-size` / `--iram-size` flags, because those numbers are properties of
the silicon, not of the sketch.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

#: Peripherals the translator asks about before lowering an Arduino API that
#: needs one. Order is the order `niusburner boards --features` prints them.
FEATURES = ("gpio", "uart", "i2c", "spi", "pwm", "adc", "eeprom")

#: What a capability value means. A board that only bit-bangs a bus still
#: counts as providing it -- the point of the distinction is documentation
#: and error messages, not gating.
HARDWARE = "hardware"
SOFTWARE = "software"
NONE = "none"

HERE = Path(__file__).parent
BOARDS_PATH = HERE / "boards.json"


@dataclass(frozen=True)
class Board:
    id: str
    part: str
    family: str
    compiler: str
    code_size: int
    iram_size: int
    xram_size: int
    model: str
    programmer: str
    status: str
    signature: str
    note: str
    aliases: tuple[str, ...] = ()
    f_cpu: int = 11059200
    peripherals: tuple[tuple[str, str], ...] = ()

    @property
    def flashable(self) -> bool:
        """True when `upload` can erase and program this board itself."""
        return self.status == "verified" and self.programmer == "usbisp_hid"

    def capability(self, feature: str) -> str:
        """"hardware", "software" or "none" for one peripheral."""
        for name, value in self.peripherals:
            if name == feature:
                return value
        return NONE

    def provides(self, feature: str) -> bool:
        """True when the board can run this feature at all, bit-banged or not."""
        return self.capability(feature) in (HARDWARE, SOFTWARE)


def load_catalog(path: Path | None = None) -> dict[str, Any]:
    with open(path or BOARDS_PATH, "r", encoding="utf-8") as fh:
        return json.load(fh)


def all_boards(path: Path | None = None) -> dict[str, Board]:
    catalog = load_catalog(path)
    boards: dict[str, Board] = {}
    for board_id, entry in catalog.get("boards", {}).items():
        boards[board_id] = Board(
            id=board_id,
            part=str(entry.get("part", board_id)),
            family=str(entry["family"]),
            compiler=str(entry["compiler"]),
            code_size=int(entry["code_size"]),
            iram_size=int(entry["iram_size"]),
            xram_size=int(entry.get("xram_size", 0)),
            model=str(entry.get("model", "small")),
            programmer=str(entry["programmer"]),
            status=str(entry.get("status", "planned")),
            signature=str(entry.get("signature", "")),
            note=str(entry.get("note", "")),
            aliases=tuple(entry.get("aliases") or ()),
            f_cpu=int(entry.get("f_cpu", 11059200)),
            peripherals=tuple(
                (str(k), str(v))
                for k, v in (entry.get("peripherals") or {}).items()
            ),
        )
    return boards


def get_board(name: str, path: Path | None = None) -> Board:
    """Look up a board by id or alias. Case-insensitive."""
    want = name.strip().lower()
    boards = all_boards(path)
    if want in boards:
        return boards[want]
    for board in boards.values():
        if want == board.part.lower() or want in {a.lower() for a in board.aliases}:
            return board
    known = ", ".join(sorted(boards))
    raise KeyError(
        f"unknown board {name!r}. Known boards: {known}. "
        "Run `python -m niusburner boards`."
    )
