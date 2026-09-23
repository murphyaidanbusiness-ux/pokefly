"""Wiring. `run.py` parses arguments and calls `run_loop(config)`.

One emulator tick is one optic-lobe read, one mushroom-body read, one brain
step, one motor update, one dopamine release. `Fly` holds that tick so the
watching loop here and the training loop in `training.py` run the same code
rather than two copies that drift apart.
"""

from __future__ import annotations

import signal
import sys
import threading
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field, replace
from pathlib import Path

import numpy as np

from .brain import Brain
from .config import POOL_NAMES, Config, dynamics_fingerprint, map_name
from .connectome import Connectome, from_edge_list, synthetic
from .emulator import Emulator
from .milestones import LABELS, MilestoneTracker, game_time, read_tick_offset, write_tick_offset
from .motor import MotorBridge
from .mushroom_body import MushroomBody
from .optic_lobe import OpticLobe
from .reward import PARTS, RewardTracker
from .snapshot import FlySnapshot, SnapshotMismatch

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
    # The journey. Defaults so a test can build a TickState without them.
    game_tick: int = 0  # ticks of game time since the cold boot (60 a second)
    milestone: str | None = None  # the milestone that landed this tick, if any
    milestones: tuple[str, ...] = ()  # all of them, in the rare tick two land
    since_milestone: int = 0  # game ticks since the last one (or since the run began)
    last_milestone: str | None = None  # the most recent one this run
    brain: str = ""  # which brain file is driving, for the milestone line
    brain_episodes: int = 0  # its episodes_trained: the brain's generation


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
        self.clock = 0  # game ticks since the cold boot
        self.milestones = MilestoneTracker(cfg)
        self.brain_label = ""  # the brain file's name, for the milestone line
        # Journey mode: a learning brain's episode count advances once per
        # `journey_episode_ticks` learning ticks, so the learning-rate schedule
        # keeps decaying while it is watched.
        self.hourly_schedule = False

    def reset(self, seed: int | None = None, clock: int = 0) -> None:
        """Start a fresh episode. The mushroom body's weights survive; its
        traces, the membrane voltages, the motor accumulators and the visited
        sets do not. A new seed varies the optic-lobe noise and the panic
        draws, so two episodes from the same savestate differ. `clock` is the
        game tick the episode starts at: the start state's own offset."""
        cfg = self.cfg if seed is None else replace(self.cfg, seed=seed)
        self.optic = OpticLobe(cfg)
        self.brain.reset()
        self.motor = MotorBridge(self.connectome, cfg, self.emulator)
        self.mushroom.reset_traces()
        self.reward.reset()
        self.episode_reward = 0.0
        self.positions = set()
        self.position = (0, 0, 0)
        self.set_clock(clock)

    def set_clock(self, clock: int) -> None:
        """Start the game clock here, with no milestones yet this run."""
        self.clock = int(clock)
        self.milestones.reset(self.clock)

    # -- snapshots ---------------------------------------------------------

    def snapshot(self, full: bool = False) -> FlySnapshot:
        """Everything that decides the next tick. `full` pays for a fresh
        emulator savestate (about 20 ms) so the snapshot needs no
        fast-forward; otherwise the emulator half is its last anchor plus the
        buttons pressed since, which costs next to nothing."""
        if full:
            self.emulator.anchor()
        positions = np.array(sorted(self.positions), dtype=np.int32).reshape(-1, 3)
        return FlySnapshot(
            emulator=self.emulator.point(),
            parts={
                "brain": self.brain.get_state(),
                "optic": self.optic.get_state(),
                "motor": self.motor.get_state(),
                "mushroom": self.mushroom.get_state(),
                "reward": self.reward.get_state(),
                "milestones": self.milestones.get_state(),
                "fly": {
                    "episode_reward": self.episode_reward,
                    "positions": positions,
                    "position": list(self.position),
                    "clock": self.clock,
                    "hourly_schedule": self.hourly_schedule,
                    "brain_label": self.brain_label,
                },
            },
            fingerprint=dynamics_fingerprint(self.cfg),
            meta={"game_tick": self.clock, "game_time": game_time(self.clock)},
        )

    def restore(self, snapshot: FlySnapshot) -> None:
        """Put the fly and its emulator exactly where `snapshot` was."""
        mine = dynamics_fingerprint(self.cfg)
        if snapshot.fingerprint != mine:
            raise SnapshotMismatch(
                f"this snapshot was taken from a fly built with other numbers (config fingerprint "
                f"{snapshot.fingerprint}, this one {mine}): seed, neuron count or a tuning value differs"
            )
        self.emulator.restore(snapshot.emulator)
        parts = snapshot.parts
        self.brain.set_state(parts["brain"])
        self.optic.set_state(parts["optic"])
        self.motor.set_state(parts["motor"])
        self.mushroom.set_state(parts["mushroom"])
        self.reward.set_state(parts["reward"])
        self.milestones.set_state(parts["milestones"])
        own = parts["fly"]
        self.episode_reward = float(own["episode_reward"])
        self.positions = {tuple(int(v) for v in row) for row in np.asarray(own["positions"]).reshape(-1, 3)}
        self.position = tuple(int(v) for v in own["position"])
        self.clock = int(own["clock"])
        self.hourly_schedule = bool(own["hourly_schedule"])
        self.brain_label = str(own.get("brain_label", ""))

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
        self.clock += 1
        landed = self.milestones.update(snapshot, self.clock)

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
            if self.hourly_schedule and mb.ticks_trained % self.cfg.journey_episode_ticks == 0:
                mb.episodes_trained += 1

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
            game_tick=self.clock,
            milestone=landed[0] if landed else None,
            milestones=landed,
            since_milestone=self.milestones.since(self.clock),
            last_milestone=self.milestones.last,
            brain=self.brain_label,
            brain_episodes=mb.episodes_trained,
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
    learn: bool | None = False  # keep learning while watching. None, with a
    # `start` snapshot: whatever the snapshot was doing
    # (a replay has to learn exactly as the original did).
    save_brain: bool = False  # write the learned brain on exit, to `save_path`
    save_path: Path | None = None  # where `save_brain` writes. run.py never lets
    # this be the best brain (see `run.brain_save_target`).
    pace_hz: float = 0.0  # >0: sleep so the loop runs at this many ticks a
    # second. PyBoy's null window does not limit speed,
    # so watching a headless run needs this.
    pause_toggle: Callable[[], bool] | None = None  # polled once per tick; True
    # flips pause. None means "read the terminal when
    # there is one" (see `terminal_keys`).
    start: FlySnapshot | None = None  # restore this fly instead of booting or
    # loading a state: a journey save or a replay
    brain_label: str | None = None  # how the milestone line names the brain
    hourly_schedule: bool = False  # journey mode: see `Fly.hourly_schedule`
    recorder: object | None = None  # a MilestoneRecorder: journey log and replays
    journey: object | None = None  # a JourneySession: autosave and Save
    commands: list[Callable[[], Iterable[str]]] = field(default_factory=list)
    # each polled once per tick for "pause" and "save"
    # (the couch's buttons arrive this way)
    on_start: Callable[[object], None] | None = None  # called with the fly once
    # it is set up, before the first tick


def terminal_keys() -> Callable[[], list[str]] | None:
    """A non-blocking reader for the terminal's keys on a Windows console:
    P or Space is "pause", S is "save". None when there is no keyboard.

    A pipe or a redirected stdin has no keyboard, and the POSIX equivalent
    needs termios games this project does not want; there Ctrl+C is the only
    control and the keys are simply absent.
    """
    try:
        import msvcrt  # Windows only
    except ImportError:
        return None
    if not sys.stdin.isatty():
        return None

    def poll() -> list[str]:
        commands = []
        while msvcrt.kbhit():
            key = msvcrt.getwch().lower()
            if key in ("p", " "):
                commands.append("pause")
            elif key == "s":
                commands.append("save")
        return commands

    return poll


class _StopFlag:
    """Ctrl+C as a flag the loop reads between ticks, so a tick is never cut
    in half and an exit save is always of a whole tick. A second Ctrl+C
    raises as usual, for a loop that has stopped reading the flag.

    Signal handlers belong to the main thread; anywhere else this does
    nothing and Ctrl+C is the old KeyboardInterrupt.
    """

    def __init__(self) -> None:
        self.hit = False
        self._old = None

    def _handler(self, signum, frame) -> None:
        if self.hit:
            raise KeyboardInterrupt
        self.hit = True

    def __enter__(self) -> _StopFlag:
        if threading.current_thread() is threading.main_thread():
            try:
                self._old = signal.signal(signal.SIGINT, self._handler)
            except (ValueError, OSError):
                self._old = None
        return self

    def __exit__(self, *exc) -> None:
        if self._old is not None:
            signal.signal(signal.SIGINT, self._old)


def _poll(sources: list[Callable[[], Iterable[str]]]) -> list[str]:
    commands: list[str] = []
    for source in sources:
        try:
            commands.extend(source())
        except Exception:  # a broken source must never stop the game
            continue
    return commands


def _notify(watchers: list[object], hook: str, *args) -> None:
    for watcher in watchers:
        method = getattr(watcher, hook, None)
        if method is not None:
            method(*args)


def _hold(
    fly: Fly,
    toggle: Callable[[], bool] | None,
    sources: list[Callable[[], Iterable[str]]],
    journey,
    stop: _StopFlag,
    watchers: list[object],
) -> None:
    """Pause: buttons up, nothing ticks, until the key is pressed again.

    The game and the brain both stand still, so what the couch scene shows is
    the last state it was sent; the socket stays open, so the TV keeps the
    last frame rather than going to static. A save asked for while paused is
    made at once.
    """
    fly.motor.release_all()
    _notify(watchers, "on_pause", True)
    print("paused (P, Space or the Pause button to resume, Ctrl+C to quit)", flush=True)
    while not stop.hit:
        if toggle is not None and toggle():
            break
        commands = _poll(sources)
        if "save" in commands and journey is not None:
            journey.save(fly, "on request")
            _notify(watchers, "on_pause", True)
        if "pause" in commands:
            break
        time.sleep(0.05)
    _notify(watchers, "on_pause", False)
    print("resumed", flush=True)


def _set_up(cfg: Config, fly: Fly, emulator: Emulator, options: LoopOptions) -> str:
    """Brain, start point and clock. Returns the line saying which brain."""
    if options.start is not None:
        fly.restore(options.start)
        if options.learn is not None:
            fly.mushroom.learning = bool(options.learn)
        if options.brain_label is not None:
            fly.brain_label = options.brain_label
        fly.hourly_schedule = options.hourly_schedule or fly.hourly_schedule
        mb = fly.mushroom
        return (
            f"brain: {fly.brain_label or 'none'} ({mb.episodes_trained} episodes, {mb.ticks_trained} ticks trained"
            + (", still learning)" if mb.learning else ")")
        )

    fly.mushroom.learning = bool(options.learn)
    fly.hourly_schedule = options.hourly_schedule
    if options.brain_path is not None:
        fly.mushroom.load(options.brain_path)
        fly.brain_label = options.brain_label or Path(options.brain_path).name
        loaded = (
            f"brain: {fly.brain_label} "
            f"({fly.mushroom.episodes_trained} episodes, {fly.mushroom.ticks_trained} ticks trained"
            + (
                f", best block score {fly.mushroom.score:.1f} from episode {fly.mushroom.score_episode}"
                if fly.mushroom.score is not None
                else ", no block score"
            )
            + (", still learning)" if options.learn else ")")
        )
    else:
        fly.brain_label = options.brain_label or ""
        loaded = "brain: none (naive fly, no learned bias)"

    if cfg.load_state is not None:
        emulator.load_state(cfg.load_state)
        fly.optic.reset()
        offset = read_tick_offset(cfg.load_state)
        if offset is None:
            print(
                f"no game-time offset recorded for {cfg.load_state} (no {Path(cfg.load_state).name}.json beside it): "
                "game time counts from 0 here",
                flush=True,
            )
            offset = 0
        fly.set_clock(offset)
    return loaded


def run_loop(cfg: Config, observers: Iterable[object] = (), options: LoopOptions | None = None) -> dict:
    """Runs until the window closes, Ctrl+C, or `max_steps`.

    Every observer is called with one `TickState` per tick. The display is the
    first one. Returns a summary dict for the caller and the integration test.
    """
    options = options or LoopOptions()
    rom = require_rom(cfg)

    emulator = Emulator(rom, headless=cfg.headless, uncapped=cfg.uncapped, cfg=cfg)
    fly = Fly(cfg, emulator)
    try:
        loaded = _set_up(cfg, fly, emulator, options)
    except BaseException:
        emulator.close()
        raise
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

    recorder = options.recorder
    journey = options.journey
    if options.on_start is not None:
        options.on_start(fly)
    if recorder is not None:
        recorder.begin(fly, 0)
    if journey is not None:
        journey.start(fly)

    step = 0
    map_order: list[int] = []
    landed: dict[str, int] = {}
    period = 1.0 / options.pace_hz if options.pace_hz > 0 else 0.0
    started = time.perf_counter()
    deadline = started + period
    toggle = options.pause_toggle
    sources = list(options.commands)
    if toggle is None:
        keys = terminal_keys()
        if keys is not None:
            sources.append(keys)
    paused_for = 0.0
    torn = False  # a second Ctrl+C landed inside a tick
    with _StopFlag() as stop:
        try:
            while (cfg.max_steps == 0 or step < cfg.max_steps) and not stop.hit:
                commands = _poll(sources) if sources else []
                if (toggle is not None and toggle()) or "pause" in commands:
                    held = time.perf_counter()
                    _hold(fly, toggle, sources, journey, stop, watchers)
                    paused_for += time.perf_counter() - held
                    deadline = time.perf_counter() + period
                    if stop.hit:
                        break
                if "save" in commands and journey is not None:
                    journey.save(fly, "on request")
                torn = True
                running = emulator.tick()
                # A closed window has still emulated its frame; the fly sees
                # it, so whatever is saved on the way out is one whole tick.
                step += 1
                state = fly.tick(step)
                if not map_order or map_order[-1] != state.map_id:
                    map_order.append(state.map_id)
                for name in state.milestones:
                    landed[name] = state.game_tick
                for watcher in watchers:
                    watcher(state)
                if recorder is not None:
                    recorder(fly, state)
                if journey is not None:
                    journey.after_tick(fly)
                torn = False
                if not running:
                    break
                if period:
                    deadline = _pace(deadline, period)
        except KeyboardInterrupt:
            pass
        finally:
            elapsed = time.perf_counter() - started - paused_for
            if journey is not None:
                if torn:
                    print("not saved: stopped in the middle of a tick; the last save stands", flush=True)
                else:
                    journey.save(fly, "on exit")
            fly.motor.release_all()
            if options.save_brain and options.save_path is not None:
                fly.mushroom.save(options.save_path)
                print(f"brain saved to {options.save_path}", flush=True)
            if cfg.save_state is not None:
                emulator.save_state(cfg.save_state)
                write_tick_offset(cfg.save_state, fly.clock, note="written by run.py --save-state")
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
        "game_tick": fly.clock,
        "milestones": landed,
    }
    if recorder is not None and recorder.snapshot_ms:
        ordered = sorted(recorder.snapshot_ms)
        summary["snapshot_ms_median"] = round(ordered[len(ordered) // 2], 3)
        summary["snapshot_ms_max"] = round(ordered[-1], 3)
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
    landed = summary.get("milestones") or {}
    print(
        f"game time at the end: {game_time(summary.get('game_tick', 0))}; milestones this run: "
        + (", ".join(f"{LABELS.get(name, name)} {game_time(tick)}" for name, tick in landed.items()) or "none"),
        flush=True,
    )
    if "snapshot_ms_median" in summary:
        print(
            f"replay snapshots: median {summary['snapshot_ms_median']} ms, max {summary['snapshot_ms_max']} ms "
            "(the max includes the occasional full savestate anchor)",
            flush=True,
        )


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
