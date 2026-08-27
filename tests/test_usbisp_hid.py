"""Host-side USB-ISP helpers. No hardware required."""

from __future__ import annotations

import pathlib

from niusburner.backends.usbisp_hid import _bytes_to_program, _parse_ihx, _spi_rx
from niusburner import registry


def test_spi_rx_strips_report_id_and_trailing_junk():
    assert _spi_rx([0x01, 0xAA, 0x53, 0x69, 0x00, 0x00, 0x00, 0x00, 0xEB]) == [
        0xAA, 0x53, 0x69, 0x00]
    assert _spi_rx([0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0xC8]) == [
        0x00, 0x00, 0x00, 0x00]
    assert _spi_rx([]) == [0, 0, 0, 0]
    assert _spi_rx([0x01]) == [1, 0, 0, 0]


def test_spi_rx_matches_enable_and_signature_frames():
    # GET FR1 (8 bytes) after 0x0E AC 53 00 00 — ACK is SPI byte 3.
    assert _spi_rx([0xFF, 0xFF, 0xFF, 0x69, 0xFF, 0xFF, 0x60, 0xFF]) == [
        0xFF, 0xFF, 0xFF, 0x69]
    assert _spi_rx([0x00, 0x28, 0x00, 0x1E, 0xFF, 0xFF, 0x60, 0xFF])[3] == 0x1E
    assert _spi_rx([0x00, 0x28, 0x01, 0x52, 0xFF, 0xFF, 0x60, 0xFF])[3] == 0x52
    assert _spi_rx([0x00, 0x28, 0x02, 0x06, 0xFF, 0xFF, 0x60, 0xFF])[3] == 0x06


def test_spi_echoed_rejects_a_frame_that_does_not_echo_the_command():
    """A GET that lands before the transfer holds no answer; retry, do not guess.

    The target shifts each TX byte back out one byte later, so RX[1] must be
    the command. Accepting a frame without it would let a stale buffer pass a
    verify, so the read is retried instead.
    """
    from niusburner.backends.usbisp_hid import _Programmer

    frames = [
        [0xFF, 0xFF, 0xFF, 0xFF],   # GET landed before the transfer finished
        [0x00, 0x20, 0x00, 0xA5],   # aligned: RX[1] echoes the 0x20 command
    ]
    prog = _Programmer.__new__(_Programmer)
    prog.spi = lambda *a, **k: frames.pop(0)  # type: ignore[method-assign]

    assert prog.spi_echoed(0x20, 0x00, 0x00, 0x00)[3] == 0xA5
    assert not frames


def test_parse_ihx_data_records(tmp_path: pathlib.Path):
    image = tmp_path / "tiny.ihx"
    image.write_text(
        ":03010000010203F7\n:00000001FF\n", encoding="ascii")
    assert _parse_ihx(image) == {0x0100: 1, 0x0101: 2, 0x0102: 3}


def test_bytes_to_program_skips_erased_ff():
    assert _bytes_to_program({0: 0xFF, 1: 0x00, 2: 0xAC}) == {1: 0x00, 2: 0xAC}


def test_erase_and_write_fire_then_wait():
    import inspect
    from niusburner.backends.usbisp_hid import _Programmer, flash as hid_flash
    assert "_spi_fire" in inspect.getsource(_Programmer.write_byte)
    erase_src = inspect.getsource(_Programmer.chip_erase)
    assert "_spi_fire" in erase_src
    assert "range(2)" in erase_src
    flash_src = inspect.getsource(hid_flash)
    assert "range(3)" in flash_src
    assert "release_to_run" in flash_src
    after_done = flash_src.split("Done - ISP complete")[-1]
    assert "release_to_run" in after_done
    assert "disconnect" not in after_done
    # The bench failure this points at was not the reset at all: EA tied low
    # makes the CPU fetch from external memory, so a perfectly verified image
    # never runs. Say that where someone reads it.
    assert "EA (pin 31)" in after_done
    release_src = inspect.getsource(_Programmer.release_to_run)
    assert "auto_reset" in release_src
    auto_src = inspect.getsource(_Programmer.auto_reset)
    assert "[0x0D, 0x00, 0x01, 0x00, 0x00, 0x00, 0x00]" in auto_src
    assert "[0x0B, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00]" not in auto_src
    assert "[0x02, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00]" not in auto_src


def test_hid_detect_rule_shape():
    ok, where, version, reason = registry.probe(
        {"detect": {"vid": "0x03EB", "pid": "0xC8B4"}})
    # Device may or may not be plugged in; the rule must not crash.
    assert ok or reason
    if ok:
        assert where


def test_release_uses_0d_and_executes_both_frames():
    """auto_reset must run through _exec, not _fr1.

    A bare SET only loads the dongle's command register; the GET is what
    runs it. Sending the release as a SET is why the part stayed halted
    after every flash on this bench.
    """
    import inspect
    from niusburner.backends.usbisp_hid import _Programmer

    src = inspect.getsource(_Programmer.auto_reset)
    assert src.count("self._exec(") == 2
    assert "self._fr1(" not in src


def test_flash_can_hold_the_part_in_reset():
    import inspect
    from niusburner.backends.usbisp_hid import flash as hid_flash

    assert inspect.signature(hid_flash).parameters["run"].default is True
    src = inspect.getsource(hid_flash)
    assert "if not run:" in src
    # The early return must come before release_to_run, or --hold-reset runs
    # the part anyway.
    assert src.index("if not run:") < src.index("prog.release_to_run()")
