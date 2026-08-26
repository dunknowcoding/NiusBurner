"""Host-side USB-ISP helpers. No hardware required."""

from __future__ import annotations

import pathlib

from niusburner.backends.usbisp_hid import _parse_ihx, _spi_rx
from niusburner import registry


def test_spi_rx_strips_report_id_and_trailing_junk():
    assert _spi_rx([0x01, 0xAA, 0x53, 0x69, 0x00, 0x00, 0x00, 0x00, 0xEB]) == [
        0xAA, 0x53, 0x69, 0x00]
    assert _spi_rx([0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0xC8]) == [
        0x00, 0x00, 0x00, 0x00]
    assert _spi_rx([]) == [0, 0, 0, 0]
    assert _spi_rx([0x01]) == [1, 0, 0, 0]


def test_spi_rx_matches_progisp_enable_and_signature_frames():
    # HidD_GetFeature(8) after 0x0E AC 53 00 00 — ACK is SPI byte 3.
    assert _spi_rx([0xFF, 0xFF, 0xFF, 0x69, 0xFF, 0xFF, 0x60, 0xFF]) == [
        0xFF, 0xFF, 0xFF, 0x69]
    assert _spi_rx([0x00, 0x28, 0x00, 0x1E, 0xFF, 0xFF, 0x60, 0xFF])[3] == 0x1E
    assert _spi_rx([0x00, 0x28, 0x01, 0x52, 0xFF, 0xFF, 0x60, 0xFF])[3] == 0x52
    assert _spi_rx([0x00, 0x28, 0x02, 0x06, 0xFF, 0xFF, 0x60, 0xFF])[3] == 0x06


def test_parse_ihx_reads_data_records(tmp_path: pathlib.Path):
    # 3 bytes at 0x0100: 01 02 03, then EOF.
    image = tmp_path / "tiny.ihx"
    image.write_text(
        ":03010000010203F7\n:00000001FF\n", encoding="ascii")
    assert _parse_ihx(image) == {0x0100: 1, 0x0101: 2, 0x0102: 3}


def test_hid_detect_rule_shape():
    ok, where, version, reason = registry.probe(
        {"detect": {"vid": "0x03EB", "pid": "0xC8B4"}})
    # Device may or may not be plugged in; the rule must not crash.
    assert ok or reason
    if ok:
        assert where
