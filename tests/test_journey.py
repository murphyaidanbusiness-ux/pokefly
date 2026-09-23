"""The journey save: continue, autosave, save on exit, atomic, --fresh.

The atomicity and schedule tests use a small fake fly and need no ROM. The
continuation and exit tests run the real game and skip without the ROM.
"""

from __future__ import annotations

import hashlib
import io
import os
import signal
from dataclasses import replace

import numpy as np
import pytest
from conftest import ROM, ROOT

from flybrain.config import Config
from flybrain.emulator import EmulatorPoint
from flybrain.journey import BRAIN, DATA_FILES, FLY, MANIFEST, STATE, JourneySave, JourneySession
from flybrain.mushroom_body import MushroomBody
from flybrain.snapshot import FlySnapshot

BEDROOM = ROOT / "states" / "bedroom.state"
BEST = ROOT / "brains" / "latest.npz"
needs_rom = pytest.mark.skipif(not (ROM.is_file() and BEDROOM.is_file()), reason="ROM or bedroom state not present")


class FakeFly:
    """What `JourneySave.save` touches: `snapshot`, `mushroom`, `clock`."""

    def __init__(self, generation: int) -> None:
        self.clock = 1000 * generation
        self.mushroom = MushroomBody(Config(), 0)
        self.mushroom.episodes_trained = generation
        self.generation = generation

    def snapshot(self, full: bool = False) -> FlySnapshot:
        return FlySnapshot(
            emulator=EmulatorPoint(anchor=bytes([self.generation]) * 64, events=(), ticks=0, pending=()),
            parts={"fly": {"clock": self.clock, "marker": np.full(4, self.generation)}},
            fingerprint="f",
            meta={},
        )


def generation_of(store: JourneySave) -> int:
    snapshot, manifest = store.load()
    marker = int(snapshot.parts["fly"]["marker"][0])
    assert snapshot.emulator.anchor == bytes([marker]) * 64, "the state and the npz come from one save"
    assert manifest["episodes_trained"] == marker
    return marker


# --------------------------------------------------------------- atomic ---


def test_a_save_keeps_the_previous_one_as_bak(tmp_path):
    store = JourneySave(tmp_path / "journey")
    assert not store.exists()
    store.save(FakeFly(1))
    store.save(FakeFly(2))
    assert generation_of(store) == 2
    for name in (*DATA_FILES, MANIFEST):
        assert (store.folder / name).is_file() and (store.folder / (name + ".bak")).is_file()
    assert not list(store.folder.glob("*.tmp")) and not list(store.folder.glob("*.partial"))


@pytest.mark.parametrize("fail_at", range(1, 12))
def test_an_interrupted_save_never_loses_the_previous_one(tmp_path, monkeypatch, fail_at):
    """Kill the save at every rename it makes: the three that land the `.tmp`
    files (state, fly npz, brain), then two for each of the four files as they
    rotate. Whatever is on disk afterwards, the loader finds one whole save:
    the old one or the new one, never a mixture."""
    store = JourneySave(tmp_path / "journey")
    store.save(FakeFly(1))
    store.save(FakeFly(2))

    real = os.replace
    calls = {"n": 0}

    def dying(src, dst):
        calls["n"] += 1
        if calls["n"] == fail_at:
            raise KeyboardInterrupt("killed mid-save")
        return real(src, dst)

    monkeypatch.setattr("flybrain.journey.os.replace", dying)
    with pytest.raises(KeyboardInterrupt):
        store.save(FakeFly(3))
    monkeypatch.setattr("flybrain.journey.os.replace", real)
    assert calls["n"] == fail_at
    assert generation_of(store) in (2, 3)
    # And the next save tidies up from whatever was left.
    store.save(FakeFly(4))
    assert generation_of(store) == 4


def test_a_corrupted_file_falls_back_to_the_backup(tmp_path):
    store = JourneySave(tmp_path / "journey")
    store.save(FakeFly(1))
    store.save(FakeFly(2))
    (store.folder / FLY).write_bytes(b"not an npz")
    assert generation_of(store) == 1


def test_the_journey_brain_is_an_ordinary_brain_file(tmp_path):
    store = JourneySave(tmp_path / "journey")
    store.save(FakeFly(5))
    brain = MushroomBody(Config(), 0)
    brain.load(store.folder / BRAIN)
    assert brain.episodes_trained == 5 and brain.score is None


# ------------------------------------------------------------- schedule ---


class CountingStore:
    def __init__(self) -> None:
        self.saves: list[int] = []
        self.folder = "fake"

    def save(self, fly, extra=None) -> dict:
        self.saves.append(fly.clock)
        return {}

    def manifest(self):
        return None


def test_autosave_fires_on_the_wall_clock_schedule():
    now = {"t": 0.0}
    store = CountingStore()
    cfg = replace(Config(), autosave_minutes=5.0)
    session = JourneySession(store, cfg, clock=lambda: now["t"], say=lambda line: None)
    fly = FakeFly(1)
    session.start(fly)
    for second in range(0, 1000):
        now["t"] = float(second)
        fly.clock = second
        session.after_tick(fly)
    assert store.saves == [300, 600, 900]
    # A save on request restarts the timer.
    now["t"] = 950.0
    session.save(fly, "on request")
    now["t"] = 1199.0
    session.after_tick(fly)
    now["t"] = 1250.0
    session.after_tick(fly)
    assert len(store.saves) == 5 and session.saves == 5


# ------------------------------------------------------------ with a game ---


def journey_run(tmp_path, max_steps, observers=(), **options):
    from flybrain.loop import LoopOptions, run_loop

    cfg = replace(Config(), rom_path=ROM, headless=True, uncapped=True, hud=False, max_steps=max_steps, load_state=BEDROOM)
    store = CountingStore()
    session = JourneySession(store, cfg, say=lambda line: None)
    run_loop(cfg, observers=observers, options=LoopOptions(journey=session, pause_toggle=lambda: False, **options))
    return store


@needs_rom
def test_exit_always_saves_at_max_steps(tmp_path):
    store = journey_run(tmp_path, 30)
    assert store.saves == [5047 + 30]


@needs_rom
def test_ctrl_c_finishes_the_tick_and_saves(tmp_path):
    def interrupt(tick):
        if tick.step == 12:
            signal.raise_signal(signal.SIGINT)

    store = journey_run(tmp_path, 100, observers=(interrupt,))
    assert store.saves == [5047 + 12], "the tick the Ctrl+C arrived in was finished, then saved"


@needs_rom
def test_a_closed_window_still_saves_a_whole_tick(tmp_path, monkeypatch):
    from flybrain.emulator import Emulator

    real = Emulator.tick
    count = {"n": 0}

    def closing(self):
        count["n"] += 1
        return real(self) and count["n"] < 20

    monkeypatch.setattr(Emulator, "tick", closing)
    store = journey_run(tmp_path, 100)
    assert store.saves == [5047 + 20], "the last frame was emulated, so the fly saw it before the save"


@needs_rom
def test_a_tick_cut_in_half_is_not_saved(tmp_path, capsys):
    def explode(tick):
        if tick.step == 5:
            raise KeyboardInterrupt

    store = journey_run(tmp_path, 100, observers=(explode,))
    assert store.saves == []
    assert "not saved" in capsys.readouterr().out


@needs_rom
def test_a_save_then_restore_continues_with_identical_presses(tmp_path):
    from test_replay import new_fly, play

    source = new_fly()
    source.emulator.load_state(BEDROOM)
    source.reset(seed=9, clock=5047)
    play(source, 500)
    store = JourneySave(tmp_path / "journey")
    store.save(source)
    expected = play(source, 600, start=500)
    source.emulator.close()

    continued = new_fly()
    try:
        snapshot, manifest = store.load()
        assert manifest["game_tick"] == 5047 + 500
        continued.restore(snapshot)
        assert play(continued, 600, start=500) == expected
    finally:
        continued.emulator.close()


@needs_rom
@pytest.mark.skipif(not BEST.is_file(), reason="brains/latest.npz not present")
def test_latest_npz_is_byte_identical_after_a_journey_run(tmp_path, monkeypatch):
    import run
    from flybrain.loop import run_loop

    before = hashlib.sha256(BEST.read_bytes()).hexdigest()
    store = JourneySave(tmp_path / "journey")
    cfg, options, args = run.parse_args(["--headless", "--no-hud", "--uncapped", "--max-steps", "300"])
    assert args.journey
    cfg = run.set_up_journey(cfg, options, args, store)
    assert options.brain_path == store.brain_path() and options.learn
    options.journey = JourneySession(store, cfg, say=lambda line: None)
    options.pause_toggle = lambda: False
    run_loop(cfg, options=options)
    after = hashlib.sha256(BEST.read_bytes()).hexdigest()
    assert after == before
    # The journey brain learned and moved on; the best brain did not.
    assert store.exists()
    snapshot, manifest = store.load()
    assert manifest["ticks_trained"] > 0
    assert hashlib.sha256((store.folder / BRAIN).read_bytes()).hexdigest() != before


# ---------------------------------------------------------------- fresh ---


class Tty(io.StringIO):
    def isatty(self) -> bool:
        return True


def test_fresh_without_yes_on_a_pipe_refuses(tmp_path):
    import run

    store = JourneySave(tmp_path / "journey")
    store.save(FakeFly(1))
    assert not run.confirm_fresh(store, yes=False, stdin=io.StringIO())
    assert store.exists(), "nothing was touched"


def test_fresh_asks_on_a_terminal_and_yes_skips_the_question(tmp_path):
    import run

    store = JourneySave(tmp_path / "journey")
    store.save(FakeFly(1))
    assert not run.confirm_fresh(store, yes=False, stdin=Tty(), ask=lambda prompt: "n")
    assert store.exists()
    assert run.confirm_fresh(store, yes=False, stdin=Tty(), ask=lambda prompt: "y")
    assert not store.folder.exists()
    store.save(FakeFly(2))
    assert run.confirm_fresh(store, yes=True, stdin=io.StringIO())
    assert not store.folder.exists()


def test_fresh_on_a_terminal_that_ends_at_once_refuses(tmp_path):
    """Windows reports the NUL device as a terminal; reading it gives EOF."""
    import run

    def eof(prompt):
        raise EOFError

    store = JourneySave(tmp_path / "journey")
    store.save(FakeFly(1))
    assert not run.confirm_fresh(store, yes=False, stdin=Tty(), ask=eof)
    assert store.exists()


def test_fresh_with_no_save_has_nothing_to_ask(tmp_path):
    import run

    assert run.confirm_fresh(JourneySave(tmp_path / "none"), yes=False, stdin=io.StringIO())


# ----------------------------------------------------------- run.py flags ---


def test_no_flags_is_a_journey_and_a_chosen_brain_or_start_is_not(monkeypatch):
    import run

    monkeypatch.setattr(run.Path, "is_file", lambda self: True)
    assert run.parse_args([])[2].journey
    assert run.parse_args(["--couch", "--portrait", "--no-learn"])[2].journey
    for flags in (
        ["--no-journey"],
        ["--brain", "brains/v1-2M.npz"],
        ["--naive"],
        ["--start-state"],
        ["--load-state", "x.state"],
        ["--learn", "--save-brain"],
        ["--seed", "3"],
        ["--replay", "left_house"],
    ):
        assert not run.parse_args(flags)[2].journey, flags


def test_fresh_is_refused_when_the_run_is_not_a_journey():
    import run

    with pytest.raises(SystemExit):
        run.parse_args(["--fresh", "--naive"])


def test_replay_and_portrait_imply_the_couch():
    import run

    assert run.parse_args(["--replay", "left_house"])[2].couch
    assert not run.parse_args(["--replay", "left_house", "--headless"])[2].couch
    assert run.parse_args(["--portrait"])[2].couch


def test_the_files_are_named_as_the_spec_says():
    assert (STATE, FLY, BRAIN, MANIFEST) == ("fly.state", "fly.npz", "brain.npz", "journey.json")
