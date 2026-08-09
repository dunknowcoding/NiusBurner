import json
import pathlib

import pytest

from niusburner import build


def _contract(path: pathlib.Path) -> pathlib.Path:
    path.write_text(json.dumps({
        "kernel_data_bytes": 12,
        "resource_ladder": {"maximum_linked_system_bytes": 1024},
    }), encoding="utf-8")
    return path


def _fake_tool(monkeypatch, program_bytes: int):
    def fake_run(command: list[str], cwd: pathlib.Path) -> str:
        if "--version" in command:
            return "SDCC 4.5.0 #15242\n"
        output = command[command.index("-o") + 1]
        if "-c" in command:
            (cwd / output).write_text("object", encoding="ascii")
            (cwd / pathlib.Path(output).with_suffix(".asm")).write_text(
                "; optimized assembly\n", encoding="ascii")
        else:
            (cwd / "firmware.ihx").write_text(":00000001FF\n", encoding="ascii")
            (cwd / "firmware.map").write_text("map\n", encoding="ascii")
            (cwd / "firmware.mem").write_text(
                f"ROM/EPROM/FLASH  0x0000 0x02b5 {program_bytes} 2048\n",
                encoding="ascii")
        return ""

    monkeypatch.setattr(build, "_run", fake_run)


def test_mcs51_build_retains_assembly_and_enforces_receipt(tmp_path, monkeypatch):
    _fake_tool(monkeypatch, 694)
    compiler = tmp_path / "sdcc.exe"
    compiler.write_bytes(b"")
    source = tmp_path / "app.c"
    source.write_text("int main(void) { return 0; }\n", encoding="ascii")
    receipt = _contract(tmp_path / "contract.json")

    result = build.build_mcs51(
        [source], [tmp_path], tmp_path / "out",
        compiler=compiler, contract=receipt, data_limit=32,
        require_version="4.5.0 #15242",
    )

    assert result.program_bytes == 694
    assert result.kernel_data_bytes == 12
    manifest = json.loads(result.manifest.read_text(encoding="utf-8"))
    assert manifest["measured"] == {
        "kernel_data_bytes": 12,
        "linked_system_program_bytes": 694,
    }
    assert manifest["limits"]["linked_system_program_bytes"] == 1024
    assert manifest["artifacts"]["assembly"][0]["name"].endswith(".asm")
    assert str(tmp_path) not in result.manifest.read_text(encoding="utf-8")


def test_mcs51_build_rejects_half_rom_budget_overflow(tmp_path, monkeypatch):
    _fake_tool(monkeypatch, 1025)
    compiler = tmp_path / "sdcc.exe"
    compiler.write_bytes(b"")
    source = tmp_path / "app.c"
    source.write_text("int main(void) { return 0; }\n", encoding="ascii")

    with pytest.raises(ValueError, match="reserved application"):
        build.build_mcs51(
            [source], [], tmp_path / "out",
            compiler=compiler, contract=_contract(tmp_path / "contract.json"),
        )


def test_sdcc_program_parser_fails_closed():
    assert build.parse_sdcc_program_bytes(
        "ROM/EPROM/FLASH 0x0000 0x01ff 512 2048") == 512
    with pytest.raises(ValueError, match="exact program-byte"):
        build.parse_sdcc_program_bytes("ambiguous report")
