"""The observer hook, the brain's pool-current input, and the training
plumbing. The one test here that needs the ROM skips without it."""

from dataclasses import fields, replace
from pathlib import Path

import numpy as np
import pytest
from conftest import ROM

from flybrain.brain import Brain
from flybrain.config import POOL_NAMES, Config, furthest_map, map_progress
from flybrain.connectome import synthetic
from flybrain.loop import TickState, run_loop
from flybrain.training import CSV_FIELDS, EpisodeResult, learning_curve

EXPECTED_FIELDS = {
    "step",
    "frame",
    "pressed",
    "started",
    "action",
    "excursion",
    "firing_rate",
    "dopamine",
    "value",
    "mbon",
    "reward",
    "reward_parts",
    "episode_reward",
    "map_id",
    "map_name",
    "x",
    "y",
    "in_battle",
    "panic",
    "panics",
    # The journey (docs/spec-milestones.md section 1).
    "game_tick",
    "milestone",
    "milestones",
    "since_milestone",
    "last_milestone",
    "brain",
    "brain_episodes",
}


class Recorder:
    def __init__(self):
        self.seen: list[TickState] = []

    def __call__(self, tick):
        self.seen.append(tick)


def test_tick_state_carries_the_documented_fields():
    assert {f.name for f in fields(TickState)} == EXPECTED_FIELDS


def test_a_pool_current_reaches_only_its_own_pool():
    """The mushroom body's only way into the network. It must be an input
    current to the pool's own neurons and nothing else."""
    cfg = replace(Config(), noise_sigma=0.0)
    conn = synthetic(n=1200, seed=0, cfg=cfg)
    quiet = np.zeros(cfg.n_sensory, dtype=np.float32)

    plain = Brain(conn, cfg)
    plain.step(quiet)
    biased = Brain(conn, cfg)
    current = np.zeros(len(POOL_NAMES), dtype=np.float32)
    current[POOL_NAMES.index("UP")] = 0.5
    biased.step(quiet, current)

    moved = np.flatnonzero(biased.v != plain.v)
    assert np.array_equal(np.sort(moved), np.sort(conn.motor_pools["UP"]))
    assert np.allclose(biased.v[conn.motor_pools["UP"]] - plain.v[conn.motor_pools["UP"]], 0.5)


def test_brain_reset_returns_it_to_rest():
    cfg = Config()
    conn = synthetic(n=1200, seed=0, cfg=cfg)
    brain = Brain(conn, cfg)
    rng = np.random.default_rng(0)
    for _ in range(50):
        brain.step(rng.random(cfg.n_sensory).astype(np.float32) * cfg.max_current)
    brain.reset()
    assert np.all(brain.v == cfg.v_rest) and not brain.spikes.any() and brain.steps == 0


def test_map_progress_ranks_the_early_game():
    assert map_progress(0x26) < map_progress(0x25) < map_progress(0x00) < map_progress(0x0C)
    assert map_progress(0xAB) == -1
    assert furthest_map([0x26, 0x25, 0x00]) == 0x00
    assert furthest_map([0xAB]) is None
    assert furthest_map([]) is None


def result(episode, reward, left_house, maps):
    return EpisodeResult(
        episode=episode,
        kind="train",
        ticks=20_000,
        reward=reward,
        parts=dict.fromkeys(("tile", "map", "event", "level", "badge"), 0.0),
        tiles=int(reward),
        maps=maps,
        furthest=furthest_map(maps),
        left_house=left_house,
        presses=dict.fromkeys(POOL_NAMES, 1),
        panics=0,
        mean_abs_delta=0.1,
        w_actor_abs=0.01,
        w_critic_abs=0.01,
        ticks_per_second=1200.0,
        seed=episode,
    )


def test_an_episode_row_matches_the_csv_header():
    assert set(result(1, 10.0, False, [0x26]).row()) == set(CSV_FIELDS)


def test_the_learning_curve_buckets_training_episodes():
    results = [result(i, float(i), i >= 5, [0x26, 0x25] + ([0x00] if i >= 5 else [])) for i in range(1, 11)]
    rows = learning_curve(results, bucket=5)
    assert len(rows) == 2
    assert rows[0]["left_house"] == 0.2 and rows[1]["left_house"] == 1.0
    assert rows[1]["mean_reward"] > rows[0]["mean_reward"]


@pytest.mark.skipif(not ROM.is_file(), reason="roms/pokemon_red.gb not present")
def test_every_tick_reaches_every_observer():
    cfg = replace(Config(), rom_path=ROM, headless=True, uncapped=True, hud=False, max_steps=400, seed=0)
    first, second = Recorder(), Recorder()
    summary = run_loop(cfg, observers=(first, second))
    assert len(first.seen) == len(second.seen) == summary["steps"] == 400
    assert [t.step for t in first.seen] == list(range(1, 401))
    one = first.seen[-1]
    assert one.frame.shape == (144, 160)
    assert one.excursion.shape == (len(POOL_NAMES),) and one.mbon.shape == (len(POOL_NAMES),)
    assert set(one.reward_parts) == {"tile", "map", "event", "level", "badge"}
    assert isinstance(one.map_name, str) and isinstance(one.in_battle, bool)


@pytest.mark.skipif(not ROM.is_file(), reason="roms/pokemon_red.gb not present")
@pytest.mark.skipif(
    not (Path(__file__).resolve().parent.parent / "states" / "bedroom.state").is_file(),
    reason="states/bedroom.state not present",
)
def test_a_short_training_run_writes_a_brain_and_a_csv(tmp_path):
    from flybrain.mushroom_body import MushroomBody
    from flybrain.training import train

    cfg = replace(Config(), rom_path=ROM, headless=True, uncapped=True, seed=0, checkpoint_every=1)
    out, log = tmp_path / "brain.npz", tmp_path / "train.csv"
    state = Path(__file__).resolve().parent.parent / "states" / "bedroom.state"
    results = train(cfg, total_ticks=1200, episode_ticks=600, out=out, log_path=log, state_path=state, eval_every=0)

    assert len(results) == 2 and all(r.ticks == 600 for r in results)
    assert out.is_file() and log.is_file()
    assert log.read_text(encoding="utf-8").splitlines()[0].startswith("episode,kind")
    loaded = MushroomBody(cfg, cfg.seed)
    loaded.load(out)
    assert loaded.episodes_trained == 2


@pytest.mark.skipif(not ROM.is_file(), reason="roms/pokemon_red.gb not present")
def test_run_loop_loads_a_saved_brain_and_biases_with_it(tmp_path):
    """The other half of the contract's end-to-end check: a brain written by
    training is picked up by the watching loop and actually reaches the pools."""
    from flybrain.loop import LoopOptions
    from flybrain.mushroom_body import MushroomBody

    cfg = replace(Config(), rom_path=ROM, headless=True, uncapped=True, hud=False, max_steps=300, seed=0)
    mushroom = MushroomBody(cfg, cfg.seed)
    mushroom.w_actor[POOL_NAMES.index("DOWN")] = cfg.w_actor_clip
    mushroom.episodes_trained, mushroom.ticks_trained = 3, 60_000
    path = mushroom.save(tmp_path / "brain.npz")

    seen = Recorder()
    run_loop(cfg, observers=(seen,), options=LoopOptions(brain_path=path))
    biases = np.array([t.mbon[POOL_NAMES.index("DOWN")] for t in seen.seen])
    assert (biases > 0).all(), "the loaded brain never biased the pool it was built to bias"
