"""Thin PyBoy wrapper. Nothing else in the package imports pyboy.

Verified against pyboy 2.7.0: `PyBoy(rom, window=..., sound_emulated=False)`,
`tick(count, render)` returning False once the window is closed,
`screen.ndarray` as (144, 160, 4) RGBA, `button_press`/`button_release` taking
lowercase names, `memory[addr]`, `set_emulation_speed(0)`, `stop(save=False)`,
and `save_state`/`load_state` taking file-like objects.

Snapshots, and why they are two things. A full PyBoy savestate costs about
20 ms here, measured: `save_state` pushes all 167,677 bytes one at a time
through a Python-level `write`, and a bare Python loop of that many writes is
already 16 ms. The replay buffer wants a snapshot every five seconds of game,
inside a 16 ms tick budget. So the emulator keeps an ANCHOR, one full
savestate taken rarely (a loaded state file is one for free), and logs every
button event after it, keyed by the tick it was issued before. A cheap
`EmulatorPoint` is the anchor plus that log plus the events issued since the
last tick; restoring one loads the anchor and replays the log tick by tick.
The emulator is deterministic given its inputs (a cold-boot run of the naive
fly regenerated `states/bedroom.state` byte for byte), so that is the same
emulator state, reached in about 1/6400 s per tick instead of stored.

Button events are queued by PyBoy and only reach the joypad on the next
`tick`, and that queue (`PyBoy.events`) is not in a savestate. So a point
also carries the events issued since the last tick, and a restore clears the
queue and issues them again.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from pyboy import PyBoy

from .config import Config
from .reward import RamSnapshot

# (button, pressed) in the order they were issued.
Event = tuple[str, bool]


@dataclass(frozen=True)
class EmulatorPoint:
    """An emulator's exact position, cheaply.

    `anchor` is a full savestate. `events[i]` is `(t, evs)`: `evs` were issued
    just before the t-th tick after the anchor. `ticks` is how many ticks past
    the anchor this point is, and `pending` the events issued since the last
    of them, which the next tick will apply.
    """

    anchor: bytes
    events: tuple[tuple[int, tuple[Event, ...]], ...]
    ticks: int
    pending: tuple[Event, ...]


class Emulator:
    def __init__(self, rom_path: str | Path, headless: bool = False, uncapped: bool = False, cfg: Config | None = None):
        self.cfg = cfg or Config()
        self.rom_path = Path(rom_path)
        self.pyboy = PyBoy(
            str(self.rom_path),
            window="null" if headless else "SDL2",
            sound_emulated=False,
        )
        if uncapped:
            self.pyboy.set_emulation_speed(0)
        self._closed = False
        self._anchor: bytes | None = None  # none until one is asked for
        self._events: list[tuple[int, tuple[Event, ...]]] = []
        self._since_anchor = 0
        self._pending: list[Event] = []

    # -- stepping ----------------------------------------------------------

    def tick(self) -> bool:
        """One frame. False means the window was closed and the loop should
        exit; the frame was still emulated."""
        if self._pending:
            if self._anchor is not None:
                self._events.append((self._since_anchor + 1, tuple(self._pending)))
            self._pending = []
        running = bool(self.pyboy.tick(1, True))
        self._since_anchor += 1
        return running

    def frame(self) -> np.ndarray:
        """(144, 160) uint8 grayscale. PyBoy hands back RGBA; the Game Boy
        palette is gray, so the red channel alone is the luminance."""
        return np.ascontiguousarray(self.pyboy.screen.ndarray[:, :, 0])

    # -- input -------------------------------------------------------------

    def press(self, button: str) -> None:
        self.pyboy.button_press(button)
        self._pending.append((button, True))

    def release(self, button: str) -> None:
        self.pyboy.button_release(button)
        self._pending.append((button, False))

    def _issue(self, events) -> None:
        for button, pressed in events:
            (self.pyboy.button_press if pressed else self.pyboy.button_release)(button)

    # -- game state --------------------------------------------------------

    def position(self) -> tuple[int, int, int]:
        memory = self.pyboy.memory
        return (
            int(memory[self.cfg.map_id_addr]),
            int(memory[self.cfg.player_x_addr]),
            int(memory[self.cfg.player_y_addr]),
        )

    @property
    def in_battle(self) -> bool:
        return bool(self.pyboy.memory[self.cfg.in_battle_addr])

    def snapshot(self) -> RamSnapshot:
        """Every RAM value the reward layer is allowed to see, in one read.

        This is the only place PyBoy memory is turned into reward inputs, so
        `reward.py` never imports an emulator and is testable with a plain
        dataclass. Measured at about 10 microseconds a call against a tick
        budget of roughly 500, so it runs every tick rather than being sampled.
        """
        cfg = self.cfg
        memory = self.pyboy.memory
        count = int(memory[cfg.party_count_addr])
        levels = 0
        exp = 0
        species: tuple[int, ...] = ()
        hp: tuple[int, ...] = ()
        if 1 <= count <= 6:  # anything else is uninitialised RAM, not a party
            stride = cfg.party_stride
            species = tuple(int(memory[cfg.party_species_addr + slot]) for slot in range(count))
            hp_list = []
            for slot in range(count):
                base = slot * stride
                levels += int(memory[cfg.party_level_addr + base])
                at = cfg.party_hp_addr + base
                hp_list.append((int(memory[at]) << 8) | int(memory[at + 1]))
                at = cfg.party_exp_addr + base
                exp += (int(memory[at]) << 16) | (int(memory[at + 1]) << 8) | int(memory[at + 2])
            hp = tuple(hp_list)
        flags = bytes(memory[cfg.event_flags_addr : cfg.event_flags_end])
        battle = int(memory[cfg.in_battle_addr])
        return RamSnapshot(
            map_id=int(memory[cfg.map_id_addr]),
            x=int(memory[cfg.player_x_addr]),
            y=int(memory[cfg.player_y_addr]),
            in_battle=bool(battle),
            party_count=count,
            level_sum=levels,
            badge_bits=int(memory[cfg.badges_addr]),
            event_bits=int.from_bytes(flags, "big").bit_count(),
            name_byte=int(memory[cfg.player_name_addr]),
            joy_ignore=int(memory[cfg.joy_ignore_addr]),
            battle=battle,
            party_species=species,
            party_hp=hp,
            exp_sum=exp,
        )

    # -- savestates --------------------------------------------------------

    def load_state(self, path: str | Path) -> None:
        """Load a state file. It becomes the anchor, at no extra cost. Events
        already issued stay queued, exactly as PyBoy leaves them."""
        self.load_bytes(Path(path).read_bytes())

    def load_bytes(self, data: bytes) -> None:
        self.pyboy.load_state(io.BytesIO(data))
        self._anchor = bytes(data)
        self._events = []
        self._since_anchor = 0

    def state_bytes(self) -> bytes:
        """A full savestate, now. About 20 ms: see the module docstring."""
        buffer = io.BytesIO()
        self.pyboy.save_state(buffer)
        return buffer.getvalue()

    def save_state(self, path: str | Path) -> None:
        """A full savestate to a file, written whole or not at all. It becomes
        the anchor too, since it was paid for."""
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        data = self.anchor()
        partial = target.with_name(target.name + ".partial")
        partial.write_bytes(data)
        partial.replace(target)

    # -- cheap snapshots ---------------------------------------------------

    def anchor(self) -> bytes:
        """Take a full savestate and log button events from here on. Returns it."""
        self._anchor = self.state_bytes()
        self._events = []
        self._since_anchor = 0
        return self._anchor

    @property
    def ticks_since_anchor(self) -> int:
        return self._since_anchor

    def point(self) -> EmulatorPoint:
        """Where this emulator is, cheaply (an anchor is taken the first time)."""
        if self._anchor is None:
            self.anchor()
        return EmulatorPoint(
            anchor=self._anchor,
            events=tuple(self._events),
            ticks=self._since_anchor,
            pending=tuple(self._pending),
        )

    def restore(self, point: EmulatorPoint) -> None:
        """Put this emulator exactly where `point` was: load its anchor, replay
        the logged button events tick by tick, and queue the events that were
        waiting for the next tick. Rendering stays on during the fast-forward
        because the screen buffer is part of the state."""
        self.pyboy.events.clear()  # anything queued belongs to the old timeline
        self._pending = []
        self.pyboy.load_state(io.BytesIO(point.anchor))
        logged = iter(point.events)
        upcoming = next(logged, None)
        for tick in range(1, point.ticks + 1):
            while upcoming is not None and upcoming[0] == tick:
                self._issue(upcoming[1])
                upcoming = next(logged, None)
            self.pyboy.tick(1, True)
        self._anchor = point.anchor
        self._events = [event for event in point.events if event[0] <= point.ticks]
        self._since_anchor = point.ticks
        for button, pressed in point.pending:
            (self.press if pressed else self.release)(button)

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self.pyboy.stop(save=False)
