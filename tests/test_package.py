from __future__ import annotations

import json
import pathlib

import pytest

from niusburner.package import package_image, verify_package


def test_package_is_reproducible_and_host_neutral(tmp_path: pathlib.Path):
    source = tmp_path / "firmware.bin"
    source.write_bytes(b"firmware")
    manifest = package_image(source, tmp_path / "out", target="example-target",
                             load_address=0x1000)
    first = manifest.read_bytes()
    assert verify_package(manifest)["target"] == "example-target"
    package_image(source, tmp_path / "out", target="example-target",
                  load_address=0x1000)
    assert manifest.read_bytes() == first
    assert str(tmp_path) not in first.decode()


def test_package_rejects_tampering(tmp_path: pathlib.Path):
    source = tmp_path / "firmware.bin"
    source.write_bytes(b"firmware")
    manifest = package_image(source, tmp_path / "out", target="example-target")
    (manifest.parent / "firmware.bin").write_bytes(b"changed")
    with pytest.raises(ValueError, match="digest|size"):
        verify_package(manifest)
