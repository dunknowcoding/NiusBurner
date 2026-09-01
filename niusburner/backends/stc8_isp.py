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
STC8H1K08 it comes back near 23.8 MHz -- close to what the vendor tool
shows for the same part, and a percent off the constant. The reading moves
by a few kHz between handshakes, which is what a count of whole cycles
against a host bit period will do.

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

One reason it is hard to confirm is worth writing down, because it looks
like a protocol fault and is not. A board that takes its supply from the
serial line rather than from its own regulator is fed only while that line
is idle. A sync byte is high nine tenths of the time and such a board
handshakes perfectly; a command frame is low well over half the time, and
on one measured board that collapses the supply before the frame ends. The
part then restarts into its application, and the session reads as a
bootloader that answered the handshake and ignored every command. Nothing
in the exchange below can fix that -- the board has to be on its own
supply while it is programmed.
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

#: Sent once the last block has gone out. Bootloaders from 7.2 on expect
#: it, and without it the blocks that went before are not committed.
WRITE_FINISH = (0x07, 0x00, 0x00, 0x5A, 0xA5)
WRITE_FINISH_ACK = 0x07

#: Second byte of a write acknowledgement, for a block and for the finish
#: alike. The opcode alone comes back on a refusal too, so both are checked.
WRITE_OK = 0x54

#: Flash is written a block at a time; the bootloader expects this size.
BLOCK = 128

#: The rate the handshake runs at. Low rates give the bootloader a longer
#: pulse to measure, but this part does not answer below 4800 at all, and
#: 9600 has synced it on every attempt.
HANDSHAKE_BAUD = 9600

#: The rate the session moves to once the bootloader agrees to it.
TRANSFER_BAUD = 115200

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
    STC8H1K08 this reads about 2475 at 9600 baud -- near 23.8 MHz, which is
    close to what the vendor tool displays for the same part, and nearly a
    percent away from the 24 MHz that gets assumed in its place.

    That percent matters little for a UART reload and would matter for
    anything derived from it, so it is worth taking from the part rather
    than from a constant.

    The count is whole cycles per host bit period, so a slow handshake
    measures the clock finely and a fast one coarsely: the same part reads
    23.779 MHz when the handshake ran at 9600 and 24.077 MHz when it ran at
    115200, purely because the second count is a twelfth the size. Handshake
    low, then change rate.
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
    """Split *image* into the frames that write it, in order.

    A final block shorter than the rest is padded, because the bootloader
    writes what it is sent and an unpadded tail leaves the frame short of
    the length it works from. The length padded to is the one the reference
    implementation uses, which counts from the block size and the three
    header bytes it had before the two-byte tail was added to it -- an odd
    figure, but the one these bootloaders have been fed for years, and not
    something to improve on without a part to try it against.
    """
    opcode = WRITE_FIRST
    for addr in range(0, len(image), BLOCK):
        chunk = image[addr:addr + BLOCK]
        head = (opcode, (addr >> 8) & 0xFF, addr & 0xFF) + WRITE_TAIL
        frame = bytes(head) + chunk
        if len(frame) < BLOCK + 3:
            frame += b"\x00" * (BLOCK + 3 - len(frame))
        yield addr, frame
        opcode = WRITE_NEXT


class Session:
    """One bootloader conversation, over an already-open serial port."""

    def __init__(self, ser, reply_timeout: float = 3.0,
                 sync_run: int = 1, sync_gap: float = 0.03,
                 reply_quiet: float = 0.08):
        self.ser = ser
        self.reply_timeout = reply_timeout
        #: Sync bytes per burst, and the quiet time after each burst.
        self.sync_run = sync_run
        self.sync_gap = sync_gap
        #: How long to keep listening, writing nothing, once a reply has
        #: started to arrive. Long enough for the slowest frame to finish.
        self.reply_quiet = reply_quiet
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
        such a board a fifth is already too much -- measured on one, a
        run of thirteen sync bytes back to back resets the part, and the
        same thirteen spaced out does not.

        The defaults favour the handshake, because a board that cannot
        drop its own rail has a better answer available: hold a break to
        drop it, which is a power cut rather than a duty cycle.

        The writing also has to stop the moment the part starts answering.
        A sync byte is how the bootloader is asked what it is, and once it
        has said so it is waiting to be told what to do -- at which point a
        further sync byte is not a question but a malformed command. The
        status frame takes tens of milliseconds to arrive, so a loop that
        keeps to its timer sends two or three more bytes into the gap. Both
        reference implementations go quiet here, and so does this.
        """
        run = SYNC * self.sync_run
        started = time.monotonic()
        while time.monotonic() - started < timeout:
            self.ser.write(run)
            self.ser.flush()
            if self.sync_gap:
                time.sleep(self.sync_gap)
            buf = self.ser.read(512)
            if not buf:
                continue
            # Something is coming back; read the rest of it in silence.
            quiet = time.monotonic() + self.reply_quiet
            while time.monotonic() < quiet:
                more = self.ser.read(512)
                if more:
                    buf += more
                    quiet = time.monotonic() + self.reply_quiet
                try:
                    payload = parse(buf)
                except Stc8Error:
                    buf = b""
                    break
                if payload and payload[0] == STATUS:
                    self.status = payload
                    return payload
        return None

    def command(self, payload, expect: int, what: str,
                expect_ok: int = None) -> bytes:
        """Send one frame and require the reply that says it landed.

        A write is answered with its opcode and a second byte that
        distinguishes "done" from "refused", so *expect_ok* is checked too
        where there is one.
        """
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
            if expect_ok is not None and (len(reply) < 2
                                          or reply[1] != expect_ok):
                raise Stc8Error(
                    f"{what}: the part answered but did not confirm, "
                    f"{reply[:4].hex()}")
            return reply
        raise Stc8Error(f"{what}: no reply")


def program(port: str, image: bytes, handshake: int = HANDSHAKE_BAUD,
            transfer: int = TRANSFER_BAUD, wait: float = 120.0,
            announce=None) -> None:
    """Sync, then erase and write *image*, over a port opened here.

    Raises Stc8Error if the part does not answer, so a caller can report
    the step that failed rather than a return code.
    """
    import serial

    def say(text):
        if announce is not None:
            announce(text)

    ser = serial.Serial()
    ser.port, ser.baudrate = port, handshake
    ser.parity = serial.PARITY_NONE
    ser.timeout = 0.05
    ser.open()
    try:
        session = Session(ser)
        status = session.sync(wait)
        if status is None:
            raise Stc8Error(
                "the bootloader did not answer; it is entered on power-on "
                "only, so the supply has to be interrupted while this waits")
        clock = bootloader_hz(status, handshake)
        say("part reports %.3f MHz for its own clock" % (clock / 1e6))

        # The rate change is acknowledged at the old rate, and the host
        # moves only once that answer is in. Handshaking again at the new
        # rate would look like a confirmation and is not one: the
        # bootloader measures the host's rate from every sync byte it is
        # sent, so it answers a handshake at whatever rate one arrives at,
        # whether it took the reload or never saw the frame at all.
        try:
            session.command(baud_switch(status, transfer, handshake), 0x01,
                            "rate change")
        except Stc8Error as exc:
            raise Stc8Error(
                f"{exc}. The handshake worked, so the part is there and "
                "listening; a first command that draws nothing usually "
                "means the board is not on a supply of its own while it "
                "is being programmed") from None
        ser.baudrate = transfer
        say("running at %d baud" % transfer)

        erased = session.command(ERASE, 0x03, "erase")
        # The erase is what returns the part's unique id; nothing else does.
        if len(erased) >= 8:
            say("erased, target id %s" % erased[1:8].hex())
        else:
            say("erased")

        for addr, frame in write_blocks(image):
            session.command(frame, WRITE_ACK, "write at %04X" % addr,
                            WRITE_OK)
        session.command(WRITE_FINISH, WRITE_FINISH_ACK, "finish writing",
                        WRITE_OK)
        say("wrote %d bytes" % len(image))
    finally:
        ser.close()
