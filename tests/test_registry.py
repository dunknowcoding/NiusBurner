"""Registry invariants. No hardware, no toolchain required.

Copyright 2026 dunknowcoding (NiusRobotLab)
SPDX-License-Identifier: Apache-2.0

These are the rules that make the registry trustworthy rather than decorative.
The one that matters most is the last: this repository must never come to
contain a toolchain.
"""

from __future__ import annotations

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from niusburner import registry  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]

# Extensions that would mean a third-party tool had been committed here.
BINARY_SUFFIXES = {".exe", ".dll", ".so", ".dylib", ".a", ".lib",
                   ".zip", ".7z", ".tar", ".gz", ".xz", ".msi"}


def test_registry_parses():
    reg = registry.load_registry()
    assert reg["root"], "a toolchain root must be named"
    assert reg["compilers"], "registry has no compilers"
    assert reg["programmers"], "registry has no programmers"


def test_every_compiler_declares_a_family():
    """
    A compiler with no family cannot be selected for a target, which makes it
    invisible in exactly the situation it is needed.
    """
    for name, entry in registry.load_registry()["compilers"].items():
        assert entry.get("family"), f"{name} declares no family"


def test_every_entry_can_be_detected_or_says_why_not():
    """
    Detection is optional, but silence is not. An entry with no rule is
    reported as unconfirmable rather than assumed present -- the alternative
    is a tool that looks installed until a build fails.
    """
    reg = registry.load_registry()
    for section in ("compilers", "programmers"):
        for name, entry in reg[section].items():
            rule = entry.get("detect")
            if rule is None:
                # Allowed, but then it must at least explain itself to a user.
                assert entry.get("note") or entry.get("wiring"), (
                    f"{name} has neither a detection rule nor any guidance")
                continue
            assert {"cmd", "path", "glob"} & set(rule), (
                f"{name} detect rule has no cmd, path or glob")


def test_detection_paths_point_outside_this_repository():
    """
    THE RULE. Nothing is vendored, so no detection rule may resolve inside the
    repo -- a rule that did would mean a toolchain was expected to live here.
    """
    reg = registry.load_registry()
    for section in ("compilers", "programmers"):
        for name, entry in reg[section].items():
            rule = entry.get("detect") or {}
            for key in ("path", "glob"):
                if key not in rule:
                    continue
                value = pathlib.Path(rule[key])
                assert not value.is_absolute() or ROOT not in value.parents, (
                    f"{name} expects a tool inside the repository")
                assert value.is_absolute(), (
                    f"{name} uses a relative tool path; it would resolve "
                    "against the working directory")


def test_probing_a_missing_tool_gives_a_reason_not_a_crash():
    ok, where, version, reason = registry.probe(
        {"detect": {"path": str(ROOT.parent / "definitely-not-here" / "nope")}})
    assert not ok
    assert reason, "a failed probe must say why"


def test_probing_an_entry_with_no_rule_is_not_an_error():
    ok, where, version, reason = registry.probe({})
    assert not ok
    assert "cannot be confirmed" in reason


def test_a_command_that_is_the_wrong_tool_is_rejected():
    """
    `match` exists because PATH collisions are real: something else named
    `sdcc` or `avrdude` earlier on PATH would otherwise be accepted and then
    fail confusingly at build time.
    """
    ok, where, version, reason = registry.probe(
        {"detect": {"cmd": "python", "args": ["--version"],
                    "match": "this-is-not-python"}})
    assert not ok
    assert "did not identify itself" in reason


def test_programmers_for_returns_all_options_not_one():
    """
    An STC89C52RC is reachable two ways and the right one depends on wiring.
    Collapsing that to a single answer would be a guess about a bench this
    code cannot see.
    """
    opts = registry.programmers_for("stc89c52rc")
    assert opts, "STC89C52RC should have at least one route"
    names = {o.name for o in opts}
    assert "usbasp" in names, (
        "the USB-ISP does program STC89 parts over SPI ISP -- only the STC15 "
        "family is bootloader-only")


def test_no_toolchain_binary_is_committed():
    """
    The invariant the whole project rests on. Checked by walking the tree
    rather than trusting .gitignore, because an ignore rule added after a file
    was committed does not remove it.
    """
    offenders = []
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        if any(part in {".git", "_work", "__pycache__"} for part in path.parts):
            continue
        if path.suffix.lower() in BINARY_SUFFIXES:
            offenders.append(path.relative_to(ROOT))
    assert not offenders, f"toolchain binaries committed: {offenders}"


def test_the_repository_stays_small():
    """
    A size ceiling is the cheapest way to notice a vendored toolchain that
    slipped past the extension check -- they are never small.
    """
    total = sum(p.stat().st_size for p in ROOT.rglob("*")
                if p.is_file()
                and not any(x in {".git", "_work", "__pycache__"} for x in p.parts))
    assert total < 5 * 1024 * 1024, f"repo is {total/1e6:.1f} MB; something was vendored"
