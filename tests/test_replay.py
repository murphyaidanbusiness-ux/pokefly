"""Deterministic replay: a fly snapshot restored twice does the same thing twice.

This is the proof the milestone replays and the journey save rest on. What a
snapshot has to hold (docs/spec-milestones.md section 2) is everything that
decides the next tick: the emulator, every array in the brain, optic lobe,
motor, mushroom body and reward tracker, the milestone tracker, and the
bit-generator state of both RNGs in the chain (the optic lobe's noise and the
motor's panic draws). If any of it were missing, the press sequences below
would part company within a few hundred ticks: a panic burst alone draws from
the motor RNG, and the noise enters every tick.

Every test here needs the ROM and the bedroom state, and skips without them.
"""

from __future__ import annotations

import time
from dataclasses import replace

import pytest
from conftest import ROM, ROOT

from flybrain.config import Config
from flybrain.emulator import Emulator
from flybrain.loop import Fly, LoopOptions, run_loop
from flybrain.milestones import JourneyLog, MilestoneRecorder
from flybrain.snapshot import FlySnapshot, SnapshotMismatch

BEDROOM = ROOT / "states" / "bedroom.state"
BEST = ROOT / "brains" / "latest.npz"

pytestmark = [
    pytest.mark.skipif(not ROM.is_file(), reason="no ROM in roms/"),
    pytest.mark.skipif(not BEDROOM.is_file(), reason="states/bedroom.state not present"),
]


def config(**changes) -> Config:
    return replace(Config(), rom_path=ROM, headless=True, uncapped=True, hud=False, **changes)


def new_fly(cfg: Config | None = None) -> Fly:
    """A learning fly, so the snapshot has to carry weights that move, with
    the best brain when there is one."""
    cfg = cfg or config()
    fly = Fly(cfg, Emulator(ROM, headless=True, uncapped=True, cfg=cfg))
    if BEST.is_file():
        fly.mushroom.load(BEST)
    fly.mushroom.learning = True
    return fly


def from_bedroom(ticks: int, seed: int = 7) -> Fly:
    fly = new_fly()
    fly.emulator.load_state(BEDROOM)
    fly.reset(seed=seed, clock=5047)
    play(fly, ticks)
    return fly


def play(fly: Fly, ticks: int, start: int = 0) -> list[tuple]:
    """Every press that started, what was held, and where the player stood,
    tick by tick, plus the value estimate as a witness for the weights."""
    record = []
    for step in range(start + 1, start + ticks + 1):
        fly.emulator.tick()
        tick = fly.tick(step)
        record.append((tick.game_tick, tick.started, tick.pressed, tick.map_id, tick.x, tick.y, tick.value))
    return record


def presses(record: list[tuple]) -> int:
    return sum(len(row[1]) for row in record)


@pytest.fixture
def flies():
    made: list[Fly] = []
    yield made
    for fly in made:
        fly.emulator.close()


def test_600_ticks_from_one_snapshot_twice_are_identical(tmp_path, flies):
    """Two fresh flies restored from the same snapshot on disk: the spec's
    test. The snapshot is the cheap kind, 700 ticks past its anchor, so the
    restore replays recorded input before handing over."""
    source = from_bedroom(700)
    flies.append(source)
    snapshot = source.snapshot()
    assert snapshot.emulator.ticks == 700 and snapshot.emulator.events, "a cheap snapshot, with input to replay"
    snapshot.save(tmp_path, "start")

    runs = []
    for _ in range(2):
        fly = new_fly()
        flies.append(fly)
        fly.restore(FlySnapshot.load(tmp_path, "start"))
        runs.append(play(fly, 600, start=700))
    assert presses(runs[0]) > 10, "the fly has to actually do something for this to prove anything"
    assert runs[0] == runs[1]
    # And both are what the source itself went on to do.
    assert play(source, 600, start=700) == runs[0]


def test_snapshot_run_restore_run_again_gives_the_same_presses(flies):
    """The in-process form: snapshot, run 600, restore the same fly, run 600."""
    fly = from_bedroom(400, seed=11)
    flies.append(fly)
    snapshot = fly.snapshot()
    first = play(fly, 600, start=400)
    fly.restore(snapshot)
    second = play(fly, 600, start=400)
    assert presses(first) > 10 and first == second


def test_a_full_snapshot_restores_with_no_fast_forward(flies):
    fly = from_bedroom(300, seed=3)
    flies.append(fly)
    snapshot = fly.snapshot(full=True)
    assert snapshot.emulator.ticks == 0 and not snapshot.emulator.events
    first = play(fly, 600, start=300)
    fly.restore(snapshot)
    assert play(fly, 600, start=300) == first


def test_a_snapshot_with_buttons_held_mid_press_restores_them(flies):
    """The joypad bits are in the savestate but PyBoy's event queue is not, so
    a snapshot taken while a press is queued has to re-issue it."""
    fly = from_bedroom(1)
    flies.append(fly)
    for step in range(2, 2000):
        fly.emulator.tick()
        fly.tick(step)
        if fly.emulator.point().pending and fly.motor.held:
            break
    else:
        pytest.skip("no tick with a press queued in 2000 ticks")
    snapshot = fly.snapshot()
    first = play(fly, 300, start=step)
    fly.restore(snapshot)
    assert play(fly, 300, start=step) == first


def test_the_cheap_snapshot_costs_under_5_ms(flies):
    """The spec's budget is 2 ms at n=2000 and the test's ceiling is 5. The
    full savestate is measured too and printed, not asserted: it is about
    20 ms, which is why it is only taken every `anchor_every` ticks."""
    fly = from_bedroom(200)
    flies.append(fly)
    cheap, full = [], []
    for block in range(12):
        play(fly, 300, start=200 + block * 300)
        started = time.perf_counter()
        fly.snapshot()
        cheap.append((time.perf_counter() - started) * 1000)
    for _ in range(5):
        started = time.perf_counter()
        fly.snapshot(full=True)
        full.append((time.perf_counter() - started) * 1000)
    cheap.sort()
    full.sort()
    median = cheap[len(cheap) // 2]
    print(f"\ncheap snapshot: median {median:.3f} ms, max {cheap[-1]:.3f} ms; full savestate median {full[2]:.1f} ms")
    assert fly.cfg.n_neurons == 2000
    assert median < 5.0, f"median cheap snapshot {median:.2f} ms"


def test_a_snapshot_from_a_fly_with_other_numbers_is_refused(flies):
    fly = from_bedroom(10)
    flies.append(fly)
    snapshot = fly.snapshot()
    other_cfg = config(seed=1)
    other = Fly(other_cfg, Emulator(ROM, headless=True, uncapped=True, cfg=other_cfg))
    flies.append(other)
    with pytest.raises(SnapshotMismatch):
        other.restore(snapshot)


def test_a_recorded_milestone_lands_again_on_the_same_tick_in_its_replay(tmp_path):
    """End to end through `run_loop`: a recorder writes the replay when the
    fly leaves the bedroom, and a second run restored from it sees the same
    milestone on the same game tick."""
    root = tmp_path / "milestones"
    cfg = config(max_steps=6000, load_state=BEDROOM, snapshot_every=120, replay_lead=360)
    (tmp_path / "bedroom.state.json").write_text('{"game_tick": 5047}', encoding="utf-8")
    recorder = MilestoneRecorder(cfg, root, "watch", JourneyLog(root / "journey.json"), say=lambda line: None)
    landed = {}

    def watch(tick):
        for name in tick.milestones:
            landed.setdefault(name, tick.game_tick)

    brain = BEST if BEST.is_file() else None
    run_loop(cfg, observers=(watch,), options=LoopOptions(brain_path=brain, recorder=recorder, pause_toggle=lambda: False))
    if "left_bedroom" not in landed:
        pytest.skip("this brain did not leave the bedroom in 6000 ticks")
    snapshot = FlySnapshot.load(root / "left_bedroom")
    assert snapshot.meta["landed_tick"] == landed["left_bedroom"]
    lead = snapshot.meta["landed_tick"] - snapshot.meta["start_tick"]
    assert 0 <= lead <= cfg.replay_lead + cfg.snapshot_every

    again = {}

    def watch_again(tick):
        for name in tick.milestones:
            again.setdefault(name, tick.game_tick)

    replay_cfg = config(max_steps=lead + 5)
    run_loop(replay_cfg, observers=(watch_again,), options=LoopOptions(start=snapshot, learn=None, pause_toggle=lambda: False))
    assert again.get("left_bedroom") == landed["left_bedroom"]
