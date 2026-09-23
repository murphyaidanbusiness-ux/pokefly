"""Episodes. `train.py` parses arguments and calls `train(...)`.

One emulator is kept alive for the whole run and each episode reloads the start
savestate into it, which is far cheaper than building a PyBoy per episode. What
carries across an episode boundary is exactly the mushroom body's weights; the
traces, the membrane voltages, the motor accumulators and the visited-tile sets
all go.

Episode seeds vary, so the optic-lobe noise and the panic draws differ run to
run and the fly is not replaying one trajectory forever.

Training keeps two files. The training state (`out`) is always the latest
weights and is what `--resume` continues. The best brain (`best`) is what
`run.py` loads: every `eval_every` training episodes an evaluation block of
`eval_block` learning-off episodes on the SAME fixed seeds scores the current
weights, and they are copied to `best` only when the block beats the best score
so far. Continued training can wander; the brain you watch cannot get worse.
"""

from __future__ import annotations

import csv
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .config import POOL_NAMES, Config, furthest_map, map_name, map_progress
from .emulator import Emulator
from .loop import Fly, require_rom
from .mushroom_body import MushroomBody
from .reward import PARTS, has_control

# Red's house 2F: where `--make-start-state` stops and saves.
BEDROOM_MAP = 0x26
# Pallet Town, the primary acceptance of the learning experiment.
PALLET_TOWN = 0x00

CSV_FIELDS = (
    "episode",
    "kind",
    "ticks",
    "reward",
    *(f"reward_{name}" for name in PARTS),
    "tiles",
    "maps",
    "furthest",
    "left_house",
    *(f"press_{name}" for name in POOL_NAMES),
    "panics",
    "mean_abs_delta",
    "w_actor_abs",
    "w_critic_abs",
    "lr_actor",
    "lr_critic",
    "ticks_per_second",
    "seed",
)


@dataclass
class EpisodeResult:
    episode: int
    kind: str  # "train" or "eval"
    ticks: int
    reward: float
    parts: dict[str, float]
    tiles: int
    maps: list[int]
    furthest: int | None
    left_house: bool
    presses: dict[str, int]
    panics: int
    mean_abs_delta: float
    w_actor_abs: float
    w_critic_abs: float
    ticks_per_second: float
    seed: int
    # The learning rates this episode actually ran at: the schedule's value for
    # a training episode, 0 for a learning-off one.
    lr_actor: float = 0.0
    lr_critic: float = 0.0

    def row(self) -> dict:
        row = {
            "episode": self.episode,
            "kind": self.kind,
            "ticks": self.ticks,
            "reward": round(self.reward, 3),
            "tiles": self.tiles,
            "maps": " ".join(str(m) for m in self.maps),
            "furthest": "" if self.furthest is None else self.furthest,
            "left_house": int(self.left_house),
            "panics": self.panics,
            "mean_abs_delta": round(self.mean_abs_delta, 5),
            "w_actor_abs": round(self.w_actor_abs, 6),
            "w_critic_abs": round(self.w_critic_abs, 6),
            "lr_actor": f"{self.lr_actor:.6g}",
            "lr_critic": f"{self.lr_critic:.6g}",
            "ticks_per_second": round(self.ticks_per_second, 1),
            "seed": self.seed,
        }
        row.update({f"reward_{name}": round(self.parts[name], 3) for name in PARTS})
        row.update({f"press_{name}": self.presses[name] for name in POOL_NAMES})
        return row

    def line(self) -> str:
        furthest = "-" if self.furthest is None else f"{map_name(self.furthest)}"
        return (
            f"ep {self.episode:4d} {self.kind:<5s} reward {self.reward:8.1f}  "
            f"tiles {self.tiles:4d}  maps {len(set(self.maps)):2d}  furthest {furthest:<16s} "
            f"left_house {int(self.left_house)}  |delta| {self.mean_abs_delta:.4f}  "
            f"|w_a| {self.w_actor_abs:.5f}  |w_c| {self.w_critic_abs:.5f}  lr {self.lr_actor:.2e}  "
            f"{self.ticks_per_second:6.0f} tick/s"
        )


def run_episode(
    fly: Fly,
    ticks: int,
    seed: int,
    *,
    learning: bool,
    episode: int = 0,
    kind: str = "train",
    state_path: Path | None = None,
    observers: Iterable[object] = (),
) -> EpisodeResult:
    """One episode from the start state. Returns its row."""
    if state_path is not None:
        fly.emulator.load_state(state_path)
    fly.reset(seed=seed)
    fly.mushroom.learning = learning
    lr_actor = fly.mushroom.lr_actor if learning else 0.0
    lr_critic = fly.mushroom.lr_critic if learning else 0.0
    watchers = list(observers)

    deltas = np.zeros(ticks, dtype=np.float32)
    started = time.perf_counter()
    done = 0
    for step in range(1, ticks + 1):
        if not fly.emulator.tick():
            break
        state = fly.tick(step)
        deltas[step - 1] = state.dopamine
        done = step
        for watcher in watchers:
            watcher(state)
    elapsed = max(time.perf_counter() - started, 1e-9)
    fly.motor.release_all()

    maps = list(fly.reward.map_order)
    w_actor_abs, w_critic_abs = fly.mushroom.weight_norms
    if learning:
        fly.mushroom.episodes_trained += 1
    return EpisodeResult(
        episode=episode,
        kind=kind,
        ticks=done,
        reward=fly.episode_reward,
        parts=dict(fly.reward.parts),
        tiles=len(fly.reward.tiles),
        maps=maps,
        furthest=furthest_map(fly.reward.maps),
        left_house=PALLET_TOWN in fly.reward.maps,
        presses=dict(fly.motor.fire_counts),
        panics=fly.motor.panic_count,
        mean_abs_delta=float(np.abs(deltas[:done]).mean()) if done else 0.0,
        w_actor_abs=w_actor_abs,
        w_critic_abs=w_critic_abs,
        ticks_per_second=done / elapsed,
        seed=seed,
        lr_actor=lr_actor,
        lr_critic=lr_critic,
    )


def make_start_state(cfg: Config, target: Path, max_ticks: int = 400_000) -> Path:
    """Run the UNTRAINED fly headless from a cold boot until it is standing in
    Red's bedroom with control and has moved at least twice, then save.

    Nothing is scripted here: this is the same naive fly the baseline uses,
    mashing its way through the intro and the name entry, which is what it did
    in the v1 run log. It just takes a while, so the result is saved once and
    every episode starts from it.
    """
    rom = require_rom(cfg)
    emulator = Emulator(rom, headless=True, uncapped=True, cfg=cfg)
    fly = Fly(cfg, emulator)
    fly.mushroom.learning = False
    moves = 0
    last: tuple[int, int, int] | None = None
    reached = False
    try:
        for step in range(1, max_ticks + 1):
            if not emulator.tick():
                break
            state = fly.tick(step)
            snapshot = emulator.snapshot()
            if not has_control(snapshot) or snapshot.map_id != BEDROOM_MAP:
                moves, last = 0, None
                continue
            here = (state.map_id, state.x, state.y)
            if last is not None and here != last:
                moves += 1
            last = here
            if moves >= 2:
                reached = True
                break
        if not reached:
            raise RuntimeError(
                f"the naive fly did not reach Red's bedroom with control in {max_ticks} ticks; "
                "run it again with a different --seed"
            )
        # Let go of whatever is held, so the savestate is not mid-press.
        fly.motor.release_all()
        for _ in range(8):
            emulator.tick()
        emulator.save_state(target)
        print(f"start state written: {target} (after {step} ticks from cold boot)", flush=True)
    finally:
        emulator.close()
    return target


class CsvLog:
    """One row per episode, appended, header written once.

    Appending to a file written with a different header would misalign every
    column after the first difference, so that is refused up front: move the
    old file or pass another `--log`.
    """

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._new = not self.path.exists() or self.path.stat().st_size == 0
        if not self._new:
            with self.path.open(newline="", encoding="utf-8") as handle:
                header = next(csv.reader(handle), [])
            if tuple(header) != CSV_FIELDS:
                raise ValueError(
                    f"{self.path} was written with different columns (an older version of train.py); "
                    "move it aside or pass another --log"
                )

    def write(self, result: EpisodeResult) -> None:
        with self.path.open("a", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
            if self._new:
                writer.writeheader()
                self._new = False
            writer.writerow(result.row())


def read_score(path: Path) -> tuple[float | None, int | None]:
    """The block score a brain file records and the episode it came from, or
    (None, None) for a brain written before best-keeping."""
    with np.load(Path(path)) as data:
        if "score" not in data.files:
            return None, None
        return float(data["score"]), int(data["score_episode"])


class BestKeeper:
    """The best-brain file: written only when a block score beats every score
    before it, and the file carries that score and the episode it came from."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.score: float | None = None
        self.episode: int | None = None

    def offer(self, mushroom: MushroomBody, score: float, episode: int) -> bool:
        """Write `mushroom` as the best brain if `score` beats the best so far.
        A tie keeps the older brain: same evidence, fewer updates since."""
        if self.score is not None and score <= self.score:
            return False
        mushroom.save(self.path, score=score, score_episode=episode)
        self.score, self.episode = float(score), int(episode)
        return True

    def describe(self) -> str:
        if self.score is None:
            return "no best yet"
        return f"best {self.score:.1f} from episode {self.episode}"


class Trainer:
    """The training loop, with the game left to a subclass.

    `train_episode` and `eval_episode` are the only two things that touch a
    game. Everything else, when the evaluation blocks run, which brain gets
    kept, what is checkpointed when and what a Ctrl+C leaves behind, lives
    here, so a test can drive all of it with scripted episodes and no ROM.
    """

    def __init__(
        self,
        cfg: Config,
        mushroom: MushroomBody,
        *,
        out: Path,
        best: Path | None,
        log: CsvLog | None = None,
        episode_ticks: int | None = None,
        eval_every: int | None = None,
        eval_block: int | None = None,
        say: Callable[[str], None] | None = None,
    ) -> None:
        self.cfg = cfg
        self.mushroom = mushroom
        self.out = Path(out)
        self.episode_ticks = cfg.episode_ticks if episode_ticks is None else episode_ticks
        self.eval_every = cfg.eval_every if eval_every is None else eval_every
        self.eval_block = cfg.eval_block if eval_block is None else eval_block
        # No evaluation blocks means no scores, so nothing to keep a best by.
        keeping = best is not None and self.eval_every > 0 and self.eval_block > 0
        self.best = BestKeeper(best) if keeping else None
        self.log = log
        self.say = say or (lambda line: print(line, flush=True))
        self.results: list[EpisodeResult] = []
        self.spent = 0

    # -- what a subclass supplies ---------------------------------------------

    def train_episode(self, episode: int, ticks: int, seed: int) -> EpisodeResult:
        raise NotImplementedError

    def eval_episode(self, episode: int, seed: int) -> EpisodeResult:
        raise NotImplementedError

    # -- the loop -------------------------------------------------------------

    @property
    def block_seeds(self) -> tuple[int, ...]:
        """The same seeds for every block, so two block scores differ only
        because the weights differ."""
        base = self.cfg.seed + self.cfg.eval_block_seed
        return tuple(base + index for index in range(self.eval_block))

    def _record(self, result: EpisodeResult) -> None:
        self.results.append(result)
        if self.log is not None:
            self.log.write(result)
        self.say(result.line())

    def block(self, episode: int) -> float:
        """One evaluation block of `self.mushroom`, learning off. The score is
        the mean reward over the block."""
        rewards = []
        for seed in self.block_seeds:
            result = self.eval_episode(episode, seed)
            self._record(result)
            rewards.append(result.reward)
        return float(np.mean(rewards))

    def _score_other(self, brain: MushroomBody, episode: int) -> float:
        """A block for a brain that is not the one being trained. The swap is
        undone however the block ends, so a Ctrl+C in here still checkpoints
        the training weights and not these."""
        held = self.mushroom
        self.mushroom = brain
        try:
            return self.block(episode)
        finally:
            self.mushroom = held

    def seed_best(self, resumed: bool) -> None:
        """Before any training: know what the best file is worth, and give a
        resumed brain its chance, so the best is never silently a worse brain.

        A best file with no recorded score (written before best-keeping) is
        evaluated and its score written into it. A resumed brain with no score
        is evaluated too, unless its weights are the best file's, whose score
        it then shares.
        """
        keeper = self.best
        if keeper is None:
            return
        on_disk: MushroomBody | None = None
        if keeper.path.is_file():
            on_disk = MushroomBody(self.cfg, self.mushroom.seed)
            on_disk.load(keeper.path)
            if on_disk.score is None:
                self.say(f"best brain {keeper.path} has no score: evaluating it")
                score = self._score_other(on_disk, on_disk.episodes_trained)
                on_disk.save(keeper.path, score=score, score_episode=on_disk.episodes_trained)
                keeper.score, keeper.episode = score, on_disk.episodes_trained
            else:
                keeper.score, keeper.episode = on_disk.score, on_disk.score_episode
            self.say(f"best brain {keeper.path}: {keeper.describe()}")
        if not resumed:
            return

        mine = self.mushroom
        if mine.score is not None:
            score, episode = mine.score, mine.score_episode
        elif (
            on_disk is not None
            and np.array_equal(on_disk.w_actor, mine.w_actor)
            and np.array_equal(on_disk.w_critic, mine.w_critic)
        ):
            self.say("resumed brain is the best brain's weights: it shares that score")
            score, episode = keeper.score, keeper.episode
        else:
            self.say("resumed brain has no score: evaluating it before training")
            score, episode = self.block(mine.episodes_trained), mine.episodes_trained
        if keeper.offer(mine, score, episode):
            self.say(f"resumed brain is the best so far ({score:.1f}): written to {keeper.path}")

    def _evaluate_and_keep(self, episode: int) -> None:
        score = self.block(episode)
        improved = self.best.offer(self.mushroom, score, episode)
        self.say(
            f"block after episode {episode}: score {score:.1f}; {self.best.describe()}"
            + (f"  <- new best, written to {self.best.path}" if improved else "")
        )

    def run(self, total_ticks: int, *, resumed: bool = False) -> list[EpisodeResult]:
        """Train for `total_ticks` training ticks (blocks are not counted).

        The training state is checkpointed every `checkpoint_every` episodes
        and on the way out, Ctrl+C included. The best file is only ever
        written whole (see `MushroomBody.save`) and only after a finished
        block, so an interrupt can leave it behind the training state but
        never out of step with its own recorded score.
        """
        cfg = self.cfg
        episode = self.mushroom.episodes_trained
        last_block = None
        try:
            self.seed_best(resumed)
            while self.spent < total_ticks:
                episode += 1
                budget = min(self.episode_ticks, total_ticks - self.spent)
                result = self.train_episode(episode, budget, cfg.seed + 1000 * episode)
                # Whatever score these weights had is stale now.
                self.mushroom.score = self.mushroom.score_episode = None
                self.spent += result.ticks
                self._record(result)
                if self.best is not None and episode % self.eval_every == 0:
                    self._evaluate_and_keep(episode)
                    last_block = episode
                if episode % cfg.checkpoint_every == 0:
                    self.mushroom.save(self.out)
            # The weights the run ended on get their block too.
            if self.best is not None and self.spent and last_block != episode:
                self._evaluate_and_keep(episode)
        except KeyboardInterrupt:
            self.say("interrupted; checkpointing the training state")
        finally:
            self.mushroom.save(self.out)
        return self.results


class EmulatorTrainer(Trainer):
    """The Trainer on the real game: one emulator, one Fly, the start state
    reloaded every episode."""

    def __init__(self, cfg: Config, fly: Fly, state_path: Path, **kwargs) -> None:
        super().__init__(cfg, fly.mushroom, **kwargs)
        self.fly = fly
        self.state_path = Path(state_path)

    def train_episode(self, episode: int, ticks: int, seed: int) -> EpisodeResult:
        self.fly.mushroom = self.mushroom
        return run_episode(
            self.fly, ticks, seed, learning=True, episode=episode, kind="train", state_path=self.state_path
        )

    def eval_episode(self, episode: int, seed: int) -> EpisodeResult:
        self.fly.mushroom = self.mushroom
        return run_episode(
            self.fly,
            self.episode_ticks,
            seed,
            learning=False,
            episode=episode,
            kind="block",
            state_path=self.state_path,
        )


def train(
    cfg: Config,
    *,
    total_ticks: int | None = None,
    episode_ticks: int | None = None,
    out: Path | None = None,
    best: Path | None = None,
    keep_best: bool = True,
    log_path: Path | None = None,
    state_path: Path | None = None,
    resume: bool = False,
    eval_every: int | None = None,
    eval_block: int | None = None,
) -> list[EpisodeResult]:
    """The training run. Returns every episode result, blocks included.

    `out` is the training state (default `cfg.training_state_path`), `best`
    the best brain (default `cfg.best_brain_path`). `eval_every=0` or
    `keep_best=False` trains with no blocks and never touches `best`.
    """
    total_ticks = cfg.train_ticks if total_ticks is None else total_ticks
    episode_ticks = cfg.episode_ticks if episode_ticks is None else episode_ticks
    out = Path(cfg.training_state_path if out is None else out)
    best = Path(cfg.best_brain_path if best is None else best) if keep_best else None
    log_path = Path(cfg.train_log_path if log_path is None else log_path)
    state_path = Path(cfg.start_state_path if state_path is None else state_path)

    rom = require_rom(cfg)
    if resume and not out.is_file():
        raise FileNotFoundError(
            f"--resume: no training state at {out}. To continue from a brain you already have, "
            f"copy it there first (for example brains/latest.npz to {out})."
        )
    if not state_path.is_file():
        print(f"no start state at {state_path}; making one with the naive fly", flush=True)
        make_start_state(cfg, state_path)

    log = CsvLog(log_path)
    emulator = Emulator(rom, headless=True, uncapped=True, cfg=cfg)
    fly = Fly(cfg, emulator)
    if resume:
        fly.mushroom.load(out)
        print(
            f"resumed {out}: {fly.mushroom.episodes_trained} episodes, "
            f"{fly.mushroom.ticks_trained} ticks trained, learning rate now {fly.mushroom.lr_scale:.3f} x lr0",
            flush=True,
        )

    trainer = EmulatorTrainer(
        cfg,
        fly,
        state_path,
        out=out,
        best=best,
        log=log,
        episode_ticks=episode_ticks,
        eval_every=eval_every,
        eval_block=eval_block,
    )
    started = time.perf_counter()
    try:
        results = trainer.run(total_ticks, resumed=resume)
    finally:
        emulator.close()

    elapsed = time.perf_counter() - started
    ticks_all = sum(r.ticks for r in results)
    print(
        f"trained {trainer.spent} ticks over {sum(r.kind == 'train' for r in results)} training episodes "
        f"({ticks_all} ticks with the blocks) in {elapsed / 60:.1f} min "
        f"({ticks_all / max(elapsed, 1e-9):.0f} ticks/s overall); training state at {out}",
        flush=True,
    )
    if trainer.best is not None:
        print(f"best brain at {trainer.best.path}: {trainer.best.describe()}", flush=True)
    return results


def evaluate(
    cfg: Config,
    *,
    brain_path: Path | None,
    episodes: int = 10,
    episode_ticks: int | None = None,
    state_path: Path | None = None,
    base_seed: int = 90_000,
    label: str = "eval",
    log_path: Path | None = None,
) -> list[EpisodeResult]:
    """The experiment's evaluation block: N episodes with learning OFF, same
    seeds whichever brain is loaded, so naive and trained are comparable.
    `log_path` also writes one CSV row per episode."""
    log = None if log_path is None else CsvLog(log_path)
    episode_ticks = cfg.episode_ticks if episode_ticks is None else episode_ticks
    state_path = Path(cfg.start_state_path if state_path is None else state_path)
    rom = require_rom(cfg)
    emulator = Emulator(rom, headless=True, uncapped=True, cfg=cfg)
    fly = Fly(cfg, emulator)
    if brain_path is not None:
        fly.mushroom.load(brain_path)
        if fly.mushroom.score is not None:
            print(
                f"{brain_path}: block score {fly.mushroom.score:.1f} from episode {fly.mushroom.score_episode}",
                flush=True,
            )
    results = []
    try:
        for index in range(episodes):
            result = run_episode(
                fly,
                episode_ticks,
                seed=base_seed + index,
                learning=False,
                episode=index + 1,
                kind=label,
                state_path=state_path,
            )
            results.append(result)
            if log is not None:
                log.write(result)
            print(result.line(), flush=True)
    finally:
        emulator.close()
    return results


def learning_curve(results: Iterable[EpisodeResult], bucket: int = 10) -> list[dict]:
    """Training episodes grouped into buckets: mean reward, share that left the
    house, mean tiles, and where the weights and the learning rate stood at the
    bucket's last episode. This is what goes in the README."""
    train_only = [r for r in results if r.kind == "train"]
    rows = []
    for start in range(0, len(train_only), bucket):
        chunk = train_only[start : start + bucket]
        if not chunk:
            continue
        rows.append(
            {
                "episodes": f"{chunk[0].episode}-{chunk[-1].episode}",
                "n": len(chunk),
                "mean_reward": round(sum(r.reward for r in chunk) / len(chunk), 1),
                "mean_tiles": round(sum(r.tiles for r in chunk) / len(chunk), 1),
                "left_house": round(sum(r.left_house for r in chunk) / len(chunk), 2),
                "best_progress": max((map_progress(m) for r in chunk for m in r.maps), default=-1),
                "w_actor_abs": chunk[-1].w_actor_abs,
                "w_critic_abs": chunk[-1].w_critic_abs,
                "lr_actor": chunk[-1].lr_actor,
            }
        )
    return rows
