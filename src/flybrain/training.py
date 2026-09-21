"""Episodes. `train.py` parses arguments and calls `train(...)`.

One emulator is kept alive for the whole run and each episode reloads the start
savestate into it, which is far cheaper than building a PyBoy per episode. What
carries across an episode boundary is exactly the mushroom body's weights; the
traces, the membrane voltages, the motor accumulators and the visited-tile sets
all go.

Episode seeds vary, so the optic-lobe noise and the panic draws differ run to
run and the fly is not replaying one trajectory forever.
"""

from __future__ import annotations

import csv
import time
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .config import POOL_NAMES, Config, furthest_map, map_name, map_progress
from .emulator import Emulator
from .loop import Fly, require_rom
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
            f"|w_a| {self.w_actor_abs:.5f}  {self.ticks_per_second:6.0f} tick/s"
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
    """One row per episode, appended, header written once."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._new = not self.path.exists()

    def write(self, result: EpisodeResult) -> None:
        with self.path.open("a", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
            if self._new:
                writer.writeheader()
                self._new = False
            writer.writerow(result.row())


def train(
    cfg: Config,
    *,
    total_ticks: int | None = None,
    episode_ticks: int | None = None,
    out: Path | None = None,
    log_path: Path | None = None,
    state_path: Path | None = None,
    resume: bool = False,
    eval_every: int | None = None,
) -> list[EpisodeResult]:
    """The training run. Returns every episode result, and checkpoints as it
    goes so a Ctrl+C never loses one."""
    total_ticks = cfg.train_ticks if total_ticks is None else total_ticks
    episode_ticks = cfg.episode_ticks if episode_ticks is None else episode_ticks
    eval_every = cfg.eval_every if eval_every is None else eval_every
    out = Path(cfg.brain_path if out is None else out)
    log_path = Path(cfg.train_log_path if log_path is None else log_path)
    state_path = Path(cfg.start_state_path if state_path is None else state_path)

    rom = require_rom(cfg)
    if not state_path.is_file():
        print(f"no start state at {state_path}; making one with the naive fly", flush=True)
        make_start_state(cfg, state_path)

    emulator = Emulator(rom, headless=True, uncapped=True, cfg=cfg)
    fly = Fly(cfg, emulator)
    if resume and out.is_file():
        fly.mushroom.load(out)
        print(
            f"resumed {out}: {fly.mushroom.episodes_trained} episodes, "
            f"{fly.mushroom.ticks_trained} ticks trained",
            flush=True,
        )

    log = CsvLog(log_path)
    results: list[EpisodeResult] = []
    spent = 0
    episode = fly.mushroom.episodes_trained
    started = time.perf_counter()
    try:
        while spent < total_ticks:
            episode += 1
            budget = min(episode_ticks, total_ticks - spent)
            result = run_episode(
                fly,
                budget,
                seed=cfg.seed + 1000 * episode,
                learning=True,
                episode=episode,
                kind="train",
                state_path=state_path,
            )
            spent += result.ticks
            results.append(result)
            log.write(result)
            print(result.line(), flush=True)

            if eval_every and episode % eval_every == 0:
                evaluation = run_episode(
                    fly,
                    episode_ticks,
                    seed=cfg.seed + 7_000_000 + episode,
                    learning=False,
                    episode=episode,
                    kind="eval",
                    state_path=state_path,
                )
                results.append(evaluation)
                log.write(evaluation)
                print(evaluation.line(), flush=True)
            if episode % cfg.checkpoint_every == 0:
                fly.mushroom.save(out)
    except KeyboardInterrupt:
        print("interrupted; checkpointing", flush=True)
    finally:
        fly.mushroom.save(out)
        emulator.close()

    elapsed = time.perf_counter() - started
    print(
        f"trained {spent} ticks over {len(results)} episodes in {elapsed / 60:.1f} min "
        f"({spent / max(elapsed, 1e-9):.0f} ticks/s); brain at {out}",
        flush=True,
    )
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
) -> list[EpisodeResult]:
    """The experiment's evaluation block: N episodes with learning OFF, same
    seeds whichever brain is loaded, so naive and trained are comparable."""
    episode_ticks = cfg.episode_ticks if episode_ticks is None else episode_ticks
    state_path = Path(cfg.start_state_path if state_path is None else state_path)
    rom = require_rom(cfg)
    emulator = Emulator(rom, headless=True, uncapped=True, cfg=cfg)
    fly = Fly(cfg, emulator)
    if brain_path is not None:
        fly.mushroom.load(brain_path)
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
            print(result.line(), flush=True)
    finally:
        emulator.close()
    return results


def learning_curve(results: Iterable[EpisodeResult], bucket: int = 10) -> list[dict]:
    """Training episodes grouped into buckets: mean reward, share that left the
    house, mean tiles. This is what goes in the README."""
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
            }
        )
    return rows
