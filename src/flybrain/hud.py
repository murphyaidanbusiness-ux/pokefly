"""In-place terminal display. Stdlib only.

An observer: `run_loop` hands it one `TickState` per tick and it redraws over
itself with ANSI escapes every `hud_every` ticks. On Windows the console needs
virtual-terminal processing switched on first, and an empty `os.system("")` is
enough to do that.

`--no-hud` selects `PlainLog` instead: one line per second, which is what you
want when the output is piped to a file.
"""

from __future__ import annotations

import os
import sys
import time
from collections import deque

from .config import POOL_NAMES, Config
from .milestones import game_time, milestone_line
from .reward import PARTS

_HOME = "\x1b[H"
_CLEAR_BELOW = "\x1b[J"
_HIDE_CURSOR = "\x1b[?25l"
_SHOW_CURSOR = "\x1b[?25h"


def _bar(value: float, width: int, full: str = "#", empty: str = ".") -> str:
    filled = max(0, min(width, int(round(value * width))))
    return full * filled + empty * (width - filled)


def _signed_bar(value: float, scale: float, width: int) -> str:
    """A bar centred on zero: left of the middle is negative, right positive."""
    half = width // 2
    units = max(-half, min(half, int(round(value / scale * half))))
    if units < 0:
        return "." * (half + units) + "<" * (-units) + "|" + "." * half
    return "." * half + "|" + ">" * units + "." * (half - units)


class Hud:
    def __init__(self, cfg: Config, title: str = "") -> None:
        self.cfg = cfg
        self.title = title
        self.presses = dict.fromkeys(POOL_NAMES, 0)
        self.history: deque[str] = deque(maxlen=cfg.hud_history)
        self.start = time.perf_counter()
        self._last_step = 0
        self._last_time = self.start
        self._rate = 0.0
        self.milestone_lines: deque[str] = deque(maxlen=3)
        self.status = None  # run.py: a callable returning the journey status
        self._closed = False
        os.system("")  # enables VT processing on a Windows console
        sys.stdout.write(_HIDE_CURSOR + "\x1b[2J")
        sys.stdout.flush()

    def __call__(self, tick) -> None:
        if tick.action:
            self.history.append(tick.action)
        for pool in tick.started:
            self.presses[pool] += 1
        for name in tick.milestones:
            self.milestone_lines.append(milestone_line(name, tick.game_tick, tick.brain, tick.brain_episodes))
        if tick.step % self.cfg.hud_every:
            return
        now = time.perf_counter()
        if now > self._last_time:
            self._rate = (tick.step - self._last_step) / (now - self._last_time)
        self._last_step, self._last_time = tick.step, now

        width = self.cfg.hud_bar_width
        lines = [
            f"fly-brain-pokemon   {self.title}",
            f"  step {tick.step:<9d} ticks/s {self._rate:7.1f}   elapsed {now - self.start:7.1f}s",
            f"  firing {tick.firing_rate * 100:5.2f}%  [{_bar(min(tick.firing_rate / 0.30, 1.0), width)}]",
            f"  dopamine {tick.dopamine:+7.3f} [{_signed_bar(tick.dopamine, 1.0, width)}]"
            f"   value {tick.value:8.3f}",
            f"  reward {tick.episode_reward:8.1f}  "
            + " ".join(f"{name} {tick.reward_parts[name]:g}" for name in PARTS),
            "",
            "  motor pools (excursion above each pool's own baseline, bar = share of its threshold)",
        ]
        for i, name in enumerate(POOL_NAMES):
            level = float(tick.excursion[i])
            marker = "<" if name in tick.pressed else " "
            share = level / float(self.cfg.fire_threshold * self.cfg.threshold_scale[i])
            lines.append(
                f"    {name:<5s} {level:7.2f} [{_bar(share, width)}] {marker}"
                f"  mbon {float(tick.mbon[i]):+7.3f}"
            )
        lines += [
            "",
            f"  action  {('+'.join(tick.pressed) or '-'):<12s} last {' '.join(self.history) or '-'}",
            f"  {tick.map_name} ({tick.map_id})   x {tick.x:<4d} y {tick.y:<4d}   "
            f"battle {'YES' if tick.in_battle else 'no '}   panics {tick.panics}",
            f"  presses {' '.join(f'{n}:{self.presses[n]}' for n in POOL_NAMES)}",
            f"  game time {game_time(tick.game_tick)}   since the last milestone {game_time(tick.since_milestone)}"
            + _saved(self.status),
            "",
            *(f"  {line}" for line in self.milestone_lines),
        ]
        sys.stdout.write(_HOME + "\n".join(line.ljust(86) for line in lines) + "\n" + _CLEAR_BELOW)
        sys.stdout.flush()

    def close(self) -> None:
        """Give the cursor back. Safe to call twice: the loop closes its
        observers on the way out, and `run.py` closes the display again in
        case the run never reached the loop."""
        if self._closed:
            return
        self._closed = True
        sys.stdout.write(_SHOW_CURSOR + "\n")
        sys.stdout.flush()


def _saved(status) -> str:
    if status is None:
        return ""
    try:
        ago = status().get("saved_ago")
    except Exception:
        return ""
    return "   journey not saved yet" if ago is None else f"   saved {game_time(int(ago * 60))} ago"


class PlainLog:
    """One line per second. Same information, no escapes."""

    def __init__(self, cfg: Config, title: str = "") -> None:
        self.cfg = cfg
        self.title = title
        self.start = time.perf_counter()
        self._last_step = 0
        self._last_time = self.start

    def __call__(self, tick) -> None:
        for name in tick.milestones:
            print(milestone_line(name, tick.game_tick, tick.brain, tick.brain_episodes), flush=True)
        now = time.perf_counter()
        if now - self._last_time < 1.0:
            return
        rate = (tick.step - self._last_step) / (now - self._last_time)
        self._last_step, self._last_time = tick.step, now
        print(
            f"step {tick.step:6d}  {rate:6.1f} tick/s  firing {tick.firing_rate * 100:5.2f}%  "
            f"{tick.map_name} ({tick.map_id}) x {tick.x:3d} y {tick.y:3d}  "
            f"battle {int(tick.in_battle)}  panics {tick.panics}  reward {tick.episode_reward:7.1f}  "
            f"value {tick.value:7.2f}  dopamine {tick.dopamine:+6.3f}",
            flush=True,
        )

    def close(self) -> None:
        pass
