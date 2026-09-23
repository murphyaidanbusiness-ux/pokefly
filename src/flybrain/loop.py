"""Wiring. `run.py` parses arguments and calls `run_loop(config)`.

One emulator tick is one optic-lobe read, one mushroom-body read, one brain
step, one motor update, one dopamine release. `Fly` holds that tick so the
watching loop here and the training loop in `training.py` run the same code
rather than two copies that drift apart.
"""

from __future__ import annotations

import sys
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace
from pathlib import Path

import numpy as np

from .brain import Brain
from .config import POOL_NAMES, Config, map_name
from .connectome import Connectome, from_edge_list, synthetic
from .emulator import Emulator
from .motor import MotorBridge
from .mushroom_body import MushroomBody
from .optic_lobe import OpticLobe
from .reward import PARTS, RewardTracker

MISSING_ROM_EXIT = 2


@dataclass(frozen=True)
class TickState:
    """Everything one tick produced, handed to every observer.

    Immutable, and `frame` is the emulator's own buffer: an observer that
    wants to keep it past the tick copies it.
    """

    step: int
    frame: np.ndarray  # (144,160) uint8 grayscale
    pressed: tuple[str, ...]  # buttons held at the end of this tick
    started: tuple[str, ...]  # every press that began this tick, panic or not
    action: str | None  # the press that STARTED this tick, or "PANIC"
    excursion: np.ndarray  # (7,) each pool above its own baseline
    firing_rate: float
    dopamine: float  # the TD error this tick
    value: float  # the critic's estimate of the current state
    mbon: np.ndarray  # (7,) the learned bias, before squashing
    reward: float
    reward_parts: dict[str, float]
    episode_reward: float
    map_id: int
    map_name: str
    x: int
    y: int
    in_battle: bool
    panic: bool  # did the anti-stuck reflex fire this tick
    panics: int  # how many times it has fired this episode


class Fly:
    """Optic lobe, spiking brain, mushroom body, motor. One emulator."""

    def __init__(
        self,
        cfg: Config,
        emulator: Emulator,
        connectome: Connectome | None = None,
        mushroom: MushroomBody | None = None,
    ) -> None:
        self.cfg = cfg
        self.emulator = emulator
        self.connectome = build_connectome(cfg) if connectome is None else connectome
        self.optic = OpticLobe(cfg)
        self.brain = Brain(self.connectome, cfg)
        self.motor = MotorBridge(self.connectome, cfg, emulator)
        self.mushroom = MushroomBody(cfg, cfg.seed) if mushroom is None else mushroom
        self.reward = RewardTracker(cfg)
        self.episode_reward = 0.0
        self.positions: set[tuple[int, int, int]] = set()
        self.position: tuple[int, int, int] = (0, 0, 0)

    def reset(self, seed: int | None = None) -> None:
        """Start a fresh episode. The mushroom body's weights survive; its
        traces, the membrane voltages, the motor accumulators and the visited
        sets do not. A new seed varies the optic-lobe noise and the panic
        draws, so two episodes from the same savestate differ."""
        cfg = self.cfg if seed is None else replace(self.cfg, seed=seed)
        self.optic = OpticLobe(cfg)
        self.brain.reset()
        self.motor = MotorBridge(self.connectome, cfg, self.emulator)
        self.mushroom.reset_traces()
        self.reward.reset()
        self.episode_reward = 0.0
        self.positions = set()
        self.position = (0, 0, 0)

    def tick(self, step: int) -> TickState:
        """One emulator frame's worth of fly. The emulator has already ticked.

        Order matters and is the standard actor-critic one: the reward and the
        new state are read first, so the TD error can be computed against
        traces that still hold the state the choice was made in; the weights
        are updated, the traces decay, and only then does this tick's choice
        write into them.
        """
        mb = self.mushroom
        frame = self.emulator.frame()
        current = self.optic.step(frame)
        pulse = self.motor.take_pulse()
        if pulse:
            current = current + pulse

        snapshot = self.emulator.snapshot()
        reward, parts = self.reward.step(snapshot)
        self.episode_reward += reward

        mb.observe(self.optic.retina)
        dopamine = mb.learn(reward)
        mb.decay_traces()

        spikes = self.brain.step(current, mb.pool_currents())
        self.position = (snapshot.map_id, snapshot.x, snapshot.y)
        self.positions.add(self.position)
        action = self.motor.update(spikes, self.position)

        mb.credit(self.motor.chosen)
        mb.credit_critic()
        if mb.learning:
            mb.ticks_trained += 1

        return TickState(
            step=step,
            frame=frame,
            pressed=tuple(sorted(self.motor.held)),
            started=tuple(self.motor.chosen) + tuple(self.motor.panicked),
            action=action,
            excursion=self.motor.excursion,
            firing_rate=self.brain.firing_rate,
            dopamine=dopamine,
            value=mb.value,
            mbon=mb.mbon,
            reward=reward,
            reward_parts=parts,
            episode_reward=self.episode_reward,
            map_id=snapshot.map_id,
            map_name=map_name(snapshot.map_id),
            x=snapshot.x,
            y=snapshot.y,
            in_battle=snapshot.in_battle,
            panic=action == "PANIC",
            panics=self.motor.panic_count,
        )


def build_connectome(cfg: Config) -> Connectome:
    if cfg.connectome_csv is not None:
        return from_edge_list(cfg.connectome_csv, cfg)
    return synthetic(n=cfg.n_neurons, k=cfg.lattice_k, rewire_p=cfg.rewire_p, seed=cfg.seed, cfg=cfg)


def require_rom(cfg: Config) -> Path:
    rom = Path(cfg.rom_path)
    if not rom.is_file():
        print(f"ROM not found: {rom.resolve()}", file=sys.stderr)
        print("Put your own Pokemon Red dump (1 MB, .gb) at that exact path and run again.", file=sys.stderr)
        raise SystemExit(MISSING_ROM_EXIT)
    return rom


@dataclass
class LoopOptions:
    """Things `run.py` decides that are not tunable numbers."""

    brain_path: Path | None = None  # a saved mushroom body to load
    learn: bool = False  # keep learning while watching
    save_brain: bool = False  # write the brain back on exit
    pace_hz: float = 0.0  # >0: sleep so the loop runs at this many ticks a
    # second. PyBoy's null window does not limit speed,
    # so watching a headless run needs this.
    pause_toggle: Callable[[], bool] | None = None  # polled once per tick; True
    # flips pause. None means "read P or Space from the
    # terminal when there is one" (see `terminal_pause_key`).


def terminal_pause_key() -> Callable[[], bool] | None:
    """A non-blocking reader for P or Space on a Windows console, else None.

    A pipe or a redirected stdin has no keyboard, and the POSIX equivalent
    needs termios games this project does not want; there Ctrl+C is the only
    control and the pause key is simply absent.
    """
    try:
        import msvcrt  # Windows only
    except ImportError:
        return None
    if not sys.stdin.isatty():
        return None

    def poll() -> bool:
        hit = False
        while msvcrt.kbhit():
            if msvcrt.getwch().lower() in ("p", " "):
                hit = not hit
        return hit

    return poll


def _hold(emulator: Emulator, fly: Fly, toggle: Callable[[], bool], watchers: list[object]) -> None:
    """Pause: buttons up, nothing ticks, until the key is pressed again.

    The game and the brain both stand still, so what the couch scene shows is
    the last state it was sent; the socket stays open, so the TV keeps the
    last frame rather than going to static.
    """
    fly.motor.release_all()
    print("paused (P or Space to resume, Ctrl+C to quit)", flush=True)
    while not toggle():
        time.sleep(0.05)
    print("resumed", flush=True)


def run_loop(cfg: Config, observers: Iterable[object] = (), options: LoopOptions | None = None) -> dict:
    """Runs until the window closes, Ctrl+C, or `max_steps`.

    Every observer is called with one `TickState` per tick. The display is the
    first one. Returns a summary dict for the caller and the integration test.
    """
    options = options or LoopOptions()
    rom = require_rom(cfg)

    emulator = Emulator(rom, headless=cfg.headless, uncapped=cfg.uncapped, cfg=cfg)
    fly = Fly(cfg, emulator)
    fly.mushroom.learning = options.learn
    if options.brain_path is not None:
        fly.mushroom.load(options.brain_path)
        loaded = (
            f"brain: {Path(options.brain_path).name} "
            f"({fly.mushroom.episodes_trained} episodes, {fly.mushroom.ticks_trained} ticks trained"
            + (", still learning)" if options.learn else ")")
        )
    else:
        loaded = "brain: none (naive fly, no learned bias)"
    print(loaded, flush=True)

    watchers = list(observers)
    for watcher in watchers:
        # The display shows which brain is driving. Anything else that wants to
        # say so has a `title` too; anything that does not is left alone.
        if hasattr(watcher, "title"):
            watcher.title = loaded
        # An observer that needs more than one tick's worth of state asks for
        # the fly itself. The couch scene's spike raster is the only one so
        # far: putting 2000 spike bits on every TickState would cost every
        # other observer something for nothing.
        attach = getattr(watcher, "attach", None)
        if attach is not None:
            attach(fly)
    if cfg.load_state is not None:
        emulator.load_state(cfg.load_state)
        fly.optic.reset()

    step = 0
    map_order: list[int] = []
    period = 1.0 / options.pace_hz if options.pace_hz > 0 else 0.0
    started = time.perf_counter()
    deadline = started + period
    toggle = options.pause_toggle if options.pause_toggle is not None else terminal_pause_key()
    paused_for = 0.0
    try:
        while cfg.max_steps == 0 or step < cfg.max_steps:
            if toggle is not None and toggle():
                held = time.perf_counter()
                _hold(emulator, fly, toggle, watchers)
                paused_for += time.perf_counter() - held
                deadline = time.perf_counter() + period
            if not emulator.tick():
                break
            step += 1
            state = fly.tick(step)
            if not map_order or map_order[-1] != state.map_id:
                map_order.append(state.map_id)
            for watcher in watchers:
                watcher(state)
            if period:
                deadline = _pace(deadline, period)
    except KeyboardInterrupt:
        pass
    finally:
        elapsed = time.perf_counter() - started - paused_for
        fly.motor.release_all()
        if options.save_brain and options.brain_path is not None:
            fly.mushroom.save(options.brain_path)
        if cfg.save_state is not None:
            emulator.save_state(cfg.save_state)
        emulator.close()
        for watcher in watchers:
            close = getattr(watcher, "close", None)
            if close is not None:
                close()

    motor = fly.motor
    summary = {
        "steps": step,
        "seconds": round(elapsed, 2),
        "ticks_per_second": round(step / elapsed, 1) if elapsed > 0 else 0.0,
        "firing_rate": round(fly.brain.firing_rate, 5),
        "presses": dict(motor.fire_counts),
        "total_presses": int(sum(motor.fire_counts.values())),
        "panics": motor.panic_count,
        "distinct_positions": len(fly.positions),
        "final_position": fly.position,
        "moved": len(fly.positions) > 1,
        "map_order": map_order,
        "distinct_maps": sorted(set(map_order)),
        "reward": round(fly.episode_reward, 3),
        "reward_parts": {name: round(value, 3) for name, value in fly.reward.parts.items()},
        "tiles": len(fly.reward.tiles),
    }
    _print_summary(summary, motor, map_order)
    return summary


def _pace(deadline: float, period: float) -> float:
    """Sleep until `deadline`, then return the next one.

    A tick that ran long does not get made up for by a burst of fast ones: the
    next deadline starts from now, so the game slows down rather than stutters.
    """
    now = time.perf_counter()
    if now < deadline:
        time.sleep(deadline - now)
        return deadline + period
    return now + period


def _print_summary(summary: dict, motor: MotorBridge, map_order: list[int]) -> None:
    print(
        f"done: {summary['steps']} steps in {summary['seconds']}s "
        f"({summary['ticks_per_second']} ticks/s), firing {summary['firing_rate'] * 100:.2f}%",
        flush=True,
    )
    print(
        "presses: " + " ".join(f"{name}={motor.fire_counts[name]}" for name in POOL_NAMES)
        + f"  total={summary['total_presses']}  panics={summary['panics']}",
        flush=True,
    )
    print(
        f"positions: {summary['distinct_positions']} distinct (map_id, x, y); "
        f"moved={summary['moved']}; final={summary['final_position']}",
        flush=True,
    )
    print(
        f"reward: {summary['reward']}  "
        + " ".join(f"{name}={summary['reward_parts'][name]}" for name in PARTS)
        + f"  tiles={summary['tiles']}",
        flush=True,
    )
    distinct = summary["distinct_maps"]
    print("maps: " + (", ".join(f"{map_name(m)} ({m})" for m in distinct) or "none"), flush=True)
    route = [f"{m}" for m in map_order]
    tail = f" ... ({len(route) - 40} more)" if len(route) > 40 else ""
    print("route (map ids, in order entered): " + (" -> ".join(route[:40]) + tail or "none"), flush=True)


def measure_step_ms(n: int, seed: int = 0, steps: int = 400, cfg: Config | None = None) -> float:
    """Mean milliseconds per brain step, for the README numbers."""
    cfg = cfg or Config()
    connectome = synthetic(n=n, k=cfg.lattice_k, rewire_p=cfg.rewire_p, seed=seed, cfg=cfg)
    brain = Brain(connectome, cfg)
    rng = np.random.default_rng(seed)
    currents = rng.random((steps, cfg.n_sensory), dtype=np.float32) * cfg.max_current
    for i in range(50):  # warm up
        brain.step(currents[i % steps])
    started = time.perf_counter()
    for i in range(steps):
        brain.step(currents[i])
    return (time.perf_counter() - started) / steps * 1000.0


def measure_learning_ms(seed: int = 0, steps: int = 2000, cfg: Config | None = None) -> float:
    """Mean milliseconds the mushroom body costs per tick: the KC code, both
    readouts, the weight update and both traces."""
    cfg = cfg or Config()
    mb = MushroomBody(cfg, seed)
    rng = np.random.default_rng(seed)
    frames = rng.random((64, cfg.retina_size, cfg.retina_size), dtype=np.float32)
    rewards = (rng.random(steps) < 0.02).astype(np.float32)

    def one(index: int) -> None:
        mb.observe(frames[index % 64])
        mb.learn(float(rewards[index]))
        mb.decay_traces()
        mb.credit(["UP"] if index % 14 == 0 else [])
        mb.credit_critic()
        mb.pool_currents()

    for i in range(100):
        one(i)
    started = time.perf_counter()
    for i in range(steps):
        one(i)
    return (time.perf_counter() - started) / steps * 1000.0
