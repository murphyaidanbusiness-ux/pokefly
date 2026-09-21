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
