"""Motor pools -> button presses, plus the anti-stuck panic reflex.

Each pool keeps two running averages of its own spike count:

- a fast leaky accumulator (`accum`, tau of a few ticks), and
- a slow baseline (`baseline`, tau of a few hundred ticks) holding the level
  that the pool's recent average drive would sustain the accumulator at.

A button fires on the *excursion*, `accum - adaptation * baseline`, crossing
`fire_threshold * threshold_scale[pool]`. A press therefore means "this pool is
more active than it usually is", which is what visual motion and network
fluctuations produce, rather than "this pool is active", which every pool is,
all the time. Without this the cooldown timer plays the game: every pool sits
far above any absolute threshold and each button fires once per hold plus
cooldown, forever.

The baseline is computed from the spike counts, not from the accumulator, so
resetting the accumulator on a fire cannot drag its own baseline down after it
and stall the pool.

The press itself is unchanged: held for exactly `hold_frames` ticks, released,
then a per-button cooldown so the game registers distinct presses. At most one
direction is held at a time (the largest margin over its own threshold wins)
and at most one of A/B/START, but an action may overlap a direction.

The reflex: the fly startles if its `(map_id, x, y)` has not changed for
`panic_after` ticks, or if no button at all has been pressed for that long. A
burst of 6 to 10 random buttons is queued and played out one at a time, and a
transient current pulse is offered to the loop to inject into the brain so the
startle shows on the HUD. Both counters restart from zero afterwards.

The emulator is reached through a two-method protocol (`press`, `release`), so
tests drive this with a fake that just records calls.
"""

from __future__ import annotations

from typing import Protocol

import numpy as np

from .config import ACTIONS, BUTTON_FOR_POOL, DIRECTIONS, POOL_NAMES, Config


class ButtonSink(Protocol):
    def press(self, button: str) -> None: ...
    def release(self, button: str) -> None: ...


class MotorBridge:
    def __init__(self, connectome, cfg: Config, sink: ButtonSink) -> None:
        self.cfg = cfg
        self.sink = sink
        self.pools = connectome.pool_matrix()
        self.rng = np.random.default_rng(cfg.seed + 3)
        self.accum = np.zeros(len(POOL_NAMES), dtype=np.float32)
        self.baseline = np.zeros(len(POOL_NAMES), dtype=np.float32)
        self.excursion = np.zeros(len(POOL_NAMES), dtype=np.float32)
        self.thresholds = cfg.fire_threshold * np.array(cfg.threshold_scale, dtype=np.float32)
        self.held: dict[str, int] = {}  # pool name -> ticks of hold remaining
        self.cooldown: dict[str, int] = dict.fromkeys(POOL_NAMES, 0)
        self.fire_counts: dict[str, int] = dict.fromkeys(POOL_NAMES, 0)
        self.queue: list[str] = []  # pending panic burst
        self.panic_count = 0
        self.pulse = 0.0  # transient current for the loop, cleared when read
        self.position_stuck = 0  # ticks since (map_id, x, y) last changed
        self.idle_ticks = 0  # ticks since any button was last pressed
        self._last_position: tuple[int, int, int] | None = None
        self._pressed_this_tick = False
        weights = np.array(
            [
                cfg.panic_direction_weight
                if name in DIRECTIONS
                else (cfg.panic_a_weight if name == "A" else cfg.panic_other_weight)
                for name in POOL_NAMES
            ],
            dtype=np.float64,
        )
        self._draw_weights = weights / weights.sum()

    # -- button plumbing ---------------------------------------------------

    def _start(self, pool: str) -> None:
        self.sink.press(BUTTON_FOR_POOL[pool])
        self.held[pool] = self.cfg.hold_frames
        self.fire_counts[pool] += 1
        self._pressed_this_tick = True

    def _release(self, pool: str) -> None:
        self.sink.release(BUTTON_FOR_POOL[pool])
        del self.held[pool]
        self.cooldown[pool] = self.cfg.cooldown_ticks

    def _tick_timers(self) -> None:
        # Cooldowns are aged first, so a cooldown started by a release later in
        # this same tick gets its full `cooldown_ticks` of silence.
        for pool in POOL_NAMES:
            if self.cooldown[pool] > 0:
                self.cooldown[pool] -= 1
        for pool in list(self.held):
            self.held[pool] -= 1
            if self.held[pool] <= 0:
                self._release(pool)

    def _available(self, pool: str) -> bool:
        if pool in self.held or self.cooldown[pool] > 0:
            return False
        group = DIRECTIONS if pool in DIRECTIONS else ACTIONS
        return not any(other in group for other in self.held)

    def release_all(self) -> None:
        for pool in list(self.held):
            self._release(pool)

    # -- panic -------------------------------------------------------------

    def _track_stuck(self, position: tuple[int, int, int] | None) -> None:
        if position is not None:
            moved = self._last_position is not None and position != self._last_position
            self.position_stuck = 0 if moved else self.position_stuck + 1
            self._last_position = position
        # With no position reading at all (a bench harness rather than the
        # game) there is no evidence of being stuck, so that counter does not
        # run and only the idle counter can trigger the reflex.
        self.idle_ticks = 0 if self._pressed_this_tick else self.idle_ticks + 1

    def _stuck(self) -> bool:
        return self.position_stuck >= self.cfg.panic_after or self.idle_ticks >= self.cfg.panic_after

    def _panic(self) -> str:
        count = int(self.rng.integers(self.cfg.panic_min_buttons, self.cfg.panic_max_buttons + 1))
        self.queue = [str(name) for name in self.rng.choice(POOL_NAMES, size=count, p=self._draw_weights)]
        self.panic_count += 1
        self.pulse = self.cfg.panic_pulse
        self.position_stuck = 0
        self.idle_ticks = 0
        self.release_all()
        pool = self.queue.pop(0)
        self.cooldown[pool] = 0
        self._start(pool)
        return "PANIC"

    def take_pulse(self) -> float:
        """The transient current to inject this tick. Reading it clears it."""
        pulse, self.pulse = self.pulse, 0.0
        return pulse

    # -- main --------------------------------------------------------------

    def update(self, spikes: np.ndarray, position: tuple[int, int, int] | None) -> str | None:
        """Advance one tick. Returns the action that started this tick, the
        string "PANIC" on a startle, or None."""
        self._pressed_this_tick = False
        self._tick_timers()

        if self.queue:  # playing out a burst; the brain does not get a vote
            return self._play_burst(position)

        counts = spikes[self.pools].sum(axis=1).astype(np.float32)
        # `counts / (1 - decay)` is the accumulator level this drive sustains,
        # which is what the slow baseline follows.
        self.baseline += self.cfg.baseline_rate * (counts / (1.0 - self.cfg.accum_decay) - self.baseline)
        self.accum = self.accum * self.cfg.accum_decay + counts
        self.excursion = self.accum - self.cfg.adaptation * self.baseline

        fired = self._fire_pools()
        self._track_stuck(position)
        if self._stuck():
            return self._panic()
        return fired

    def _play_burst(self, position: tuple[int, int, int] | None) -> str | None:
        self.position_stuck = 0
        self.idle_ticks = 0
        if position is not None:
            self._last_position = position
        if self.held or self.cooldown[self.queue[0]] > 0:
            return None
        pool = self.queue.pop(0)
        self._start(pool)
        return pool

    def _fire_pools(self) -> str | None:
        fired: str | None = None
        for index in np.argsort(-(self.excursion - self.thresholds)):  # largest margin first
            pool = POOL_NAMES[int(index)]
            if self.excursion[index] < self.thresholds[index] or not self._available(pool):
                continue
            self.accum[index] = 0.0
            self.excursion[index] = -self.cfg.adaptation * self.baseline[index]
            self._start(pool)
            if fired is None or (pool in DIRECTIONS and fired not in DIRECTIONS):
                fired = pool
        return fired
