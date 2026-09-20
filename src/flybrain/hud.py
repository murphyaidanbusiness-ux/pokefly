"""In-place terminal display. Stdlib only.

Redraws over itself with ANSI escapes every `hud_every` ticks. On Windows the
console needs virtual-terminal processing switched on first, and an empty
`os.system("")` is enough to do that.

`--no-hud` selects `PlainLog` instead: one line per second, which is what you
want when the output is piped to a file.
"""

from __future__ import annotations

import os
import sys
import time
from collections import deque

from .config import POOL_NAMES, Config

_HOME = "\x1b[H"
_CLEAR_BELOW = "\x1b[J"
_HIDE_CURSOR = "\x1b[?25l"
_SHOW_CURSOR = "\x1b[?25h"


def _bar(value: float, width: int, full: str = "#", empty: str = ".") -> str:
    filled = max(0, min(width, int(round(value * width))))
    return full * filled + empty * (width - filled)


class Hud:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.history: deque[str] = deque(maxlen=cfg.hud_history)
        self.start = time.perf_counter()
        self._last_step = 0
        self._last_time = self.start
        self._rate = 0.0
        os.system("")  # enables VT processing on a Windows console
        sys.stdout.write(_HIDE_CURSOR + "\x1b[2J")
        sys.stdout.flush()

    def note(self, action: str | None) -> None:
        if action:
            self.history.append(action)

    def update(self, step: int, brain, motor, position, in_battle: bool) -> None:
        if step % self.cfg.hud_every:
            return
        now = time.perf_counter()
        if now > self._last_time:
            self._rate = (step - self._last_step) / (now - self._last_time)
        self._last_step, self._last_time = step, now

        width = self.cfg.hud_bar_width
        rate = brain.firing_rate
        map_id, x, y = position
        peak = max(1.0, float(motor.accum.max()), self.cfg.fire_threshold)

        lines = [
            "fly-brain-pokemon",
            f"  step {step:<9d} ticks/s {self._rate:7.1f}   elapsed {now - self.start:7.1f}s",
            f"  firing {rate * 100:5.2f}%  [{_bar(min(rate / 0.30, 1.0), width)}]",
            "",
            "  motor pools",
        ]
        for i, name in enumerate(POOL_NAMES):
            level = float(motor.accum[i])
            marker = "<" if name in motor.held else " "
            lines.append(f"    {name:<5s} {level:6.2f} [{_bar(level / peak, width)}] {marker}")
        lines += [
            "",
            f"  action  {(motor_action(motor) or '-'):<8s}   last {' '.join(self.history) or '-'}",
            f"  map {map_id:<4d} x {x:<4d} y {y:<4d}   battle {'YES' if in_battle else 'no '}"
            f"   panics {motor.panic_count}",
            f"  presses {' '.join(f'{n}:{motor.fire_counts[n]}' for n in POOL_NAMES)}",
            "",
        ]
        sys.stdout.write(_HOME + "\n".join(line.ljust(78) for line in lines) + "\n" + _CLEAR_BELOW)
        sys.stdout.flush()

    def close(self) -> None:
        sys.stdout.write(_SHOW_CURSOR + "\n")
        sys.stdout.flush()


def motor_action(motor) -> str | None:
    """Whatever button is being held right now, for the HUD's current-action line."""
    if not motor.held:
        return None
    return "+".join(sorted(motor.held))


class PlainLog:
    """One line per second. Same information, no escapes."""

    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.history: deque[str] = deque(maxlen=cfg.hud_history)
        self.start = time.perf_counter()
        self._last_step = 0
        self._last_time = self.start

    def note(self, action: str | None) -> None:
        if action:
            self.history.append(action)

    def update(self, step: int, brain, motor, position, in_battle: bool) -> None:
        now = time.perf_counter()
        if now - self._last_time < 1.0:
            return
        rate = (step - self._last_step) / (now - self._last_time)
        self._last_step, self._last_time = step, now
        map_id, x, y = position
        presses = " ".join(f"{n}:{motor.fire_counts[n]}" for n in POOL_NAMES)
        print(
            f"step {step:6d}  {rate:6.1f} tick/s  firing {brain.firing_rate * 100:5.2f}%  "
            f"map {map_id:3d} x {x:3d} y {y:3d}  battle {int(in_battle)}  "
            f"panics {motor.panic_count}  presses {presses}",
            flush=True,
        )

    def close(self) -> None:
        pass
