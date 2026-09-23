"""A savestate written by a running emulator, loaded into a fresh one, has to
render exactly what the running one renders next.

PyBoy's savestate leaves out the renderer's window line counter (see the
`emulator.py` docstring), so without `Emulator._load` a fresh PyBoy draws the
window layer one line off on its first frame after a load, whenever the window
is on screen. Measured on the ROM used here before the fix: 150 pixels in 13
rows differed on that frame, and a fly restored from a journey save pressed a
different button 71 ticks later.

These tests use the small ROM PyBoy ships for its own demo, so they run with
no Pokemon Red present. 500 ticks in, that ROM is drawing its text with the
window layer, which is what makes the first assertion mean anything.
"""

from pathlib import Path

import numpy as np
import pyboy
import pytest

from flybrain.config import Config
from flybrain.emulator import Emulator

BUNDLED_ROM = Path(pyboy.__file__).resolve().parent / "default_rom.gb"

pytestmark = pytest.mark.skipif(not BUNDLED_ROM.is_file(), reason="PyBoy's bundled default_rom.gb not found")


@pytest.fixture
def emulators():
    made: list[Emulator] = []
    yield made
    for emulator in made:
        emulator.close()


def fresh(emulators, cfg: Config) -> Emulator:
    emulator = Emulator(BUNDLED_ROM, headless=True, uncapped=True, cfg=cfg)
    emulators.append(emulator)
    return emulator


def test_a_fresh_emulator_loading_a_running_ones_state_renders_the_same_frames(emulators):
    cfg = Config()
    running = fresh(emulators, cfg)
    for _ in range(500):
        running.tick()
    state = running.state_bytes()
    assert running.frame().std() > 0, "the ROM is showing something by now"

    loaded = fresh(emulators, cfg)
    loaded.load_bytes(state)
    for tick in range(10):
        running.tick()
        loaded.tick()
        assert np.array_equal(running.frame(), loaded.frame()), f"frames differ {tick} ticks after the load"


def test_a_running_emulator_reloading_its_own_state_matches_a_fresh_one(emulators):
    """The other direction of the same fact: training reloads the start state
    into an emulator that has been running, a replay loads it into a new one,
    and both have to see the same picture."""
    cfg = Config()
    a = fresh(emulators, cfg)
    for _ in range(500):
        a.tick()
    state = a.state_bytes()
    for _ in range(37):
        a.tick()
    a.load_bytes(state)
    b = fresh(emulators, cfg)
    b.load_bytes(state)
    for _ in range(10):
        a.tick()
        b.tick()
        assert np.array_equal(a.frame(), b.frame())


def test_a_load_keeps_the_buttons_queued_before_it(emulators):
    """`load_bytes` renders a throwaway frame, and a tick consumes PyBoy's
    event queue; a press issued just before the load has to survive it."""
    cfg = Config()
    emulator = fresh(emulators, cfg)
    for _ in range(20):
        emulator.tick()
    state = emulator.state_bytes()
    emulator.press("a")
    emulator.load_bytes(state)
    assert len(emulator.pyboy.events) == 1
    assert emulator.point().pending == (("a", True),)
