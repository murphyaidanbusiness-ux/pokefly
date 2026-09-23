"""The observer that feeds the couch scene.

`run_loop` calls this once per tick, in the game loop's own thread, so it does
two things and nothing else: turn the tick into bytes, and drop those bytes
into the `Hub`'s latest-state slot. It never touches a socket and never waits
on one. Measured cost is in the README.

Two rates, both wall clock rather than tick counts so an uncapped run does not
flood the browser: a binary video message at `couch_video_fps`, and a JSON
state message at `couch_state_hz`.

Presses are sent as EVENTS, not just as the set of buttons held. A press is
four ticks long and a state message goes out every twenty or so milliseconds,
so a press that starts and ends between two messages is invisible in the held
set. The scene needs it: that press is the whole point of the animation.
A milestone is latched the same way: it goes out on the next state message
whenever it landed, and on exactly one.
"""

from __future__ import annotations

import base64
import json
import math
import time
from collections import deque
from collections.abc import Callable

import numpy as np

from .config import POOL_NAMES, Config
from .couch import OP_BINARY, OP_TEXT, PROTOCOL_VERSION, VIDEO_MESSAGE, Hub, encode_frame
from .milestones import LABELS, game_time
from .reward import PARTS

FRAME_WIDTH, FRAME_HEIGHT = 160, 144


class SpikeSampler:
    """A fixed, seeded window on the network, for the scrolling raster.

    256 neurons: the first `per_pool` of each motor pool, labelled with their
    pool so the scene can colour those rows, and the rest drawn from the
    sensory and hidden population so the raster shows the network the pools sit
    in rather than only the pools. The draw is seeded, so two runs of the same
    seed watch the same neurons.

    `pack` returns the bits, eight to a byte, in that order.
    """

    def __init__(self, connectome, cfg: Config, size: int | None = None, per_pool: int | None = None,
                 seed: int | None = None) -> None:
        size = cfg.couch_spike_sample if size is None else size
        per_pool = cfg.couch_spike_per_pool if per_pool is None else per_pool
        seed = cfg.seed if seed is None else seed

        picked: list[np.ndarray] = []
        labels: list[str] = []
        for name in POOL_NAMES:
            members = np.asarray(connectome.motor_pools[name], dtype=np.int64)[:per_pool]
            picked.append(members)
            labels += [name] * int(members.size)

        motor = set(int(i) for i in connectome.motor_idx)
        others = np.array([i for i in range(connectome.n) if i not in motor], dtype=np.int64)
        wanted = max(0, size - sum(int(p.size) for p in picked))
        rng = np.random.default_rng(seed + 11)
        chosen = np.sort(rng.choice(others, size=min(wanted, others.size), replace=False))
        picked.append(chosen)
        labels += [""] * int(chosen.size)

        self.indices = np.concatenate(picked).astype(np.int64)
        self.labels = labels
        self.size = int(self.indices.size)

    def pack(self, spikes: np.ndarray) -> bytes:
        return np.packbits(np.asarray(spikes, dtype=bool)[self.indices]).tobytes()


class Ticker:
    """A wall-clock gate that keeps its average rate instead of drifting.

    The obvious version, `now - last >= interval` and then `last = now`,
    aliases against the tick clock: at 60 ticks a second a 22 ms interval can
    only ever fire on every other tick, which is 30 messages a second and not
    the 45 that was asked for. Measured over a 1,800 tick run before this was
    written: 30.0 state and 23.7 video messages a second against 45 and 30.

    Advancing the deadline by exactly one interval keeps the average right. A
    gate that has fallen more than three intervals behind (a long stall) starts
    again from now rather than firing a burst to catch up.
    """

    def __init__(self, hz: float) -> None:
        self.interval = 1.0 / max(1e-6, hz)
        self.due: float | None = None
        self.count = 0

    def reset(self) -> None:
        """The next call fires whatever the clock says."""
        self.due = None

    def ready(self, now: float) -> bool:
        if self.due is None or now > self.due + 3 * self.interval:
            self.due = now + self.interval
        elif now < self.due:
            return False
        else:
            self.due += self.interval
        self.count += 1
        return True


def _number(value: float) -> float:
    """JSON has no NaN. A value the network has not produced yet is zero."""
    number = float(value)
    return number if math.isfinite(number) else 0.0


def _floats(values, places: int = 4) -> list[float]:
    return [round(_number(v), places) for v in values]


class CouchObserver:
    """One `TickState` in, framed WebSocket messages into the hub."""

    def __init__(self, cfg: Config, hub: Hub, title: str = "") -> None:
        self.cfg = cfg
        self.hub = hub
        self.title = title
        self.state_ticker = Ticker(cfg.couch_state_hz)
        self.video_ticker = Ticker(cfg.couch_video_fps)
        self.thresholds = cfg.fire_threshold * np.array(cfg.threshold_scale, dtype=np.float32)
        self.events: list[dict] = []
        self.history: deque[str] = deque(maxlen=cfg.hud_history)
        self.sampler: SpikeSampler | None = None
        self.fly = None
        # Set by run.py. `extras` returns fields to merge into every state
        # and status message (the journey's "saved ... ago"); `replay_target`
        # is (milestone name, game tick it lands at) during a replay, for the
        # countdown.
        self.extras: Callable[[], dict] | None = None
        self.replay_target: tuple[str, int] | None = None
        self.landed: list[dict] = []  # milestones not yet sent
        self.last: dict | None = None  # the most recent milestone this run

        self._start = time.perf_counter()
        self._rate_step = 0
        self._rate_at = self._start
        self._rate = 0.0
        self._hello()

    # -- wiring ------------------------------------------------------------

    def attach(self, fly) -> None:
        """`run_loop` offers the fly to any observer that asks for it.

        `TickState` carries no spikes, and adding them to it would put a 2000
        element array on every tick for every observer. The raster is the only
        thing that wants them, so it reaches in here instead, which is also
        what makes the sample "only computed when a couch observer is
        attached".
        """
        self.fly = fly
        self.sampler = SpikeSampler(fly.connectome, self.cfg)
        self._hello()

    def close(self) -> None:
        """The server outlives the loop by a moment; `run.py` stops it."""

    def on_pause(self, paused: bool) -> None:
        """`run_loop` calls this when it pauses and resumes, and again after a
        save made while paused. No tick runs while paused, so this is the only
        way the page hears about it."""
        payload = {"type": "status", "paused": bool(paused), **self._extras()}
        self.hub.publish("status", encode_frame(json.dumps(payload).encode("utf-8"), OP_TEXT))

    def _extras(self) -> dict:
        if self.extras is None:
            return {}
        try:
            return dict(self.extras())
        except Exception:  # a broken status source must not stop the feed
            return {}

    @property
    def states_sent(self) -> int:
        return self.state_ticker.count

    @property
    def videos_sent(self) -> int:
        return self.video_ticker.count

    # -- messages ----------------------------------------------------------

    def _hello(self) -> None:
        """Everything the scene needs once: what the rows and bars mean."""
        payload = {
            "type": "hello",
            "protocol": PROTOCOL_VERSION,
            "pools": list(POOL_NAMES),
            "thresholds": _floats(self.thresholds, 3),
            "reward_parts": list(PARTS),
            "brain": self.title,
            "spike_labels": self.sampler.labels if self.sampler else [],
            "spike_bits": self.sampler.size if self.sampler else 0,
            "video": {
                "message": VIDEO_MESSAGE,
                "width": FRAME_WIDTH,
                "height": FRAME_HEIGHT,
                "bytes": FRAME_WIDTH * FRAME_HEIGHT,
            },
            "state_hz": self.cfg.couch_state_hz,
            "video_fps": self.cfg.couch_video_fps,
            "game_hz": self.cfg.game_hz,
            "milestone_labels": dict(LABELS),
        }
        self.hub.publish("hello", encode_frame(json.dumps(payload).encode("utf-8"), OP_TEXT))

    def __call__(self, tick) -> None:
        if tick.action:
            self.history.append(tick.action)
        self._record_presses(tick)
        for name in tick.milestones:
            landed = {
                "name": name,
                "label": LABELS.get(name, name),
                "game_tick": int(tick.game_tick),
                "game_time": game_time(tick.game_tick, self.cfg.game_hz),
            }
            self.last = landed
            if len(self.landed) < 16:
                self.landed.append(landed)

        now = time.perf_counter()
        if self.video_ticker.ready(now):
            frame = bytes((VIDEO_MESSAGE,)) + tick.frame.tobytes()
            self.hub.publish("video", encode_frame(frame, OP_BINARY))
        if self.state_ticker.ready(now):
            self._measure_rate(tick.step, now)
            self.hub.publish("state", encode_frame(json.dumps(self._state(tick, now)).encode("utf-8"), OP_TEXT))
            self.events.clear()
            self.landed.clear()

    def _record_presses(self, tick) -> None:
        motor = getattr(self.fly, "motor", None)
        panicked = set(motor.panicked) if motor is not None else (set(tick.started) if tick.panic else set())
        for pool in tick.started:
            if len(self.events) >= self.cfg.couch_event_limit:
                return
            self.events.append({"step": int(tick.step), "pool": pool, "panic": pool in panicked})

    def _measure_rate(self, step: int, now: float) -> None:
        window = now - self._rate_at
        if window < 0.5:
            return
        self._rate = (step - self._rate_step) / window
        self._rate_step, self._rate_at = step, now

    def _state(self, tick, now: float) -> dict:
        excursion = np.asarray(tick.excursion, dtype=np.float64)
        spikes = None
        if self.sampler is not None and self.fly is not None:
            spikes = base64.b64encode(self.sampler.pack(self.fly.brain.spikes)).decode("ascii")
        return {
            "type": "state",
            "t": round(now - self._start, 3),
            "step": int(tick.step),
            "tps": round(self._rate, 1),
            "pressed": list(tick.pressed),
            "events": list(self.events),
            "action": tick.action,
            "history": list(self.history),
            "excursion": _floats(excursion, 2),
            "share": _floats(excursion / self.thresholds, 3),
            "firing_rate": round(_number(tick.firing_rate), 5),
            "dopamine": round(_number(tick.dopamine), 4),
            "value": round(_number(tick.value), 3),
            "mbon": _floats(tick.mbon),
            "reward": round(_number(tick.reward), 3),
            "episode_reward": round(_number(tick.episode_reward), 2),
            "parts": {name: round(_number(value), 2) for name, value in tick.reward_parts.items()},
            "map_id": int(tick.map_id),
            "map_name": str(tick.map_name),
            "x": int(tick.x),
            "y": int(tick.y),
            "in_battle": bool(tick.in_battle),
            "panic": bool(tick.panic),
            "panics": int(tick.panics),
            "spikes": spikes,
            **self._journey(tick),
        }

    def _journey(self, tick) -> dict:
        """The milestone half of a state message."""
        hz = self.cfg.game_hz
        last = self.last
        if last is None and tick.last_milestone:
            # Restored from a save or a replay: the fly knows its last
            # milestone even though none has landed in this run yet.
            since = int(tick.since_milestone)
            last = {
                "name": tick.last_milestone,
                "label": LABELS.get(tick.last_milestone, tick.last_milestone),
                "game_tick": int(tick.game_tick) - since,
                "game_time": game_time(int(tick.game_tick) - since, hz),
            }
        countdown = None
        if self.replay_target is not None:
            name, at = self.replay_target
            left = int(at) - int(tick.game_tick)
            if left >= 0:
                countdown = {
                    "name": name,
                    "label": LABELS.get(name, name),
                    "ticks": left,
                    "text": f"{LABELS.get(name, name)} in {game_time(left, hz)}",
                }
        return {
            "game_tick": int(tick.game_tick),
            "game_time": game_time(tick.game_tick, hz),
            "milestones": list(self.landed),
            "last_milestone": last,
            "since_milestone": int(tick.since_milestone),
            "since_time": game_time(tick.since_milestone, hz),
            "generation": int(tick.brain_episodes),
            "brain_file": str(tick.brain),
            "countdown": countdown,
            "paused": False,
            **self._extras(),
        }
