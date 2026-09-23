"""Continued training must not make the fly worse.

Two mechanisms, both tested here without a ROM: a learning-rate schedule that
runs off the brain's own episode count, and a trainer that keeps the best brain
by evaluation-block score instead of the last one. The trainer is driven by
scripted episodes (`ScriptedTrainer`), so every test here is about what gets
written where and when, not about the game.
"""

from __future__ import annotations

import csv
from dataclasses import replace

import numpy as np
import pytest

from flybrain.config import POOL_NAMES, Config
from flybrain.mushroom_body import MushroomBody
from flybrain.training import CSV_FIELDS, CsvLog, EpisodeResult, Trainer, read_block_size, read_score

TICKS = 100  # per scripted episode


def config(**changes) -> Config:
    settings = {"seed": 0, "checkpoint_every": 1, "eval_every": 1, "eval_block": 3, "best_margin": 2.0}
    return replace(Config(), **{**settings, **changes})


def episode_result(episode: int, kind: str, reward: float, mushroom: MushroomBody, seed: int, lr: tuple) -> EpisodeResult:
    w_actor_abs, w_critic_abs = mushroom.weight_norms
    return EpisodeResult(
        episode=episode,
        kind=kind,
        ticks=TICKS,
        reward=reward,
        parts=dict.fromkeys(("tile", "map", "event", "level", "badge"), 0.0),
        tiles=int(reward),
        maps=[0x26],
        furthest=0x26,
        left_house=False,
        presses=dict.fromkeys(POOL_NAMES, 0),
        panics=0,
        mean_abs_delta=0.0,
        w_actor_abs=w_actor_abs,
        w_critic_abs=w_critic_abs,
        ticks_per_second=1000.0,
        seed=seed,
        lr_actor=lr[0],
        lr_critic=lr[1],
    )


class ScriptedTrainer(Trainer):
    """A trainer with no game. A training episode stamps the episode number
    into the weights (so every brain on disk says which episode it is), and
    every episode of evaluation block k scores `block_scores[k]`, so block k's
    mean is exactly that number. `calls` records the order things happened in."""

    def __init__(self, cfg, mushroom, block_scores, interrupt_at=None, **kwargs):
        super().__init__(cfg, mushroom, episode_ticks=TICKS, say=lambda line: None, **kwargs)
        self.block_scores = list(block_scores)
        self.interrupt_at = interrupt_at
        self.calls: list[tuple] = []
        self.evals = 0

    def train_episode(self, episode, ticks, seed):
        if self.interrupt_at == ("train", episode):
            raise KeyboardInterrupt
        lr = (self.mushroom.lr_actor, self.mushroom.lr_critic)
        self.calls.append(("train", episode))
        self.mushroom.w_critic[0] = float(episode)
        self.mushroom.episodes_trained += 1
        self.mushroom.ticks_trained += ticks
        return episode_result(episode, "train", 0.0, self.mushroom, seed, lr)

    def eval_episode(self, episode, seed):
        block = self.evals // self.eval_block
        if self.interrupt_at == ("eval", self.evals):
            raise KeyboardInterrupt
        self.evals += 1
        self.calls.append(("eval", episode, float(self.mushroom.w_critic[0])))
        return episode_result(episode, "block", self.block_scores[block], self.mushroom, seed, (0.0, 0.0))


# -- the schedule ---------------------------------------------------------------


def test_the_learning_rate_halves_at_100_episodes_and_quarters_at_300():
    cfg = Config()
    mb = MushroomBody(cfg, 0)
    for episodes, divisor in ((0, 1.0), (100, 2.0), (300, 4.0)):
        mb.episodes_trained = episodes
        assert mb.lr_actor == pytest.approx(cfg.lr_actor / divisor)
        assert mb.lr_critic == pytest.approx(cfg.lr_critic / divisor)


def test_the_schedule_is_what_the_update_actually_uses():
    """Same traces, same TD error: the weight step at 100 episodes is half the
    step at 0."""
    cfg = Config()
    steps = []
    for episodes in (0, 100):
        mb = MushroomBody(cfg, 0)
        mb.episodes_trained = episodes
        frame = np.linspace(0, 1, cfg.retina_size * cfg.retina_size, dtype=np.float32).reshape(16, 16)
        mb.observe(frame)
        mb.learn(0.0)  # priming tick
        mb.credit(["LEFT"])
        mb.credit_critic()
        mb.observe(frame[::-1])
        mb.learn(1.0)
        steps.append((np.abs(mb.w_actor).sum(), np.abs(mb.w_critic).sum()))
    assert steps[0][0] > 0 and steps[0][1] > 0
    assert steps[1][0] == pytest.approx(steps[0][0] / 2, rel=1e-5)
    assert steps[1][1] == pytest.approx(steps[0][1] / 2, rel=1e-5)


def test_zero_decay_switches_the_schedule_off():
    mb = MushroomBody(replace(Config(), lr_decay_episodes=0), 0)
    mb.episodes_trained = 500
    assert mb.lr_scale == 1.0


def test_resume_continues_the_schedule_from_the_stored_count(tmp_path):
    cfg = config()
    trained = MushroomBody(cfg, 0)
    trained.episodes_trained = 100
    path = trained.save(tmp_path / "training.npz")

    resumed = MushroomBody(cfg, 0)
    resumed.load(path)
    assert resumed.lr_scale == pytest.approx(0.5)

    trainer = ScriptedTrainer(cfg, resumed, [1.0] * 10, out=path, best=None)
    results = trainer.run(2 * TICKS, resumed=True)
    rows = [r for r in results if r.kind == "train"]
    assert [r.episode for r in rows] == [101, 102]
    assert rows[0].lr_actor == pytest.approx(cfg.lr_actor / (1 + 100 / 100))
    assert rows[1].lr_actor == pytest.approx(cfg.lr_actor / (1 + 101 / 100))

    again = MushroomBody(cfg, 0)
    again.load(path)
    assert again.episodes_trained == 102
    assert again.lr_scale == pytest.approx(1 / (1 + 102 / 100))


def test_every_csv_row_carries_its_learning_rate(tmp_path):
    cfg = config()
    log = CsvLog(tmp_path / "train.csv")
    mb = MushroomBody(cfg, 0)
    mb.episodes_trained = 100
    trainer = ScriptedTrainer(cfg, mb, [1.0] * 10, out=tmp_path / "t.npz", best=tmp_path / "b.npz", log=log)
    trainer.run(TICKS)
    lines = (tmp_path / "train.csv").read_text(encoding="utf-8").splitlines()
    header = lines[0].split(",")
    assert "lr_actor" in header and "lr_critic" in header
    rows = [dict(zip(header, line.split(","))) for line in lines[1:]]
    train_rows = [row for row in rows if row["kind"] == "train"]
    assert float(train_rows[0]["lr_actor"]) == pytest.approx(cfg.lr_actor / 2)
    assert float(train_rows[0]["lr_critic"]) == pytest.approx(cfg.lr_critic / 2)
    assert all(float(row["lr_actor"]) == 0.0 for row in rows if row["kind"] == "block")


def test_a_log_with_an_older_header_is_refused(tmp_path):
    old = tmp_path / "train.csv"
    old.write_text("episode,kind,ticks,reward\n1,train,20000,3.0\n", encoding="utf-8")
    with pytest.raises(ValueError, match="different columns"):
        CsvLog(old)
    fresh = tmp_path / "fresh.csv"
    CsvLog(fresh)
    fresh.write_text(",".join(CSV_FIELDS) + "\n", encoding="utf-8")
    CsvLog(fresh)  # the current header is fine


# -- keeping the best brain -----------------------------------------------------


def best_writes(monkeypatch, best):
    """Every write to the best file: (score in the file, episode in the file,
    which training episode's weights it holds)."""
    writes = []
    original = MushroomBody.save

    def spy(self, path, **kwargs):
        written = original(self, path, **kwargs)
        if written == best:
            writes.append(read_score(best) + (float(self.w_critic[0]),))
        return written

    monkeypatch.setattr(MushroomBody, "save", spy)
    return writes


def test_the_margin_rule_replaces_only_on_a_clear_win(tmp_path, monkeypatch):
    """Margin 2. Blocks 3, 5, 4, 6, 8: the first is the first; 5 beats 3 by
    exactly the margin and replaces; 4 is lower and 6 is higher by only 1, both
    kept; 8 beats 5 by 3 and replaces."""
    cfg = config(best_margin=2.0)
    best, out = tmp_path / "latest.npz", tmp_path / "training.npz"
    writes = best_writes(monkeypatch, best)
    log = CsvLog(tmp_path / "train.csv")
    trainer = ScriptedTrainer(cfg, MushroomBody(cfg, 0), [3.0, 5.0, 4.0, 6.0, 8.0], out=out, best=best, log=log)
    trainer.run(5 * TICKS)

    assert writes == [(3.0, 1, 1.0), (5.0, 2, 2.0), (8.0, 5, 5.0)]
    assert read_score(best) == (8.0, 5)
    assert read_block_size(best) == 3

    rows = list(csv.DictReader((tmp_path / "train.csv").open(encoding="utf-8")))
    decisions = [
        (int(r["episode"]), float(r["block_score"]), r["incumbent_score"], float(r["margin"]), r["decision"])
        for r in rows
        if r["kind"] == "block"
    ]
    expected = [
        (1, 3.0, "", 2.0, "first"),
        (2, 5.0, "3.0", 2.0, "replaced"),
        (3, 4.0, "5.0", 2.0, "kept"),
        (4, 6.0, "5.0", 2.0, "kept"),
        (5, 8.0, "5.0", 2.0, "replaced"),
    ]
    assert decisions == [row for row in expected for _ in range(3)]  # one row per block episode
    assert all(r["decision"] == "" and r["block_score"] == "" for r in rows if r["kind"] == "train")


def test_with_no_margin_any_higher_block_replaces(tmp_path, monkeypatch):
    cfg = config(best_margin=0.0)
    best, out = tmp_path / "latest.npz", tmp_path / "training.npz"
    writes = best_writes(monkeypatch, best)
    trainer = ScriptedTrainer(cfg, MushroomBody(cfg, 0), [3.0, 5.0, 4.0, 6.0], out=out, best=best)
    trainer.run(4 * TICKS)

    assert writes == [(3.0, 1, 1.0), (5.0, 2, 2.0), (6.0, 4, 4.0)]
    # Each block ran on the weights of the episode it follows, three episodes each.
    blocks = [call for call in trainer.calls if call[0] == "eval"]
    assert [call[1] for call in blocks] == [1, 1, 1, 2, 2, 2, 3, 3, 3, 4, 4, 4]
    assert all(call[1] == call[2] for call in blocks)
    # Every block used the same seeds.
    seeds = [r.seed for r in trainer.results if r.kind == "block"]
    assert seeds == list(trainer.block_seeds) * 4
    assert set(seeds).isdisjoint(range(90_000, 90_010))


def test_a_best_scored_on_another_block_size_is_rescored(tmp_path):
    """A 3-episode score is not comparable with a 6-episode one, so the best
    file is scored again on the current block before anything is held to it."""
    cfg = config(eval_every=10, eval_block=6)
    out, best = tmp_path / "training.npz", tmp_path / "latest.npz"
    old = MushroomBody(cfg, 0)
    old.w_critic[0] = 50.0
    old.episodes_trained = 50
    old.save(best, score=227.7, score_episode=50, score_block=3)

    trainer = ScriptedTrainer(cfg, MushroomBody(cfg, 0), [120.0, 0.0], out=out, best=best)
    trainer.run(TICKS)
    assert [call[2] for call in trainer.calls[:6]] == [50.0] * 6
    assert read_score(best) == (120.0, 50) and read_block_size(best) == 6


def test_the_defaults_are_a_6_episode_block_and_a_25_point_margin():
    cfg = Config()
    assert cfg.eval_block == 6 and cfg.best_margin == 25.0


def test_the_training_state_is_always_the_latest_weights(tmp_path):
    cfg = config()
    best, out = tmp_path / "latest.npz", tmp_path / "training.npz"
    ScriptedTrainer(cfg, MushroomBody(cfg, 0), [3.0, 5.0, 4.0, 2.0], out=out, best=best).run(4 * TICKS)
    latest = MushroomBody(cfg, 0)
    latest.load(out)
    assert latest.w_critic[0] == 4.0 and latest.episodes_trained == 4
    assert latest.score is None, "the training state must not carry a score"
    kept = MushroomBody(cfg, 0)
    kept.load(best)
    assert kept.w_critic[0] == 2.0 and (kept.score, kept.score_episode) == (5.0, 2)


def test_a_run_that_ends_between_blocks_still_scores_its_last_weights(tmp_path):
    cfg = config(eval_every=10)
    trainer = ScriptedTrainer(cfg, MushroomBody(cfg, 0), [7.0], out=tmp_path / "t.npz", best=tmp_path / "b.npz")
    trainer.run(3 * TICKS)
    assert read_score(tmp_path / "b.npz") == (7.0, 3)


def test_no_blocks_means_the_best_file_is_never_touched(tmp_path):
    cfg = config(eval_every=0)
    best = tmp_path / "latest.npz"
    trainer = ScriptedTrainer(cfg, MushroomBody(cfg, 0), [], out=tmp_path / "t.npz", best=best)
    trainer.run(2 * TICKS)
    assert not best.exists()
    assert not any(call[0] == "eval" for call in trainer.calls)


def test_resuming_from_a_brain_without_a_score_evaluates_it_before_training(tmp_path):
    cfg = config(eval_every=10)
    out, best = tmp_path / "training.npz", tmp_path / "latest.npz"
    old = MushroomBody(cfg, 0)
    old.w_critic[0] = 100.0
    old.episodes_trained = 100
    old.save(out)  # no score: a brain from before best-keeping

    resumed = MushroomBody(cfg, 0)
    resumed.load(out)
    assert resumed.score is None
    trainer = ScriptedTrainer(cfg, resumed, [8.0, 1.0], out=out, best=best)
    trainer.run(2 * TICKS, resumed=True)

    assert trainer.calls[:3] == [("eval", 100, 100.0)] * 3, trainer.calls
    assert trainer.calls[3] == ("train", 101)
    # It scored 8 before any training, and the end-of-run block's 1 did not beat it.
    assert read_score(best) == (8.0, 100)
    kept = MushroomBody(cfg, 0)
    kept.load(best)
    assert kept.w_critic[0] == 100.0


def test_an_unscored_best_file_is_scored_before_it_can_be_replaced(tmp_path):
    """The best file on disk predates best-keeping. It is evaluated and its
    score written into it, so a worse resumed brain cannot silently replace it."""
    cfg = config(eval_every=10)
    out, best = tmp_path / "training.npz", tmp_path / "latest.npz"
    good = MushroomBody(cfg, 0)
    good.w_critic[0] = 50.0
    good.episodes_trained = 50
    good.save(best)
    worse = MushroomBody(cfg, 0)
    worse.w_critic[0] = 200.0
    worse.episodes_trained = 200
    worse.save(out)

    resumed = MushroomBody(cfg, 0)
    resumed.load(out)
    trainer = ScriptedTrainer(cfg, resumed, [9.0, 4.0, 1.0], out=out, best=best)
    trainer.run(TICKS, resumed=True)

    evaluated = [call[2] for call in trainer.calls if call[0] == "eval"]
    assert evaluated[:6] == [50.0] * 3 + [200.0] * 3, "the best file first, then the resumed brain"
    kept = MushroomBody(cfg, 0)
    kept.load(best)
    assert kept.w_critic[0] == 50.0 and (kept.score, kept.score_episode) == (9.0, 50)
    trained = MushroomBody(cfg, 0)
    trained.load(out)
    assert trained.w_critic[0] == 201.0, "the training state is the resumed brain, trained on"


def test_resuming_the_best_brains_own_weights_does_not_evaluate_them_twice(tmp_path):
    cfg = config(eval_every=10)
    out, best = tmp_path / "training.npz", tmp_path / "latest.npz"
    same = MushroomBody(cfg, 0)
    same.w_critic[0] = 100.0
    same.episodes_trained = 100
    same.save(best)
    same.save(out)

    resumed = MushroomBody(cfg, 0)
    resumed.load(out)
    trainer = ScriptedTrainer(cfg, resumed, [6.0, 2.0], out=out, best=best)
    trainer.run(TICKS, resumed=True)
    assert sum(call[0] == "eval" for call in trainer.calls) == 6  # one seeding block, one end-of-run block
    assert read_score(best) == (6.0, 100)


def test_ctrl_c_mid_block_keeps_both_files_consistent(tmp_path):
    """Interrupted inside the third block: the training state holds the latest
    weights, the best file still holds the brain its score belongs to."""
    cfg = config()
    out, best = tmp_path / "training.npz", tmp_path / "latest.npz"
    trainer = ScriptedTrainer(
        cfg, MushroomBody(cfg, 0), [3.0, 5.0, 9.0], out=out, best=best, interrupt_at=("eval", 7)
    )
    trainer.run(10 * TICKS)

    latest = MushroomBody(cfg, 0)
    latest.load(out)
    assert latest.w_critic[0] == 3.0 and latest.episodes_trained == 3
    kept = MushroomBody(cfg, 0)
    kept.load(best)
    assert kept.w_critic[0] == 2.0 and (kept.score, kept.score_episode) == (5.0, 2)
    assert not list(tmp_path.glob("*.partial"))


def test_ctrl_c_while_scoring_the_old_best_checkpoints_the_training_weights(tmp_path):
    """The block that scores an old best file swaps that brain in. An
    interrupt there must still write the TRAINING weights to the training state."""
    cfg = config(eval_every=10)
    out, best = tmp_path / "training.npz", tmp_path / "latest.npz"
    old_best = MushroomBody(cfg, 0)
    old_best.w_critic[0] = 50.0
    old_best.save(best)
    mine = MushroomBody(cfg, 0)
    mine.w_critic[0] = 200.0
    mine.episodes_trained = 200
    mine.save(out)

    resumed = MushroomBody(cfg, 0)
    resumed.load(out)
    trainer = ScriptedTrainer(cfg, resumed, [1.0], out=out, best=best, interrupt_at=("eval", 1))
    trainer.run(TICKS, resumed=True)

    latest = MushroomBody(cfg, 0)
    latest.load(out)
    assert latest.w_critic[0] == 200.0
    untouched = MushroomBody(cfg, 0)
    untouched.load(best)
    assert untouched.w_critic[0] == 50.0 and untouched.score is None


def test_a_brain_from_before_best_keeping_loads_with_no_score(tmp_path):
    cfg = Config()
    mb = MushroomBody(cfg, 0)
    np.savez(
        tmp_path / "old.npz",
        fingerprint=mb.fingerprint(),
        w_actor=mb.w_actor,
        w_critic=mb.w_critic,
        episodes_trained=np.int64(100),
        ticks_trained=np.int64(2_000_000),
    )
    mb.load(tmp_path / "old.npz")
    assert (mb.score, mb.score_episode) == (None, None)
    assert read_score(tmp_path / "old.npz") == (None, None)
    mb.save(tmp_path / "scored.npz", score=179.5, score_episode=100)
    assert read_score(tmp_path / "scored.npz") == (179.5, 100)


# -- run.py --learn --save-brain never writes the best brain ------------------------


def test_save_brain_with_no_brain_flag_goes_to_journey():
    import run

    assert run.brain_save_target(None) == run.JOURNEY_BRAIN
    assert run.JOURNEY_BRAIN.name == "journey.npz"


def test_save_brain_never_targets_the_best_brain_however_it_is_spelled(tmp_path):
    import run

    best, journey = tmp_path / "brains" / "latest.npz", tmp_path / "brains" / "journey.npz"
    spelled = tmp_path / "brains" / ".." / "brains" / "latest.npz"
    assert run.brain_save_target(best, best, journey) == journey
    assert run.brain_save_target(spelled, best, journey) == journey
    assert run.brain_save_target(run.BEST_BRAIN) == run.JOURNEY_BRAIN
    other = tmp_path / "brains" / "mine.npz"
    assert run.brain_save_target(other, best, journey) == other


def test_run_py_wires_the_guard_into_the_loop_options(monkeypatch):
    import run

    monkeypatch.setattr(run.Path, "is_file", lambda self: True)
    _, options, _ = run.parse_args(["--learn", "--save-brain", "--brain", str(run.BEST_BRAIN)])
    assert options.brain_path == run.BEST_BRAIN, "it still LOADS the best brain"
    assert options.save_path == run.JOURNEY_BRAIN, "but never writes it"
    _, options, _ = run.parse_args(["--learn", "--save-brain"])
    assert options.save_path == run.JOURNEY_BRAIN
    _, options, _ = run.parse_args(["--learn"])
    assert options.save_path is None and not options.save_brain


def test_the_loop_writes_the_save_path_and_not_the_brain_it_loaded(tmp_path, monkeypatch):
    """The loop's own half of the guard: it writes `save_path`, never
    `brain_path`. Checked on the exit path with a fake emulator."""
    from conftest import ROM

    if not ROM.is_file():
        pytest.skip("roms/pokemon_red.gb not present")
    from flybrain.loop import LoopOptions, run_loop

    cfg = replace(Config(), rom_path=ROM, headless=True, uncapped=True, hud=False, max_steps=30, seed=0)
    loaded = MushroomBody(cfg, cfg.seed).save(tmp_path / "latest.npz", score=179.5, score_episode=100, score_block=6)
    before = loaded.read_bytes()
    journey = tmp_path / "journey.npz"
    run_loop(
        cfg,
        options=LoopOptions(brain_path=loaded, learn=True, save_brain=True, save_path=journey, pause_toggle=lambda: False),
    )
    assert journey.is_file()
    assert loaded.read_bytes() == before
