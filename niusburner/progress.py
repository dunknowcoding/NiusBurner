"""Console output for long operations, in the NiusRobotLab house style.

Copyright 2026 dunknowcoding (NiusRobotLab)
SPDX-License-Identifier: Apache-2.0

The style is the one ArduinoNRF's uploader established, so a person who has
flashed an nRF52 recognises this console immediately: the same banner, the
same signature bar, the same closing summary, the same failure block.

    *******************************************************************
        <NiusRobotLab, figlet slant>
    *******************************************************************
       8051 Flash Console - Target: at89s52

      NIUS  ==============>.......   64%  Programming  890/1390 B

Three rules carried over from that tool, each for a reason:

**stdout, never stderr.** arduino-cli and Arduino IDE 2 capture both streams
into one Output panel, so anything on stderr is rendered red and, in a plain
terminal, printed twice. Progress is not an error.

**Quiet by default.** The console shows the banner, the bar and the result.
Everything else is a `[nius]` detail line, shown only when the IDE's "verbose
upload" preference or NIUSBURNER_VERBOSE is set.

**Pure ASCII.** The art and the bar render identically whatever the console
codepage is, which on Windows is not something to assume.

The `***` rules appear only around the banner. A failure block is the only
other rule, and it uses dashes.
"""

from __future__ import annotations

import os
import sys
import time
from typing import TextIO

#: figlet "slant", the lab name. The subtitle underneath names the console.
BANNER_RULE = "*" * 67
BANNER_ART = (
    r"    _   ___            ____        __          __  __          __",
    r"   / | / (_)_  _______/ __ \____  / /_  ____  / /_/ /   ____ _/ /_",
    # A raw string cannot end in a backslash, and this row does.
    r"  /  |/ / / / / / ___/ /_/ / __ \/ __ \/ __ \/ __/ /   / __ `/ __ " + "\\",
    r" / /|  / / /_/ (__  ) _, _/ /_/ / /_/ / /_/ / /_/ /___/ /_/ / /_/ /",
    r"/_/ |_/_/\__,_/____/_/ |_|\____/_.___/\____/\__/_____/\__,_/_.___/",
)

_BAR_WIDTH = 22
_FAIL_RULE = "-" * 64

#: Milestones printed when the stream cannot rewrite a line. Ten percent is
#: enough to see movement and few enough to read in an IDE panel.
_QUIET_STEP = 10

_start_utc: float | None = None


def verbose() -> bool:
    """Whether the internal `[nius]` detail lines are shown."""
    return os.environ.get("NIUSBURNER_VERBOSE", "") in {"1", "true", "TRUE"}


def _out(stream: TextIO | None = None) -> TextIO:
    return stream or sys.stdout


def _rewritable(stream: TextIO) -> bool:
    """True when a line can be redrawn in place.

    Only a real terminal. The IDE panel turns a carriage return into a line
    break, which would print one line per byte programmed.
    """
    if os.environ.get("NO_COLOR"):
        return False
    return hasattr(stream, "isatty") and stream.isatty()


def human_time(seconds: float) -> str:
    if seconds < 0 or seconds != seconds:          # negative or NaN
        return "--:--"
    seconds = int(seconds + 0.5)
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


def _bar(percent: int) -> str:
    """The signature comet: `==============>.......`, never bracketed."""
    percent = max(0, min(100, percent))
    filled = int(round(percent * _BAR_WIDTH / 100.0))
    if filled >= _BAR_WIDTH:
        return "=" * _BAR_WIDTH
    if filled <= 0:
        return "." * _BAR_WIDTH
    return (("=" * (filled - 1)) + ">").ljust(_BAR_WIDTH, ".")


def stage(percent: int, label: str, detail: str = "",
          stream: TextIO | None = None, end: str = "\n") -> None:
    """One progress line: `  NIUS  ====>....   64%  Programming  890/1390 B`."""
    out = _out(stream)
    line = f"  NIUS  {_bar(percent)}  {max(0, min(100, percent)):3d}%  {label}"
    if detail:
        line = f"{line}  {detail}"
    out.write(line + end)
    out.flush()


#: How rarely a wait reports itself when the line cannot be redrawn. An
#: IDE panel turns a carriage return into a line break, so a countdown that
#: redraws would fill the panel with one line per tick.
_QUIET_WAIT = 30.0

_last_wait: float = 0.0


def waiting(label: str, detail: str, stream: TextIO | None = None) -> None:
    """A wait that reports itself without filling the screen.

    On a terminal the line is redrawn in place, so a countdown costs one
    line however long the wait runs. Where the line cannot be redrawn it
    is printed rarely instead: a carriage return becomes a line break in
    an IDE panel, and a countdown that redraws there would fill it with
    one line per tick.
    """
    global _last_wait
    out = _out(stream)
    if _rewritable(out):
        out.write(f"\r  NIUS  {_bar(0)}    0%  {label}  {detail}    ")
        out.flush()
        return
    now = time.monotonic()
    if now - _last_wait < _QUIET_WAIT:
        return
    _last_wait = now
    out.write(f"  {label}: {detail}\n")
    out.flush()


def waited(stream: TextIO | None = None) -> None:
    """Close a redrawn wait line, so what follows starts on its own."""
    global _last_wait
    _last_wait = 0.0
    out = _out(stream)
    if _rewritable(out):
        out.write("\n")
        out.flush()


def banner(subtitle: str, stream: TextIO | None = None) -> None:
    """Printed once, at the start of a run. Starts the elapsed-time clock."""
    global _start_utc
    out = _out(stream)
    out.write(BANNER_RULE + "\n")
    for line in BANNER_ART:
        out.write(line + "\n")
    out.write(BANNER_RULE + "\n")
    out.write(f"   {subtitle}\n\n")
    out.flush()
    _start_utc = time.monotonic()


def elapsed() -> str:
    if _start_utc is None:
        return ""
    return f"{time.monotonic() - _start_utc:.1f}s"


def complete(label: str = "Upload complete", *rows: str,
             stream: TextIO | None = None) -> None:
    """The closing summary: the full bar, then plain-language status lines."""
    out = _out(stream)
    stage(100, label, stream=out)
    out.write("\n")
    spent = elapsed()
    if spent:
        out.write(f"  Total upload time : {spent}\n")
    for row in rows:
        if row:
            out.write(f"  {row}\n")
    out.write("\n")
    out.flush()


def note(text: str, stream: TextIO | None = None) -> None:
    """An internal detail. Suppressed unless verbose, exactly as upstream."""
    if not verbose():
        return
    out = _out(stream)
    out.write(f"[nius] {text}\n")
    out.flush()


def info(text: str, stream: TextIO | None = None) -> None:
    """A short line the operator should see even in quiet mode."""
    out = _out(stream)
    out.write(f"  {text}\n")
    out.flush()


def error(summary: str, *, title: str = "upload failed",
          hints: tuple[str, ...] = (), details: tuple[str, ...] = (),
          stream: TextIO | None = None) -> None:
    """The failure block: a dashed rule, the reason, then hints and trace."""
    out = _out(stream)
    out.write(_FAIL_RULE + "\n")
    out.write(f"[nius][fail] {title}\n")
    out.write(f" reason: {summary}\n")
    if hints:
        out.write(" hints:\n")
        for hint in hints:
            if hint:
                out.write(f"  - {hint}\n")
    if details:
        out.write(" trace:\n")
        for detail in details:
            if detail:
                out.write(f"  > {detail}\n")
    out.write(_FAIL_RULE + "\n")
    out.flush()


class Progress:
    """One phase of work with a known number of steps.

    Emits the signature bar. On a terminal the line is rewritten in place;
    anywhere else it prints at ten-percent milestones, so an IDE panel gets
    a readable handful of lines instead of one per byte.
    """

    def __init__(self, label: str, total: int, *,
                 stream: TextIO | None = None, unit: str = "B") -> None:
        self.label = label
        self.total = max(0, int(total))
        self.unit = unit
        self.stream = _out(stream)
        self.live = _rewritable(self.stream)
        self.count = 0
        self.started = time.monotonic()
        self._last_drawn = -1.0
        self._mark = -1
        self._closed = False
        self._draw(force=True)

    # -- drawing ---------------------------------------------------------

    def _fraction(self) -> float:
        return 1.0 if not self.total else min(1.0, self.count / self.total)

    def _detail(self, fraction: float) -> str:
        counts = f"{self.count}/{self.total} {self.unit}" if self.total else ""
        eta = ""
        if 0 < fraction < 1:
            spent = time.monotonic() - self.started
            eta = f"  ETA {human_time(spent / fraction - spent)}"
        return f"{counts}{eta}"

    def _draw(self, force: bool = False) -> None:
        if self._closed:
            return
        fraction = self._fraction()
        percent = int(fraction * 100)
        if not self.live:
            # done() prints the only 100% line, so the last milestone would
            # just repeat it one line earlier.
            if percent >= 100 and not force:
                return
            mark = percent // _QUIET_STEP
            if not force and mark <= self._mark:
                return
            self._mark = mark
            stage(percent, self.label, self._detail(fraction), self.stream)
            return
        now = time.monotonic()
        if not force and now - self._last_drawn < 0.08:
            return
        self._last_drawn = now
        stage(percent, self.label, self._detail(fraction) + "   ",
              self.stream, end="\r")

    # -- api -------------------------------------------------------------

    def step(self, n: int = 1) -> None:
        self.count += n
        self._draw()

    def set(self, count: int) -> None:
        self.count = count
        self._draw()

    def done(self, note_text: str = "") -> None:
        if self._closed:
            return
        self.count = self.total
        spent = time.monotonic() - self.started
        detail = f"{self.total} {self.unit} in {spent:.1f}s" if self.total else ""
        if note_text:
            detail = f"{detail}  {note_text}" if detail else note_text
        if self.live:
            self.stream.write("\r")
        stage(100, self.label, detail, self.stream)
        self._closed = True

    def fail(self, reason: str) -> None:
        if self._closed:
            return
        if self.live:
            self.stream.write("\r")
        stage(int(self._fraction() * 100), self.label, f"FAILED  {reason}",
              self.stream)
        self._closed = True

    def __enter__(self) -> "Progress":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if exc_type is None:
            self.done()
        else:
            self.fail(str(exc) or exc_type.__name__)


class Spinner:
    """A phase whose length is not known ahead of time, such as chip erase.

    Upstream keeps its pulse verbose-only, because in quiet mode the
    milestone lines are enough and a spinner just fills the IDE panel. Same
    here: one line at the start, one at the end, and animation only on a
    terminal.
    """

    FRAMES = ("[-]", "[\\]", "[|]", "[/]")

    def __init__(self, label: str, *, stream: TextIO | None = None) -> None:
        self.label = label
        self.stream = _out(stream)
        self.live = _rewritable(self.stream)
        self.started = time.monotonic()
        self._frame = 0
        self._closed = False
        if not self.live:
            stage(0, self.label, "working", self.stream)

    def tick(self) -> None:
        if self._closed or not self.live:
            return
        self._frame += 1
        spent = time.monotonic() - self.started
        stage(0, self.label,
              f"{self.FRAMES[self._frame % len(self.FRAMES)]} {spent:4.1f}s  ",
              self.stream, end="\r")

    def done(self, note_text: str = "") -> None:
        if self._closed:
            return
        spent = time.monotonic() - self.started
        detail = f"{spent:.1f}s"
        if note_text:
            detail = f"{detail}  {note_text}"
        if self.live:
            self.stream.write("\r")
        stage(100, self.label, detail, self.stream)
        self._closed = True

    def fail(self, reason: str) -> None:
        if self._closed:
            return
        if self.live:
            self.stream.write("\r")
        stage(0, self.label, f"FAILED  {reason}", self.stream)
        self._closed = True

    def __enter__(self) -> "Spinner":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if exc_type is None:
            self.done()
        else:
            self.fail(str(exc) or exc_type.__name__)
