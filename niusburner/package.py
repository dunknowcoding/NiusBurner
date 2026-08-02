"""Reproducible, host-neutral firmware image packages."""

from __future__ import annotations

import hashlib
import json
import pathlib
import shutil

MANIFEST_SCHEMA = "niusburner-image-v1"


def package_image(image: pathlib.Path, output: pathlib.Path, *, target: str,
                  load_address: int = 0) -> pathlib.Path:
    image = image.resolve(strict=True)
    if not image.is_file() or not target or load_address < 0:
        raise ValueError("image, target, and non-negative load address are required")
    output.mkdir(parents=True, exist_ok=True)
    destination = output / image.name
    shutil.copyfile(image, destination)
    payload = destination.read_bytes()
    manifest = {
        "schema": MANIFEST_SCHEMA,
        "target": target,
        "image": destination.name,
        "load_address": load_address,
        "size_bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }
    path = output / "manifest.json"
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8")
    return path


def verify_package(manifest_path: pathlib.Path) -> dict:
    manifest_path = manifest_path.resolve(strict=True)
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    if data.get("schema") != MANIFEST_SCHEMA:
        raise ValueError("unknown package schema")
    image_name = data.get("image", "")
    if pathlib.Path(image_name).name != image_name:
        raise ValueError("image must be a package-local filename")
    image = manifest_path.parent / image_name
    payload = image.read_bytes()
    if len(payload) != data.get("size_bytes"):
        raise ValueError("image size does not match manifest")
    if hashlib.sha256(payload).hexdigest() != data.get("sha256"):
        raise ValueError("image digest does not match manifest")
    return data
