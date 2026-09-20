"""The only test that needs the ROM. It skips when the ROM is absent."""

from dataclasses import replace
from pathlib import Path

import pytest

from conftest import ROM
from flybrain.config import Config
from flybrain.loop import run_loop

@pytest.mark.skipif(not ROM.is_file(), reason="roms/pokemon_red.gb not present")
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
