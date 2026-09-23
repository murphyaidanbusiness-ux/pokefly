"""Reward from RAM. Nothing here touches PyBoy: it takes a `RamSnapshot`.

Every address is in `config.py` with its pokered symbol name, checked against
the pret/pokered symbol file rather than remembered. A wrong address is a
reward for noise, which is worse than a missing reward part.

What is paid for, and only this:

- a tile the fly has not stood on this episode,
- a map it has not entered this episode (so the stairs cannot be farmed: the
  second trip pays nothing, and neither do the tiles it already saw),
- each event flag the game newly sets (meeting Oak, the starter, the parcel),
- each party level gained,
- each badge.

Nothing the policy can trigger without progressing pays anything: opening a
menu, advancing text and turning on the spot are all free.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .config import Config

PARTS: tuple[str, ...] = ("tile", "map", "event", "level", "badge")

# Pokemon's text terminator and the two values uninitialised RAM reads as. A
# player name whose first character is one of these is not a name.
_NOT_A_NAME = frozenset({0x00, 0x50, 0xFF})


@dataclass(frozen=True)
class RamSnapshot:
    """The whole of what the reward layer is allowed to know about the game."""

    map_id: int
    x: int
    y: int
    in_battle: bool
    party_count: int
    level_sum: int
    badge_bits: int
    event_bits: int  # popcount of the whole wEventFlags array
    name_byte: int  # wPlayerName[0]
    joy_ignore: int  # wJoyIgnore
    # For the milestones only; the reward never reads these. Defaults so a
    # test that only cares about the reward can leave them out.
    battle: int = 0  # wIsInBattle raw: 0 none, 1 wild, 2 trainer, $FF lost
    party_species: tuple[int, ...] = ()  # wPartySpecies, one per member
    party_hp: tuple[int, ...] = ()  # wPartyMon{n}HP, one per member
    exp_sum: int = 0  # wPartyMon{n}Exp summed over the party

    @property
    def named(self) -> bool:
        """The intro has written a player name, so these bytes are a game in
        progress and not uninitialised RAM."""
        return self.name_byte not in _NOT_A_NAME


def has_control(snapshot: RamSnapshot) -> bool:
    """Is the player actually driving the character right now?

    Two conditions, both concrete and both tested:

    - the player has a name. `wPlayerName` is the last thing the intro writes
      before handing over in the bedroom, and before that the array reads as
      uninitialised RAM. This is what keeps the boot-time `wCurMap` of 0 from
      being scored as a visit to Pallet Town.
    - `wJoyIgnore` is zero. Nonzero means the engine is swallowing input, which
      is every cutscene and every map transition. Rewarding those would pay the
      fly for things it did not do.
    """
    return snapshot.name_byte not in _NOT_A_NAME and snapshot.joy_ignore == 0


class RewardTracker:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.reset()

    def reset(self) -> None:
        """Per episode. Visited sets go; the reward is an exploration bonus and
        has to be earned again from the start state every time."""
        self.tiles: set[tuple[int, int, int]] = set()
        self.maps: set[int] = set()
        self.map_order: list[int] = []
        self.total = 0.0
        self.parts: dict[str, float] = dict.fromkeys(PARTS, 0.0)
        self._levels = 0
        self._events = 0
        self._badges = 0
        self._started = False

    def get_state(self) -> dict:
        tiles = np.array(sorted(self.tiles), dtype=np.int32).reshape(-1, 3)
        return {
            "tiles": tiles,
            "maps": sorted(self.maps),
            "map_order": list(self.map_order),
            "total": self.total,
            "parts": dict(self.parts),
            "levels": self._levels,
            "events": self._events,
            "badges": self._badges,
            "started": self._started,
        }

    def set_state(self, state: dict) -> None:
        self.tiles = {tuple(int(v) for v in row) for row in np.asarray(state["tiles"]).reshape(-1, 3)}
        self.maps = {int(m) for m in state["maps"]}
        self.map_order = [int(m) for m in state["map_order"]]
        self.total = float(state["total"])
        self.parts = {str(k): float(v) for k, v in state["parts"].items()}
        self._levels = int(state["levels"])
        self._events = int(state["events"])
        self._badges = int(state["badges"])
        self._started = bool(state["started"])

    @property
    def started(self) -> bool:
        """True once the fly has had control for at least one tick."""
        return self._started

    def step(self, snapshot: RamSnapshot) -> tuple[float, dict[str, float]]:
        cfg = self.cfg
        parts = dict.fromkeys(PARTS, 0.0)
        if not has_control(snapshot):
            return 0.0, parts

        if not self._started:
            # The first controlled tick sets the baselines and books the start
            # square as seen, so standing still at the start pays nothing.
            self._started = True
            self._levels = snapshot.level_sum
            self._events = snapshot.event_bits
            self._badges = int(snapshot.badge_bits).bit_count()
            self.maps.add(snapshot.map_id)
            self.map_order.append(snapshot.map_id)
            self.tiles.add((snapshot.map_id, snapshot.x, snapshot.y))
            return 0.0, parts

        tile = (snapshot.map_id, snapshot.x, snapshot.y)
        if tile not in self.tiles:
            self.tiles.add(tile)
            parts["tile"] = cfg.reward_tile
        if snapshot.map_id not in self.maps:
            self.maps.add(snapshot.map_id)
            parts["map"] = cfg.reward_map
        if not self.map_order or self.map_order[-1] != snapshot.map_id:
            self.map_order.append(snapshot.map_id)

        gained = max(0, snapshot.event_bits - self._events)
        self._events = max(self._events, snapshot.event_bits)
        parts["event"] = cfg.reward_event * gained

        levels = max(0, snapshot.level_sum - self._levels)
        self._levels = max(self._levels, snapshot.level_sum)
        parts["level"] = cfg.reward_level * levels

        badges = int(snapshot.badge_bits).bit_count()
        parts["badge"] = cfg.reward_badge * max(0, badges - self._badges)
        self._badges = max(self._badges, badges)

        reward = float(sum(parts.values()))
        self.total += reward
        for name, value in parts.items():
            self.parts[name] += value
        return reward, parts
