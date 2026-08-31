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
    #: Ports the package brings out, A upwards. PIC16 only.
    ports: int = 5
    #: Which register makes the analog pins digital at start-up:
    #: 1 ADCON1, 2 CMCON, 3 ANSEL, 0 the part has no analog.
    analog: int = 1
    #: Configuration bits this part does not implement.
    config_omit: tuple[str, ...] = ()
    #: Where the USART appears: 1 RC6/RC7, 2 RB2/RB1, 3 RB2/RB5.
    usart: int = 1
    #: 8051 only: whether the part has a Timer 2 to generate baud.
    timer2: bool = True
    #: True when this part is in the catalog on the strength of
    #: its datasheet and family, with some part of the path still
    #: an assumption. See docs/families/.
    experimental: bool = False
    #: stcgal's name for the bootloader generation.
    protocol: str = "stc89"
    #: PIC18 only: which configuration-bit spelling the part uses.
    config_profile: int = 1
    #: 8-pin PICs name their port GPIO/TRISIO, not PORTA/TRISA.
    gpio_style: bool = False
    #: 0 crystal, 1 internal RC as INTRCIO, 2 internal as INTOSCIO.
    internal_osc: int = 0
    peripherals: tuple[tuple[str, str], ...] = ()

    #: Programmers this tool can actually drive. A board whose programmer is
    #: not here compiles, and says plainly that the route is not wired.
    DRIVEN = ("usbisp_hid", "stcgal", "pickit3")

    #: Families built by XC8 and programmed over ICSP. They share a
    #: runtime shape and differ in registers, not in how they are
    #: compiled or flashed.
    PIC_FAMILIES = ("pic16", "pic18")

    @property
    def is_pic(self) -> bool:
        return self.family in self.PIC_FAMILIES

    @property
    def program_unit(self) -> str:
        """What the compiler counts program memory in for this family.

        A mid-range PIC instruction is one 14-bit word and XC8 counts
        words; a PIC18 instruction is byte-addressed and it counts
        bytes. Calling either by the other's name is wrong by a
        factor of two.
        """
        return "words" if self.family == "pic16" else "bytes"

    @property
    def flashable(self) -> bool:
        """True when `upload` can program this board itself.

        Keyed on the programmer: a board whose transport this tool drives
        can be programmed, whatever else the catalog records about it.
        """
        return self.programmer in self.DRIVEN

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
            ports=int(entry.get("ports", 5)),
            analog=int(entry.get("analog", 1)),
            config_omit=tuple(entry.get("config_omit", ())),
            usart=int(entry.get("usart", 1)),
            timer2=bool(entry.get("timer2", True)),
            experimental=bool(entry.get("experimental", False)),
            protocol=str(entry.get("protocol", "stc89")),
            config_profile=int(entry.get("config_profile", 1)),
            gpio_style=bool(entry.get("gpio_style", False)),
            internal_osc=int(entry.get("internal_osc", 0)),
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
