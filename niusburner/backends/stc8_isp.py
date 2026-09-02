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

    reload = 65536 - 24_000_000 / 4 / rate

The 24 MHz there is nominal and must stay nominal. The part also reports a
clock of its own, as a count of bootloader cycles per host bit period, and
on an STC8H1K08 that comes back near 23.9 MHz. Substituting it is the
obvious refinement and it does not work: at 115200 it yields 0xFFCD where
the bootloader wants 0xFFCC, and a bootloader sent the refined value
answers nothing at all -- not the rate change, not anything after it. The
count measures the host's bit period; it is not a statement about the
bootloader's baud generator, which runs from the nominal clock.

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
codec below is confirmed in both directions. The sequence has since
programmed that part end to end -- handshake, rate change, erase, blocks,
finish -- in about a second.

Two things had to be right before any of it worked, and both fail in the
same silent way. This bootloader does not refuse a frame it dislikes; it
says nothing at all and then starts the application, which reads as a part
that answers the handshake and ignores every command. There is no NAK to
look at and no error to report, so a wrong line setting and a wrong
constant are indistinguishable from a dead part. The two are PARITY and
the reload constant in baud_switch, and each is written up where it lives.

A third thing looks like the same fault and is not. A board that takes its
supply from the serial line rather than from its own regulator is fed only
while that line is idle. A sync byte is high nine tenths of the time and
such a board handshakes perfectly; a command frame is low well over half
the time, and on one measured board that collapses the supply before the
frame ends -- so it restarts into its application, again looking exactly
like a refused command. Nothing in the exchange below can fix that: the
board has to be on its own supply while it is programmed. Worth knowing
because it makes every measurement taken on that supply worthless, which
is a trap this file's history fell into repeatedly.
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

#: The last byte of the rate-change frame, which is an IAP wait-state
#: setting and is a constant per generation rather than anything derived.
#: The STC8G and STC8H want 0x97; the STC15 family wants 0xC3. Everything
#: else about the exchange is the same for both, which is why one handler
#: covers them.
IAP_WAIT = {"stc8g": 0x97, "stc8d": 0x81, "stc15": 0xC3}

#: Where each generation reports the oscillator it is trimmed to. Read for
#: display only; nothing is derived from it -- see bootloader_hz.
FOSC_AT = {"stc8g": slice(1, 5), "stc8d": slice(1, 5), "stc15": slice(8, 12)}

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

#: Leave the bootloader and start what was just written.
#:
#: Without this the part sits in its bootloader after a successful upload,
#: having written the flash and never run it, and stays silent until its
#: power is cycled by hand. Which looks exactly like an upload that wrote
#: nothing -- and cost a good while here being investigated as one.
#:
#: It is not acknowledged and cannot be: the part stops being a bootloader
#: as it obeys. So this is sent and not waited for, and whether it worked
#: is answered by the sketch starting to talk.
RUN = (0xFF,)

#: Flash is written a block at a time; the bootloader expects this size.
BLOCK = 128

#: How a frame is paced on a retry, after a command went unanswered.
#:
#: A UART does not care how long the gaps between bytes are, so the same
#: frame can be delivered in pieces with the line left idle between them.
#: On a board supplied through that line, this is the difference between a
#: frame that is half a gap in its supply and one that is not.
#:
#: Whether it is enough is not established. On the one board measured, with
#: its supply switched out, the handshake succeeded on every power-on at
#: 4800 and above and no command was ever answered -- at four rates, paced
#: and solid, forty-eight attempts. Pacing did not rescue that; nothing in
#: this file will, because the part cannot complete a command it has no
#: power to run. It is kept because it costs nothing when it is not needed
#: and is the only thing left to vary on a supply that is merely marginal
#: rather than absent.
#:
#: Off until a command actually goes unanswered.
PACED_CHUNK = 8
PACED_GAP = 0.002

#: Even parity, for the whole session including the handshake.
#:
#: This is easy to get wrong and hard to notice, because the sync byte
#: hides it: 0x7f carries seven ones, so its even-parity bit is 1, which is
#: the level a no-parity stop bit already holds. The two settings put an
#: identical waveform on the wire for that one byte. So a session with no
#: parity handshakes perfectly, reads the status frame, and then has every
#: command frame it sends rejected -- which reads as a bootloader that
#: answers the handshake and ignores commands, rather than as a line
#: setting. Measured on an STC8H1K08: with this, the rate change is
#: acknowledged and the part programs; without it, nothing is ever
#: answered, at any rate and on any supply.
PARITY = "E"

#: The rate the handshake runs at. Low rates give the bootloader a longer
#: pulse to measure, and 2400 is what has programmed this part end to end,
#: both here and through the vendor tool. Higher rates sync too. An earlier
#: note here said the part does not answer below 4800; that was measured on
#: a board taking its supply from the serial line, where a 2400-baud sync
#: byte holds that line low for the best part of a millisecond and empties
#: the rail. It was measuring the supply, not the bootloader.
HANDSHAKE_BAUD = 2400

#: The rates the wait cycles through while looking for a power-on.
#:
#: One rate is not enough, because the best rate depends on where the board
#: gets its power and the wait cannot know that yet. A slow sync byte gives
#: the bootloader a longer pulse to measure, which is why 2400 is what
#: programs this part from its own supply. But a slow sync byte also holds
#: the line low for longer -- 0.83 ms at 2400 against 0.21 ms at 9600 --
#: and on a board fed through that line, the line is the supply. Measured
#: on one: at 2400 not one power-on in twelve was ever answered, and at
#: 4800 and above, twelve out of twelve. So the wait tries both rather than
#: pick one and be wrong about half the boards.
HANDSHAKE_RATES = (2400, 9600)

#: The rate the session moves to once the bootloader agrees to it.
TRANSFER_BAUD = 115200

#: What a status frame starts with, so it can be told from a reply.
STATUS = 0x50

#: Where the status frame carries the part's identity.
MAGIC = slice(20, 22)


def part_name(status: bytes):
    """The part the status frame says this is, or None if unrecognised.

    Read from the carried device table, so a part the table does not know
    returns None rather than a guess. An unrecognised part is not an error
    in itself -- the table is a copy and parts outlive copies -- so the
    caller decides what to make of it.
    """
    if len(status) < MAGIC.stop:
        return None
    magic, = struct.unpack(">H", status[MAGIC])
    try:
        from ..vendor.stcgal.models import MCUModelDatabase
        return MCUModelDatabase.find_model(magic).name
    except Exception:
        return None


def check_part(status: bytes, expected: str):
    """Refuse to program a part that is not the one the board says it is.

    The parts in a family answer the same protocol and differ in how much
    flash they have, so programming the wrong one succeeds and then behaves
    strangely -- or overruns the flash and does not, with nothing to say
    why. STC's own tool refuses this outright and it is right to.

    Names are compared without case. An unrecognised magic passes, since
    the table here is a copy of one that will always be behind.
    """
    if not expected:
        return
    found = part_name(status)
    if found is None or found.upper() == expected.upper():
        return
    magic, = struct.unpack(">H", status[MAGIC])
    raise Stc8Error(
        f"this is an {found} (magic {magic:04X}), and the board selected is "
        f"{expected.upper()}. Programming it as the wrong part writes the "
        "wrong amount of flash and configures the wrong clock, so nothing "
        "is written; select the right board and upload again")


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

    This is reported, and nothing is derived from it. Deriving the UART
    reload from it is wrong -- see baud_switch, where using it instead of
    the nominal clock stops the bootloader answering at all.

    It is also coarse. The count is whole cycles per host bit period, so a
    slow handshake measures finely and a fast one badly: the same part
    reads 23.779 MHz from a handshake at 9600 and 24.077 MHz from one at
    115200, purely because the second count is a twelfth the size. It is
    worth printing and not worth computing with.
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


def baud_switch(status: bytes, rate: int,
                protocol: str = "stc8g") -> tuple:
    """The payload that moves the session to *rate*.

    The two zero bytes are where an oscillator trim would go. Leaving them
    zero is what "do not touch the RC" looks like on the wire.

    For the STC15 family the two implementations this was checked against
    disagree, and only one of them can be tried here. stc8prog sends this
    exact frame with 0xC3 as the last byte and the same nominal 24 MHz
    reload, and trims nothing. stcgal instead runs a calibration exchange
    first and puts the resulting programming-frequency trim in those two
    bytes, with a reload worked out from 22.1184 MHz. The form here follows
    stc8prog, because trimming is the thing this path exists to avoid: it
    moves the part's clock away from the frequency the runtime was built
    for. If an STC15 does not answer this, the reload constant is the first
    thing to change and 22118400 is the number to try -- on this bootloader
    a wrong reload is answered with silence rather than a refusal, so it
    will look like the part is not there.

    The reload comes from the nominal 24 MHz and not from the clock the
    part reports for itself, which looks like the worse choice and is not.
    Deriving it from the reported figure puts the value one count out at
    115200 -- 0xFFCD where the bootloader wants 0xFFCC -- and a bootloader
    sent the derived value does not answer at all, while the nominal one is
    acknowledged at once. That was measured on an STC8H1K08 running BSL
    7.3.13U by putting this frame beside the same frame from a working
    implementation: the reload byte and the checksum that follows it were
    the only difference between a session that programmed the part and one
    that got silence.

    So the reported count is a measurement of the host's bit period, not a
    statement that the bootloader's own baud generator runs from anything
    other than its nominal clock. There is deliberately no parameter here
    for supplying a measured clock, because there is nowhere it belongs.
    """
    if len(status) < 5:
        raise Stc8Error("status frame too short to switch rate")
    reload_value = transfer_reload(rate, BOOTLOADER_HZ)
    return (0x01, status[4], 0x40,
            (reload_value >> 8) & 0xFF, reload_value & 0xFF,
            0x00, 0x00, IAP_WAIT.get(protocol, IAP_WAIT["stc8g"]))


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
                 reply_quiet: float = 0.08,
                 write_chunk: int = 0, write_gap: float = 0.0):
        self.ser = ser
        self.reply_timeout = reply_timeout
        #: Sync bytes per burst, and the quiet time after each burst.
        self.sync_run = sync_run
        self.sync_gap = sync_gap
        #: How long to keep listening, writing nothing, once a reply has
        #: started to arrive. Long enough for the slowest frame to finish.
        self.reply_quiet = reply_quiet
        #: Bytes per write and the idle time after each. Zero sends a frame
        #: whole, which is right for a board that has its own supply.
        self.write_chunk = write_chunk
        self.write_gap = write_gap
        self.status = None

    def send(self, data: bytes) -> None:
        """Put *data* on the line, in pieces if this session is paced."""
        if not self.write_chunk:
            self.ser.write(data)
            self.ser.flush()
            return
        for at in range(0, len(data), self.write_chunk):
            self.ser.write(data[at:at + self.write_chunk])
            self.ser.flush()
            if self.write_gap:
                time.sleep(self.write_gap)

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
        self.send(build(payload))
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


#: How the wait for a power-on is paced.
#:
#: The difficulty is that the supply is a switch under somebody's hand, and
#: the two things the wait must do used to be in opposite phases. It has to
#: hold the line low, because on a board fed through that line an idle line
#: is a powered board -- switching its supply out while the line is idle
#: turns nothing off, and switching it back in is a step in voltage rather
#: than a power-on. And it has to be listening, because the bootloader
#: waits only about a second after a power-on before running the
#: application, and that clock starts when the supply returns.
#:
#: Splitting those into phases makes both of them wrong some of the time: a
#: flick landing in a listening phase drains nothing, and a flick landing
#: in a long low phase spends the window before anyone listens. Adjusting
#: the split trades one failure for the other.
#:
#: They are not actually opposed. A sync byte is 0x7f, low for two bit
#: times in ten, and sent back to back that is a fifth of the time -- which
#: is measurably enough to hold such a board down. So streaming the sync
#: byte continuously drains the rail *and* handshakes, and the listening
#: phase is a draining phase. Nothing can land in the wrong one, a flick of
#: any length is covered, and a power-on is answered within a byte time
#: rather than within a phase.
#:
#: The short break each cycle is belt and braces: a fifth of the time low
#: is enough on the board measured, and a solid low is enough on any board.
#: It is kept far below the window it is spent from.
DRAIN_SECONDS = 0.35
LISTEN_SECONDS = 0.45

#: How long to wait for the rate change to be acknowledged.
#:
#: Short, because it is answered in milliseconds when it is answered at
#: all, and every second spent waiting for an answer that is not coming is
#: a second not spent watching for a power-on. On a board whose supply is a
#: switch under somebody's hand that matters: the handshake succeeds
#: through the leakage while the switch is out, this command then goes
#: unanswered, and if the switch is put back during the wait for it, the
#: bootloader's second of listening passes unseen. Three seconds of
#: patience here made that the likely outcome rather than a rare one.
RATE_TIMEOUT = 0.6

#: How long a read waits between sync bytes while waiting for a power-on.
#: Short, so a byte goes out often and a part that has just come up is
#: answered promptly rather than up to a port timeout later.
STREAM_READ = 0.01

#: How often the wait says it is still waiting.
NOTICE_SECONDS = 5.0

#: Quiet time after the rate change, before anything is sent at the new
#: rate. The part reconfigures its own UART on being told to switch, and a
#: frame sent into that gap is simply lost -- which shows up as the next
#: command going unanswered rather than as anything to do with the rate.
RATE_SETTLE = 0.02

#: A whole-chip erase is the one step that can take seconds rather than
#: milliseconds, so it gets its own patience.
ERASE_TIMEOUT = 20.0


def await_bootloader(ser, session, wait: float, say, tick=None,
                     rates=HANDSHAKE_RATES) -> bytes:
    """Sit until the board is powered on, then return its status frame.

    This bootloader is entered on power-on and on nothing else, so the wait
    is the whole interface: there is no reset line to pull and no command
    that gets back into it. Three things decide whether the power-on is
    seen at all.

    It holds TX low between listening windows. That looks pointless and is
    not. A board fed through the serial line by a clamp diode is not off
    when its supply is switched out -- an idle-high TX keeps it running --
    so switching the supply back in raises the rail rather than starting
    it, and no reset happens. Holding the line low empties the rail, which
    is what makes the supply coming back a power-on. A board with a supply
    of its own ignores the low phase entirely, so this costs nothing there.

    It listens in short windows, for the reason given at LISTEN_SECONDS.

    And it cycles through *rates*, for the reason given at HANDSHAKE_RATES:
    the rate that suits a board on its own supply is the one that cannot
    start a board fed from the line.

    And it says so while it waits. A wait that prints nothing cannot be
    told from one that has died, which wastes the time of whoever is stood
    at the board wondering whether to try again. *tick* is called with the
    seconds remaining, and once with None when the wait is over, so a
    caller can redraw one line rather than print a column of them.
    """
    deadline = time.monotonic() + wait
    spoken = 0.0
    turn = 0
    choices = tuple(rates) or (ser.baudrate,)
    while time.monotonic() < deadline:
        ser.baudrate = choices[turn % len(choices)]
        turn += 1
        ser.break_condition = True
        until = time.monotonic() + DRAIN_SECONDS
        while time.monotonic() < until:
            ser.read(64)
        ser.break_condition = False
        ser.reset_input_buffer()

        # Stream the sync byte rather than spacing it out: while waiting,
        # the stream is what holds a line-fed board down, and it answers a
        # power-on within a byte time. The spaced cadence is for talking to
        # a part that is already awake.
        #
        # Streaming means enough bytes per write to cover the read that
        # follows it. Clearing the gap alone does not: the read blocks for
        # the port's timeout, so one byte per write is one byte every 50 ms
        # -- two percent of the time low, where a fifth is wanted and is
        # what the drain argument rests on. The run is sized to the rate so
        # the line stays busy at any of them.
        # Sync bytes go out singly and often -- not in runs.
        #
        # A run would hold the line lower for longer, which is what the
        # rail wants, and this bootloader does not answer it: spaced bytes
        # have synced this hardware every time it was asked and a
        # continuous stream has not. Sending runs to improve the duty
        # stopped the handshake working at all, which is a poor trade for a
        # drain that the low phase already provides.
        #
        # So the listening phase listens, the low phase drains, and the
        # only thing tuned here is how often a single byte goes out: often
        # enough to answer a power-on promptly, spaced enough to be heard.
        spacing, runs = session.sync_gap, session.sync_run
        patience = ser.timeout
        session.sync_gap = 0.0
        session.sync_run = 1
        ser.timeout = STREAM_READ
        try:
            status = session.sync(LISTEN_SECONDS)
        finally:
            session.sync_gap, session.sync_run = spacing, runs
            ser.timeout = patience
        if status is not None:
            return status

        now = time.monotonic()
        if now - spoken >= NOTICE_SECONDS:
            spoken = now
            left = max(0.0, deadline - now)
            if tick is not None:
                tick(left)
            else:
                say("still waiting for handshake, %ds left" % int(left))
    if tick is not None:
        tick(None)
    return None


def _one_pass(ser, session, status, image, handshake, transfer,
              say, step, protocol: str = "stc8g") -> None:
    """Rate change, erase and write, on a bootloader already handshaken.

    Raises Stc8Error at the first unanswered frame. Everything here is
    restartable: the caller can run it again from a fresh power-on, and it
    erases before it writes, so a pass interrupted halfway leaves nothing
    the next pass has to reason about.
    """
    patience = session.reply_timeout

    # The rate change is acknowledged at the old rate, and the host moves
    # only once that answer is in. Handshaking again at the new rate would
    # look like a confirmation and is not one: the bootloader measures the
    # host's rate from every sync byte it is sent, so it answers a
    # handshake at whatever rate one arrives at, whether it took the
    # reload or never saw the frame at all.
    session.reply_timeout = RATE_TIMEOUT
    try:
        session.command(baud_switch(status, transfer, protocol), 0x01,
                        "rate change")
    finally:
        session.reply_timeout = patience
    ser.baudrate = transfer
    # The part has to reconfigure its own UART before it can hear anything
    # at the new rate, and a frame sent into that gap is lost.
    time.sleep(RATE_SETTLE)
    step(20, "Link", "%d baud" % transfer)
    say("running at %d baud" % transfer)

    # Confirming the new rate before erasing is not a formality. It is the
    # first frame sent at the new rate, so it is the one that finds out
    # whether the rate change really took -- and finding that out with a
    # ping costs a frame, where finding it out with the erase means a chip
    # erased by a session that cannot then talk to it.
    session.command(PING, 0x05, "confirm the new rate")
    say("rate confirmed")

    step(30, "Erasing", "whole chip")
    session.reply_timeout = ERASE_TIMEOUT
    try:
        erased = session.command(ERASE, 0x03, "erase")
    finally:
        session.reply_timeout = patience
    # The erase is what returns the part's unique id; nothing else does.
    if len(erased) >= 8:
        say("erased, target id %s" % erased[1:8].hex())
    else:
        say("erased")

    blocks = list(write_blocks(image))
    for done, (addr, frame) in enumerate(blocks, 1):
        session.command(frame, WRITE_ACK, "write at %04X" % addr, WRITE_OK)
        written = min(done * BLOCK, len(image))
        step(30 + int(65 * done / len(blocks)), "Programming",
             "%d/%d B" % (written, len(image)))
    step(97, "Finishing", "committing the last block")
    session.command(WRITE_FINISH, WRITE_FINISH_ACK, "finish writing",
                    WRITE_OK)
    say("wrote %d bytes" % len(image))

    # Start it. The part leaves the bootloader as it obeys, so there is no
    # acknowledgement to wait for and none is expected.
    step(99, "Starting", "leaving the bootloader")
    session.send(build(RUN))
    say("started the sketch")


def identify(port: str, handshake: int = HANDSHAKE_BAUD, wait: float = 120.0,
             announce=None, progress=None, tick=None,
             expect_part: str = "") -> bytes:
    """Wait for a power-on, report what answered, and leave it running.

    The same handshake `program` opens with and nothing after it. It has to
    be its own entry point because `program` cannot stand in for it: that
    one erases the part, which is a steep price for asking what it is.

    Raises Stc8Error if nothing answers inside *wait*, so the caller can say
    which step failed rather than return a bare code.
    """
    import serial

    def say(text):
        if announce is not None:
            announce(text)

    def step(percent, label, detail=""):
        if progress is not None:
            progress(percent, label, detail)

    ser = serial.Serial()
    ser.port, ser.baudrate = port, handshake
    ser.parity = PARITY
    ser.timeout = 0.05
    ser.open()
    try:
        session = Session(ser)
        step(0, "Waiting for handshake",
             "switch the board's supply off and on")
        say("waiting for handshake -- switch the board's supply off and "
            "back on, any time in the next %d seconds" % wait)
        status = await_bootloader(ser, session, wait, say, tick)
        if tick is not None:
            tick(None)
        if status is None:
            raise Stc8Error(
                f"no power-on seen in {wait:.0f}s. The bootloader is entered "
                "on power-on and on nothing else, so the board's supply has "
                "to be interrupted and restored while this waits")
        check_part(status, expect_part)
        say("powered on: %s" % part_name(status))
        say("part reports %.3f MHz for its own clock"
            % (bootloader_hz(status, ser.baudrate) / 1e6))
        step(100, "Handshake", part_name(status))
        # Hand the part back to its own firmware. Without this it sits in
        # the bootloader until the next power cycle, and a board that was
        # running a sketch before the probe would come back mute.
        session.send(build(RUN))
        return status
    finally:
        ser.close()


def program(port: str, image: bytes, handshake: int = HANDSHAKE_BAUD,
            transfer: int = TRANSFER_BAUD, wait: float = 120.0,
            announce=None, progress=None, tick=None,
            attempts: int = 200, expect_part: str = "",
            protocol: str = "stc8g") -> None:
    """Sync, then erase and write *image*, over a port opened here.

    Raises Stc8Error if the part does not answer, so a caller can report
    the step that failed rather than a return code.

    *announce* takes a line of text and *progress* takes a percentage, a
    label and a detail. Both are called throughout rather than only at the
    end, because most of this run is spent waiting for somebody to power
    the board on: a run that prints nothing while it waits cannot be told
    from one that has hung, and the person waiting is stood at the board.

    *tick* carries the seconds left in that wait, and None once it is over,
    so the countdown can be one line that changes rather than a column of
    lines that scrolls.

    A pass that dies partway is started again from the next power-on, for
    as long as *wait* allows. On a board whose supply is a switch under
    somebody's thumb, the supply going away in the middle of a write is not
    an exceptional case -- it is the same gesture that started the upload,
    made once too often. Cutting it there resets the part, which ends the
    session and leaves the flash half written. Rather than report that as a
    failure and leave it half written, this waits for the board to come
    back and does the whole thing again from the erase, which is the one
    recovery that always lands somewhere known.

    The budget is the clock and not a count of tries, because the two are
    not the same thing here. While the supply is switched out the part
    still answers a handshake -- the sync byte is high nine tenths of the
    time and costs it almost nothing -- and then fails at the first
    command, in about a second. A budget of a few tries is spent in well
    under a minute of somebody simply holding the switch off, and the
    upload would give up on a board that was about to be perfectly fine.
    *attempts* remains only as a stop against a fault that fails instantly
    and for ever.
    """
    import serial

    def say(text):
        if announce is not None:
            announce(text)

    def step(percent, label, detail=""):
        if progress is not None:
            progress(percent, label, detail)

    ser = serial.Serial()
    ser.port, ser.baudrate = port, handshake
    ser.parity = PARITY
    ser.timeout = 0.05
    ser.open()
    try:
        paced = False
        # Said once when it changes, not on every retry: a line repeated
        # down the page reads as something going wrong again rather than as
        # a setting that is still in force.
        announced_pacing = False
        deadline = time.monotonic() + wait
        attempt = 0
        while True:
            attempt += 1
            left = deadline - time.monotonic()
            if left <= 0:
                raise Stc8Error(
                    f"gave up after {wait:.0f}s. The board has to be on its "
                    "own supply, and stay on it, from the handshake to the "
                    "last block")
            ser.baudrate = handshake
            session = Session(
                ser,
                write_chunk=PACED_CHUNK if paced else 0,
                write_gap=PACED_GAP if paced else 0.0)
            if paced and not announced_pacing:
                announced_pacing = True
                say("sending in small pieces from here, so a board fed from "
                    "the serial line keeps its supply through the writes")
            step(0, "Waiting for handshake",
                 "switch the board's supply off and on")
            if attempt == 1:
                say("waiting for handshake -- switch the board's supply off "
                    "and back on, any time in the next %d seconds" % wait)
            status = await_bootloader(ser, session, left, say, tick)
            if tick is not None:
                tick(None)
            if status is None:
                raise Stc8Error(
                    f"no power-on seen in {wait:.0f}s. The bootloader is "
                    "entered on power-on and on nothing else, so the "
                    "board's supply has to be interrupted and restored "
                    "while this waits")
            if len(status) >= 23:
                found = "%s, BSL %d.%d.%d%s" % (
                    status[20:22].hex().upper(), status[17] >> 4,
                    status[17] & 0x0F, status[22] & 0x0F, chr(status[18]))
            else:
                found = "part answered"
            # Not something another power-on will change, so it is raised
            # rather than retried.
            check_part(status, expect_part)
            step(10, "Handshake", found)
            say("powered on: %s" % found)
            say("handshake at %d baud" % ser.baudrate)
            say("part reports %.3f MHz for its own clock"
                % (bootloader_hz(status, ser.baudrate) / 1e6))

            try:
                _one_pass(ser, session, status, image, handshake, transfer,
                          say, step, protocol)
                return
            except Stc8Error as exc:
                if (attempt >= max(1, attempts)
                        or time.monotonic() >= deadline):
                    raise Stc8Error(
                        f"{exc}. The handshake worked, so the part is there; "
                        "a command that draws nothing usually means the "
                        "board lost power partway, or is not on a supply of "
                        "its own while it is being programmed") from None
                # Pace only when the writes are what failed, which means
                # the short frames were answered and the long ones were
                # not: a supply that is marginal rather than absent, and
                # the one case pacing can do anything about.
                #
                # A first command met with silence is the other thing
                # entirely -- no supply at all -- and pacing that helps
                # nothing while making the pass that finally succeeds
                # several times slower. It was escalating on both, so
                # somebody holding the switch out for a few seconds paid
                # for it with a slow upload once they let go.
                if "write" in str(exc) and not paced:
                    paced = True
                if "rate change" in str(exc):
                    # Nothing was written, so nothing was lost, and the
                    # cause is specific: a part that answers the handshake
                    # and then the very first command with silence is a
                    # part with no supply of its own. The sync byte is high
                    # nine tenths of the time and costs it almost nothing;
                    # a command frame is half low and it cannot survive one.
                    say("the board answered the handshake and then ignored "
                        "the first command, which is what a board does when "
                        "its supply is switched out -- lock the switch and "
                        "leave it locked until this finishes")
                else:
                    say("%s -- the board went away partway through. Nothing "
                        "is lost: power it off and on again and this starts "
                        "over from the erase." % exc)
                step(0, "Restarting", "waiting for the board again")
    finally:
        ser.close()
