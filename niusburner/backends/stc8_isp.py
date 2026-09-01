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


def baud_switch(status: bytes, rate: int) -> tuple:
    """The payload that moves the session to *rate*.

    The two zero bytes are where an oscillator trim would go. Leaving them
    zero is what "do not touch the RC" looks like on the wire.

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
#: The listening window is kept shorter than the second or so the
#: bootloader waits before it gives up and runs the application, because a
#: window longer than that can be busy at the wrong moment and miss the
#: power-on entirely.
#:
#: The low phase is the longer of the two, which is the opposite of what
#: seems sensible and matters more. On a board fed through the serial line,
#: the line being idle is the board being powered -- so during a listening
#: window, switching the supply out does not turn the board off, and
#: switching it back in is a step in voltage rather than a power-on. Only a
#: supply interruption that overlaps a low phase produces a reset. Somebody
#: switching a supply off and straight back on holds it off for perhaps a
#: second, so the low phase has to be most of the cycle for that gesture to
#: land: at these figures any interruption of 0.6s or more is certain to
#: overlap one.
DRAIN_SECONDS = 0.9
LISTEN_SECONDS = 0.6

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

        status = session.sync(LISTEN_SECONDS)
        if status is not None:
            return status

        now = time.monotonic()
        if now - spoken >= NOTICE_SECONDS:
            spoken = now
            left = max(0.0, deadline - now)
            if tick is not None:
                tick(left)
            else:
                say("still waiting for the board to be powered on, "
                    "%ds left" % int(left))
    if tick is not None:
        tick(None)
    return None


def _one_pass(ser, session, status, image, handshake, transfer,
              say, step) -> None:
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
    session.command(baud_switch(status, transfer), 0x01, "rate change")
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


def program(port: str, image: bytes, handshake: int = HANDSHAKE_BAUD,
            transfer: int = TRANSFER_BAUD, wait: float = 120.0,
            announce=None, progress=None, tick=None,
            attempts: int = 200) -> None:
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
            if paced:
                say("sending in small pieces this time, so a board fed from "
                    "the serial line keeps its supply through the writes")
            step(0, "Waiting", "power the board off and on")
            if attempt == 1:
                say("waiting for the board to be powered on -- switch its "
                    "supply off, wait a moment, and switch it back on")
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
            step(10, "Handshake", found)
            say("powered on: %s" % found)
            say("handshake at %d baud" % ser.baudrate)
            say("part reports %.3f MHz for its own clock"
                % (bootloader_hz(status, ser.baudrate) / 1e6))

            try:
                _one_pass(ser, session, status, image, handshake, transfer,
                          say, step)
                return
            except Stc8Error as exc:
                if (attempt >= max(1, attempts)
                        or time.monotonic() >= deadline):
                    raise Stc8Error(
                        f"{exc}. The handshake worked, so the part is there; "
                        "a command that draws nothing usually means the "
                        "board lost power partway, or is not on a supply of "
                        "its own while it is being programmed") from None
                # A command unanswered after a successful handshake says
                # the part is powered enough to answer a sync byte, which
                # is high nine tenths of the time, and not enough for a
                # frame that is half low. Pacing is the only thing left to
                # vary, and repeating the attempt that just failed,
                # unchanged, is the one thing certain not to help. On a
                # board whose supply is switched out entirely it will not
                # help either -- see PACED_CHUNK -- but that case is not
                # one this can distinguish from a marginal supply.
                if not paced:
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
