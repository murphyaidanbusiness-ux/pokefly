"""The only test that needs the ROM. It skips when the ROM is absent."""

from dataclasses import replace
from pathlib import Path

import pytest

from conftest import ROM
from flybrain.config import Config
from flybrain.loop import find_rom, require_rom, run_loop

@pytest.mark.skipif(not ROM.is_file(), reason="no ROM in roms/")
def test_600_headless_ticks_through_the_real_loop():
    cfg = replace(
        Config(),
        rom_path=ROM,
        headless=True,
        uncapped=True,
        hud=False,
        max_steps=600,
        seed=0,
    )
    summary = run_loop(cfg)
    assert summary["steps"] == 600
    assert summary["total_presses"] >= 1
    map_id, x, y = summary["final_position"]
    assert 0 <= map_id <= 255 and 0 <= x <= 255 and 0 <= y <= 255
    assert 0.0 < summary["firing_rate"] < 0.30


def test_missing_rom_exits_with_code_2(tmp_path):
    cfg = replace(Config(), rom_path=Path(tmp_path) / "nope.gb", headless=True, hud=False, max_steps=1)
    with pytest.raises(SystemExit) as excinfo:
        run_loop(cfg)
    assert excinfo.value.code == 2


def test_find_rom_takes_any_one_gb_file_in_the_folder(tmp_path):
    assert find_rom(tmp_path) == tmp_path / "pokemon_red.gb"
    (tmp_path / "README.md").write_text("not a rom")
    (tmp_path / "Pokemon - Red Version (USA, Europe).GB").write_bytes(b"x")
    assert find_rom(tmp_path) == tmp_path / "Pokemon - Red Version (USA, Europe).GB"


def test_find_rom_prefers_pokemon_red_gb_over_other_files(tmp_path):
    (tmp_path / "a.gb").write_bytes(b"x")
    (tmp_path / "pokemon_red.gb").write_bytes(b"x")
    assert find_rom(tmp_path) == tmp_path / "pokemon_red.gb"


def test_two_unnamed_roms_are_refused_by_name(tmp_path, capsys):
    (tmp_path / "a.gb").write_bytes(b"x")
    (tmp_path / "b.gb").write_bytes(b"x")
    cfg = replace(Config(), rom_path=find_rom(tmp_path))
    with pytest.raises(SystemExit) as excinfo:
        require_rom(cfg)
    assert excinfo.value.code == 2
    assert "a.gb, b.gb" in capsys.readouterr().err


@pytest.mark.skipif(not ROM.is_file(), reason="no ROM in roms/")
def test_pause_holds_the_game_and_resumes():
    """Pressing the pause key stops ticking, releases the buttons, and a second press resumes."""
    from flybrain.config import Config
    from flybrain.loop import LoopOptions, run_loop

    polls = []

    def toggle() -> bool:
        # Tick 20 pauses. Inside the hold the loop polls again; the fourth
        # poll during the hold resumes. Nothing else ever pauses.
        polls.append(1)
        n = len(polls)
        return n == 20 or n == 24

    cfg = Config(rom_path=ROM, headless=True, uncapped=True, hud=False, max_steps=60)
    summary = run_loop(cfg, observers=(), options=LoopOptions(pause_toggle=toggle))
    assert summary["steps"] == 60
    # 60 ticks poll 60 times, plus the 4 polls inside the hold
    assert len(polls) == 64
