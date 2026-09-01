"""The STC8G/STC8H bootloader, spoken directly.

The later STC8 parts cannot be programmed through the general-purpose
route this package uses for the older families. That route insists on
trimming the internal RC oscillator before it will do anything else, and
these bootloaders do not answer that exchange -- so the upload stops
before a single byte of flash is written, on a part that is otherwise
answering perfectly.

The trim is not needed to program. The bootloader runs from its own fixed
24 MHz whatever the user clock is set to, so the transfer rate can be
derived from that constant and the flash written without touching the
oscillator at all:

    reload = 65536 - 24_000_000 / 4 / rate

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

#: The bootloader's own clock during programming. Not the user clock, and
#: not affected by whether the RC has ever been trimmed.
BOOTLOADER_HZ = 24_000_000

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


def transfer_reload(rate: int) -> int:
    """The UART reload the bootloader wants for *rate*.

    Derived from the bootloader's fixed clock, which is why no oscillator
    trimming is involved.
    """
    value = 65536 - (BOOTLOADER_HZ // 4) // rate
    if not 0 < value < 65536:
        raise Stc8Error(f"no reload for {rate} baud")
    return value


def baud_switch(status: bytes, rate: int) -> tuple:
    """The payload that moves the session to *rate*.

    The two zero bytes are where an oscillator trim would go. Leaving them
    zero is what "do not touch the RC" looks like on the wire.
    """
    if len(status) < 5:
        raise Stc8Error("status frame too short to switch rate")
    reload_value = transfer_reload(rate)
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

    def __init__(self, ser, reply_timeout: float = 3.0):
        self.ser = ser
        self.reply_timeout = reply_timeout
        self.status = None

    def sync(self, timeout: float):
        """Pulse until the bootloader identifies itself."""
        buf = b""
        started = time.monotonic()
        while time.monotonic() - started < timeout:
            self.ser.write(SYNC)
            self.ser.flush()
            time.sleep(0.03)
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
