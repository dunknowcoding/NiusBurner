"""Progress reporting for long operations, readable in a terminal and in an IDE.

Copyright 2026 dunknowcoding (NiusRobotLab)
SPDX-License-Identifier: Apache-2.0

Programming an 8051 over serial ISP is a byte at a time at roughly 5 ms a
byte, so a 3 KB image takes the better part of a minute. Silence for a minute
is indistinguishable from a hang, which is the actual problem this solves.

Two output shapes, chosen by asking the stream:

  a terminal      one line, rewritten in place with \\r, with a bar and an ETA
  anything else   a new line at each step, because the Arduino IDE console
                  renders \\r as a line break and would otherwise print
                  hundreds of them

Nothing here needs a package. `no_color()` also honours NO_COLOR, which the
IDE console and most CI logs want.
"""

from __future__ import annotations

import os
import sys
import time
from typing import TextIO

_BAR_WIDTH = 28
_TICK = "#"
_GAP = "."

#: Steps between lines when the output is not a terminal. Twenty lines is
#: enough to see movement and few enough to read.
_QUIET_STEPS = 20


def no_color(stream: TextIO | None = None) -> bool:
    if os.environ.get("NO_COLOR"):
        return True
    stream = stream or sys.stderr
    return not hasattr(stream, "isatty") or not stream.isatty()


class _Style:
    """ANSI, or empty strings when the stream cannot show them."""

    def __init__(self, plain: bool) -> None:
        self.dim = "" if plain else "\033[2m"
        self.bold = "" if plain else "\033[1m"
        self.green = "" if plain else "\033[32m"
        self.red = "" if plain else "\033[31m"
        self.yellow = "" if plain else "\033[33m"
        self.off = "" if plain else "\033[0m"


def human_time(seconds: float) -> str:
    if seconds < 0 or seconds != seconds:          # negative or NaN
        return "--:--"
    seconds = int(seconds + 0.5)
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


class Progress:
    """One phase of work with a known number of steps.

    Call `step()` as work completes and `done()` at the end. `done()` is safe
    to call twice, so a `finally` can close a phase an exception interrupted.
    """

    def __init__(self, label: str, total: int, *,
                 stream: TextIO | None = None, unit: str = "B") -> None:
        self.label = label
        self.total = max(0, int(total))
        self.unit = unit
        self.stream = stream or sys.stderr
        self.plain = no_color(self.stream)
        self.style = _Style(self.plain)
        self.count = 0
        self.started = time.monotonic()
        self._last_drawn = -1.0
        self._closed = False
        self._quiet_mark = 0
        self._draw(force=True)

    # -- drawing ---------------------------------------------------------

    def _bar(self, fraction: float) -> str:
        filled = int(fraction * _BAR_WIDTH)
        return _TICK * filled + _GAP * (_BAR_WIDTH - filled)

    def _line(self, fraction: float, eta: float) -> str:
        s = self.style
        pct = f"{100 * fraction:5.1f}%"
        counts = f"{self.count}/{self.total} {self.unit}" if self.total else ""
        return (
            f"  {s.bold}{self.label:<10}{s.off} "
            f"[{self._bar(fraction)}] {pct}  {counts:>16}  "
            f"{s.dim}ETA {human_time(eta)}{s.off}"
        )

    def _eta(self, fraction: float) -> float:
        if fraction <= 0:
            return float("nan")
        elapsed = time.monotonic() - self.started
        return elapsed / fraction - elapsed

    def _draw(self, force: bool = False) -> None:
        if self._closed:
            return
        fraction = 1.0 if not self.total else min(1.0, self.count / self.total)
        now = time.monotonic()
        if self.plain:
            # Only at whole steps, so an IDE console gets a readable handful
            # of lines instead of one per byte.
            mark = int(fraction * _QUIET_STEPS)
            if not force and mark <= self._quiet_mark:
                return
            self._quiet_mark = mark
            self.stream.write(self._line(fraction, self._eta(fraction)) + "\n")
            self.stream.flush()
            return
        if not force and now - self._last_drawn < 0.08:
            return
        self._last_drawn = now
        self.stream.write("\r" + self._line(fraction, self._eta(fraction)))
        self.stream.flush()

    # -- api -------------------------------------------------------------

    def step(self, n: int = 1) -> None:
        self.count += n
        self._draw()

    def set(self, count: int) -> None:
        self.count = count
        self._draw()

    def done(self, note: str = "") -> None:
        if self._closed:
            return
        self.count = self.total
        elapsed = time.monotonic() - self.started
        s = self.style
        tail = f"  {note}" if note else ""
        line = (
            f"  {s.bold}{self.label:<10}{s.off} "
            f"[{self._bar(1.0)}] {s.green}done{s.off}  "
            f"{self.total}{' ' + self.unit if self.unit else ''} in "
            f"{elapsed:.1f}s{tail}"
        )
        if self.plain:
            self.stream.write(line + "\n")
        else:
            self.stream.write("\r" + line + "\033[K\n")
        self.stream.flush()
        self._closed = True

    def fail(self, reason: str) -> None:
        if self._closed:
            return
        s = self.style
        line = f"  {s.bold}{self.label:<10}{s.off} {s.red}failed{s.off}  {reason}"
        if self.plain:
            self.stream.write(line + "\n")
        else:
            self.stream.write("\r" + line + "\033[K\n")
        self.stream.flush()
        self._closed = True

    def __enter__(self) -> "Progress":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if exc_type is None:
            self.done()
        else:
            self.fail(str(exc) or exc_type.__name__)


class Spinner:
    """A phase whose length is not known ahead of time, such as chip erase."""

    FRAMES = "|/-\\"

    def __init__(self, label: str, *, stream: TextIO | None = None) -> None:
        self.label = label
        self.stream = stream or sys.stderr
        self.plain = no_color(self.stream)
        self.style = _Style(self.plain)
        self.started = time.monotonic()
        self._frame = 0
        self._closed = False
        if self.plain:
            self.stream.write(f"  {self.label:<10} working ...\n")
            self.stream.flush()

    def tick(self) -> None:
        if self._closed or self.plain:
            return
        self._frame = (self._frame + 1) % len(self.FRAMES)
        elapsed = time.monotonic() - self.started
        s = self.style
        self.stream.write(
            f"\r  {s.bold}{self.label:<10}{s.off} "
            f"{self.FRAMES[self._frame]} {s.dim}{elapsed:4.1f}s{s.off}")
        self.stream.flush()

    def done(self, note: str = "") -> None:
        if self._closed:
            return
        elapsed = time.monotonic() - self.started
        s = self.style
        tail = f"  {note}" if note else ""
        line = (f"  {s.bold}{self.label:<10}{s.off} {s.green}done{s.off}  "
                f"{elapsed:.1f}s{tail}")
        if self.plain:
            self.stream.write(line + "\n")
        else:
            self.stream.write("\r" + line + "\033[K\n")
        self.stream.flush()
        self._closed = True

    def __enter__(self) -> "Spinner":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if exc_type is None:
            self.done()
        elif not self._closed:
            s = self.style
            self.stream.write(
                f"\r  {s.bold}{self.label:<10}{s.off} {s.red}failed{s.off}\n")
            self.stream.flush()
            self._closed = True


def banner(text: str, stream: TextIO | None = None) -> None:
    stream = stream or sys.stderr
    style = _Style(no_color(stream))
    stream.write(f"{style.bold}{text}{style.off}\n")
    stream.flush()


def note(text: str, stream: TextIO | None = None) -> None:
    stream = stream or sys.stderr
    style = _Style(no_color(stream))
    stream.write(f"  {style.dim}{text}{style.off}\n")
    stream.flush()


def error(text: str, stream: TextIO | None = None) -> None:
    stream = stream or sys.stderr
    style = _Style(no_color(stream))
    stream.write(f"{style.red}error{style.off}  {text}\n")
    stream.flush()
