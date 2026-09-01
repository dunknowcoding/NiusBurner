"""The STC8G/STC8H bootloader, spoken directly.

The later STC8 parts cannot be programmed through the general-purpose
route this package uses for the older families. That route insists on
trimming the internal RC oscillator before it will do anything else, and
these bootloaders do not answer that exchange -- so the upload stops
before a single byte of flash is written, on a part that is otherwise
answering perfectly.

The trim is not needed to program. The bootloader runs from its own
oscillator whatever the user clock is set to, so the transfer rate follows
from that and the flash can be written without touching the RC at all:

    reload = 65536 - bootloader_hz / 4 / rate

That clock is not the 24 MHz usually assumed for it. The part reports its
own, as a count of bootloader cycles per host bit period, and on an
STC8H1K08 it comes back 23.779 MHz -- the figure the vendor tool shows for
the same part, and a percent off the constant.

That leaves the RC untrimmed, which matters to the sketch and not to the
programming: a board that needs a known clock should set it from the
runtime, where the frequency is known from the catalog, rather than
depending on whatever an ISP tool happened to write.

The frame layer here was checked against a frame the part itself sent, not
against another implementation:

    length field = payload + 6, which is also the frame length minus 2
    checksum     = sum(frame[2:-3]), 16-bit, big-endian
    terminator   = 0x16

Those are what an STC8H1K08 running BSL 7.3.13U put on the wire, so the
codec below is confirmed in both directions. The command sequence is not
confirmed end to end on hardware yet, which is why the parts that use it
are marked experimental in the catalog.
"""

from __future__ import annotations

import struct
import time

#: Frame delimiters. The direction byte distinguishes the two sides.
START = b"\x46\xb9"
TO_MCU = b"\x6a"
FROM_MCU = b"\x68"
END = b"\x16"

#: The byte the bootloader listens for while it works out the host's rate.
SYNC = b"\x7f"

#: Nominal bootloader clock, used only when the status frame cannot be
#: consulted. The real one is a few percent off this and is reported by
#: the part itself -- see bootloader_hz().
BOOTLOADER_HZ = 24_000_000

#: Where the status frame carries the bootloader's clock, as a count of
#: its own cycles per host bit period.
CLOCK_COUNT = slice(13, 15)

#: Payloads, minus the reply byte each one is answered with.
PING = (0x05, 0x00, 0x00, 0x5A, 0xA5)
ERASE = (0x03, 0x00, 0x00, 0x5A, 0xA5)
WRITE_FIRST = 0x22
WRITE_NEXT = 0x02
WRITE_TAIL = (0x5A, 0xA5)
WRITE_ACK = 0x02

#: Flash is written a block at a time; the bootloader expects this size.
BLOCK = 128

#: What a status frame starts with, so it can be told from a reply.
STATUS = 0x50


class Stc8Error(Exception):
    """The bootloader said something other than what was expected."""


def build(payload) -> bytes:
    """Wrap *payload* in a host-to-MCU frame."""
    body = START + TO_MCU + struct.pack(">H", len(payload) + 6) + bytes(payload)
    return body + struct.pack(">H", sum(body[2:]) & 0xFFFF) + END


def parse(buf: bytes):
    """The first complete MCU-to-host payload in *buf*, or None.

    Scans for the frame start rather than demanding it at offset zero: the
    line carries the tail of our own transmission, and whatever noise a
    power-on left behind.
    """
    at = buf.find(START + FROM_MCU)
    if at < 0:
        return None
    frame = buf[at:]
    if len(frame) < 5:
        return None
    length, = struct.unpack(">H", frame[3:5])
    # The length field counts from the direction byte, so the frame runs to
    # length + 2. Payload ends three bytes short of that: two of checksum
    # and one of terminator.
    if length < 6 or len(frame) < length + 2:
        return None
    body = frame[:length + 2]
    stated, = struct.unpack(">H", body[-3:-1])
    if stated != sum(body[2:-3]) & 0xFFFF:
        raise Stc8Error("frame checksum mismatch")
    return body[5:-3]


def bootloader_hz(status: bytes, handshake_rate: int) -> int:
    """The bootloader's own clock, as the part reports it.

    The status frame carries a count of bootloader cycles per host bit
    period, so the clock follows from the rate the handshake ran at. On an
    STC8H1K08 this reads 2477 at 9600 baud -- 23.779 MHz, which is what
    the vendor tool displays for the same part, and nearly a percent away
    from the 24 MHz that gets assumed in its place.

    That percent matters little for a UART reload and would matter for
    anything derived from it, so it is worth taking from the part rather
    than from a constant.
    """
    if len(status) < CLOCK_COUNT.stop:
        return BOOTLOADER_HZ
    count, = struct.unpack(">H", status[CLOCK_COUNT])
    measured = count * handshake_rate
    # A wildly out-of-range count means this is not the field we think it
    # is on this part; the nominal clock is the safer answer.
    if not 16_000_000 <= measured <= 40_000_000:
        return BOOTLOADER_HZ
    return measured


def transfer_reload(rate: int, clock_hz: int = BOOTLOADER_HZ) -> int:
    """The UART reload the bootloader wants for *rate*.

    Derived from the bootloader's own clock, which is why no oscillator
    trimming is involved.
    """
    value = 65536 - (clock_hz // 4) // rate
    if not 0 < value < 65536:
        raise Stc8Error(f"no reload for {rate} baud")
    return value


def baud_switch(status: bytes, rate: int, handshake_rate: int = 0) -> tuple:
    """The payload that moves the session to *rate*.

    The two zero bytes are where an oscillator trim would go. Leaving them
    zero is what "do not touch the RC" looks like on the wire.
    """
    if len(status) < 5:
        raise Stc8Error("status frame too short to switch rate")
    clock = (bootloader_hz(status, handshake_rate) if handshake_rate
             else BOOTLOADER_HZ)
    reload_value = transfer_reload(rate, clock)
    return (0x01, status[4], 0x40,
            (reload_value >> 8) & 0xFF, reload_value & 0xFF,
            0x00, 0x00, 0x97)


def write_blocks(image: bytes):
    """Split *image* into the frames that write it, in order."""
    opcode = WRITE_FIRST
    for addr in range(0, len(image), BLOCK):
        chunk = image[addr:addr + BLOCK]
        head = (opcode, (addr >> 8) & 0xFF, addr & 0xFF) + WRITE_TAIL
        yield addr, bytes(head) + chunk
        opcode = WRITE_NEXT


class Session:
    """One bootloader conversation, over an already-open serial port."""

    def __init__(self, ser, reply_timeout: float = 3.0,
                 sync_run: int = 1, sync_gap: float = 0.03):
        self.ser = ser
        self.reply_timeout = reply_timeout
        #: Sync bytes per burst, and the quiet time after each burst.
        self.sync_run = sync_run
        self.sync_gap = sync_gap
        self.status = None

    def sync(self, timeout: float):
        """Stream the sync byte until the bootloader identifies itself.

        Two things pull in opposite directions here, so both are settable.

        A gap between bytes gives the part a quiet window to answer in,
        and that is what makes the handshake reliable -- spaced bytes have
        synced this hardware every time it was asked, and a continuous
        stream did not.

        Against that, the gap decides how much of the time the line is
        held low, which matters on a board where the part is fed through
        that same line by a clamp diode. 0x7f is low for two bit times in
        ten, so back-to-back bytes hold the rail down a fifth of the time
        while a byte every 30 ms holds it down well under one percent. On
        such a board, with nothing else pulling the supply down, it never
        falls far enough for restoring it to be a power-on reset.

        The defaults favour the handshake, because a board that cannot
        drop its own rail has a better answer available: hold a break to
        drop it, which is a power cut rather than a duty cycle.
        """
        run = SYNC * self.sync_run
        buf = b""
        started = time.monotonic()
        while time.monotonic() - started < timeout:
            self.ser.write(run)
            self.ser.flush()
            if self.sync_gap:
                time.sleep(self.sync_gap)
            buf += self.ser.read(512)
            try:
                payload = parse(buf)
            except Stc8Error:
                buf = b""
                continue
            if payload and payload[0] == STATUS:
                self.status = payload
                return payload
            if len(buf) > 4096:
                buf = buf[-512:]
        return None

    def command(self, payload, expect: int, what: str) -> bytes:
        """Send one frame and require the reply that says it landed."""
        self.ser.reset_input_buffer()
        self.ser.write(build(payload))
        self.ser.flush()
        buf = b""
        deadline = time.monotonic() + self.reply_timeout
        while time.monotonic() < deadline:
            buf += self.ser.read(256)
            try:
                reply = parse(buf)
            except Stc8Error as exc:
                raise Stc8Error(f"{what}: {exc}") from None
            if not reply:
                continue
            if reply[0] != expect:
                raise Stc8Error(
                    f"{what}: expected {expect:02X}, got {reply[:4].hex()}")
            return reply
        raise Stc8Error(f"{what}: no reply")
