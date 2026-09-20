"""Motor pools -> button presses, plus the anti-stuck panic reflex.

Each pool has a leaky accumulator of its spike count. When the accumulator
crosses `fire_threshold` the button is pressed for exactly `hold_frames`
ticks, released, and then that button sits in a short cooldown so the game
registers distinct presses. The accumulator resets on fire.

At most one direction is held at a time (the strongest accumulator wins) and
at most one of A/B/START, but an action may overlap a direction.

The reflex: if neither the player's (map_id, x, y) nor the last button fired
has changed for `panic_after` ticks, the fly startles. A burst of 6 to 10
random buttons is queued and played out one at a time, and a transient current
pulse is offered to the loop to inject into the brain so the startle shows on
the HUD.

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
        self.held: dict[str, int] = {}  # pool name -> ticks of hold remaining
        self.cooldown: dict[str, int] = dict.fromkeys(POOL_NAMES, 0)
        self.fire_counts: dict[str, int] = dict.fromkeys(POOL_NAMES, 0)
        self.queue: list[str] = []  # pending panic burst
        self.panic_count = 0
        self.pulse = 0.0  # transient current for the loop, cleared when read
        self.stuck_ticks = 0
        self._last_position: tuple[int, int, int] | None = None
        self._stuck_action: str | None = None
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

    def _track_stuck(self, position: tuple[int, int, int] | None, fired: str | None) -> None:
        changed = False
        if position is not None:
            if self._last_position is not None and position != self._last_position:
                changed = True
            self._last_position = position
        if fired is not None and fired != self._stuck_action:
            self._stuck_action = fired
            changed = True
        self.stuck_ticks = 0 if changed else self.stuck_ticks + 1

    def _panic(self) -> str:
        count = int(self.rng.integers(self.cfg.panic_min_buttons, self.cfg.panic_max_buttons + 1))
        self.queue = [str(name) for name in self.rng.choice(POOL_NAMES, size=count, p=self._draw_weights)]
        self.panic_count += 1
        self.pulse = self.cfg.panic_pulse
        self.stuck_ticks = 0
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
        self._tick_timers()

        if self.queue:  # playing out a burst; the brain does not get a vote
            if self.held or self.cooldown[self.queue[0]] > 0:
                return None
            pool = self.queue.pop(0)
            self._start(pool)
            return pool

        counts = spikes[self.pools].sum(axis=1).astype(np.float32)
        self.accum = self.accum * self.cfg.accum_decay + counts

        fired: str | None = None
        for index in np.argsort(-self.accum):  # strongest pool gets first refusal
            pool = POOL_NAMES[int(index)]
            if self.accum[index] < self.cfg.fire_threshold or not self._available(pool):
                continue
            self.accum[index] = 0.0
            self._start(pool)
            if fired is None or (pool in DIRECTIONS and fired not in DIRECTIONS):
                fired = pool

        self._track_stuck(position, fired)
        if self.stuck_ticks >= self.cfg.panic_after:
            return self._panic()
        return fired
