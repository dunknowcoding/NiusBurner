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

    @property
    def flashable(self) -> bool:
        """True when `upload` can erase and program this board itself."""
        return self.status == "verified" and self.programmer == "usbisp_hid"


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
