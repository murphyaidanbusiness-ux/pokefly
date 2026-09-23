"""Named moments in the fly's journey, for the camera.

`MILESTONES` is a fixed table in story order. Each entry is a pure predicate
over a `Moment`: the RAM snapshot this tick, the one before it, and one fact
the tracker keeps across a battle (whether the battle that just ended was
won). Every RAM value comes through `RamSnapshot`, whose addresses are in
`config.py` with their pokered symbol names.

Three layers, from cheap to durable:

- `MilestoneTracker` is part of the fly's state. Fed one snapshot per tick
  with the game clock, it reports the FIRST tick each predicate is true in
  this run (a training episode is a run). It travels in every fly snapshot,
  so a replay or a continued journey knows what has already happened.
- `JourneyLog` is `milestones/journey.json`: the first time each milestone
  was ever reached, across every run and brain, with game time, date, brain
  and run kind. A milestone is written there once and never again.
- `MilestoneRecorder` keeps a rolling buffer of cheap fly snapshots and, when
  a milestone lands, writes the one from about `replay_lead` ticks before it
  to `milestones/<name>/` so `run.py --replay <name>` can show it on camera.

Game time is ticks at 60 a second, counted from the cold boot: a run that
starts from a savestate starts its clock at the state's own tick offset, which
the state's sidecar (`<state>.json`) records.
"""

from __future__ import annotations

import json
import os
import time
from collections import deque
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from .config import (
    BATTLE_LOST,
    OAKS_LAB,
    PALLET_TOWN,
    PEWTER_CITY,
    POKEMON_CENTERS,
    REDS_HOUSE_1F,
    REDS_HOUSE_2F,
    ROUTE_1,
    VIRIDIAN_CITY,
    VIRIDIAN_FOREST,
    Config,
)
from .reward import RamSnapshot, has_control

TICKS_PER_SECOND = 60


def game_time(ticks: int, hz: int = TICKS_PER_SECOND) -> str:
    """`m:ss`, or `h:mm:ss` past an hour, of game time."""
    seconds = max(0, int(ticks)) // hz
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


# ------------------------------------------------------------ predicates ---


@dataclass(frozen=True)
class Moment:
    """What a predicate may look at. `prev` is None on a run's first tick."""

    prev: RamSnapshot | None
    now: RamSnapshot
    won_battle: bool = False  # a battle ended this tick and it was a win


def _left_bedroom(m: Moment) -> bool:
    return m.prev is not None and m.now.named and m.prev.map_id == REDS_HOUSE_2F and m.now.map_id != REDS_HOUSE_2F


def _left_house(m: Moment) -> bool:
    # Out of Red's front door: 1F straight into Pallet Town. The lab and the
    # rival's house also open onto Pallet, which is why the previous map is
    # checked and not only the current one.
    return m.prev is not None and m.now.named and m.prev.map_id == REDS_HOUSE_1F and m.now.map_id == PALLET_TOWN


def _in_map(*maps: int) -> Callable[[Moment], bool]:
    wanted = frozenset(maps)
    # With control, so the boot-time zero in wCurMap and mid-cutscene map
    # writes are never mistaken for arriving somewhere.
    return lambda m: has_control(m.now) and m.now.map_id in wanted


def _got_starter(m: Moment) -> bool:
    return m.prev is not None and m.now.named and m.prev.party_count == 0 and m.now.party_count == 1


def _first_battle(m: Moment) -> bool:
    return m.now.named and m.now.battle in (1, 2)


def _first_win(m: Moment) -> bool:
    return m.won_battle


def _first_level_up(m: Moment) -> bool:
    # Same party size, more levels: a catch or the starter also raises the
    # level sum, and those are not a level up.
    prev, now = m.prev, m.now
    return (
        prev is not None
        and now.named
        and now.party_count >= 1
        and prev.party_count == now.party_count
        and now.level_sum > prev.level_sum
    )


def _first_badge(m: Moment) -> bool:
    return m.now.named and bool(m.now.badge_bits & 1)  # wObtainedBadges bit 0: Boulder


@dataclass(frozen=True)
class Milestone:
    name: str
    label: str  # what the overlay and the log say, in plain words
    test: Callable[[Moment], bool]


MILESTONES: tuple[Milestone, ...] = (
    Milestone("left_bedroom", "left the bedroom", _left_bedroom),
    Milestone("left_house", "left the house", _left_house),
    Milestone("entered_lab", "walked into Oak's lab", _in_map(OAKS_LAB)),
    Milestone("got_starter", "got a Pokemon", _got_starter),
    Milestone("first_battle", "first battle", _first_battle),
    Milestone("first_win", "won a battle", _first_win),
    Milestone("route_1", "reached Route 1", _in_map(ROUTE_1)),
    Milestone("viridian_city", "reached Viridian City", _in_map(VIRIDIAN_CITY)),
    Milestone("first_level_up", "first level up", _first_level_up),
    Milestone("pokemon_center", "walked into a Pokemon Center", _in_map(*POKEMON_CENTERS)),
    Milestone("viridian_forest", "entered Viridian Forest", _in_map(VIRIDIAN_FOREST)),
    Milestone("pewter_city", "reached Pewter City", _in_map(PEWTER_CITY)),
    Milestone("first_badge", "won the Boulder Badge", _first_badge),
)

MILESTONE_NAMES: tuple[str, ...] = tuple(m.name for m in MILESTONES)
LABELS: dict[str, str] = {m.name: m.label for m in MILESTONES}


def milestone_line(name: str, game_tick: int, brain: str, episodes: int) -> str:
    """The one line the HUD and the log print when a milestone lands."""
    return (
        f"milestone: {LABELS.get(name, name)}  {game_time(game_tick)} of game time  "
        f"(brain {brain or 'none'}, {episodes} episodes)"
    )


# --------------------------------------------------------------- tracker ---


class MilestoneTracker:
    """First time each predicate holds, in this run, on the game clock.

    `first_win` needs one fact across a battle, kept here: the party's total
    experience when the battle started, and whether wIsInBattle ever read
    $FF (pokered: "lost battle, this is -1"). A battle that ends (wIsInBattle
    back to 0) is a win when it was not lost, the party gained experience
    (only defeating an enemy Pokemon gives any, so running away is not a win)
    and every party member's HP is above zero (no faint).
    """

    def __init__(self, cfg: Config | None = None, start_tick: int = 0) -> None:
        self.cfg = cfg or Config()
        self.reset(start_tick)

    def reset(self, start_tick: int = 0) -> None:
        self.landed: dict[str, int] = {}  # name -> game tick, in landing order
        self.last: str | None = None
        self.last_tick = int(start_tick)
        self.start_tick = int(start_tick)
        self.prev: RamSnapshot | None = None
        self._battle = False
        self._battle_exp = 0
        self._battle_lost = False

    def _battle_result(self, now: RamSnapshot) -> bool:
        """Keep the battle watch and say whether a battle was won this tick."""
        if not now.named:
            return False
        if now.battle and not self._battle:
            self._battle, self._battle_exp, self._battle_lost = True, now.exp_sum, False
        if not self._battle:
            return False
        if now.battle == BATTLE_LOST:
            self._battle_lost = True
        if now.battle:
            return False
        self._battle = False
        return (
            not self._battle_lost
            and now.exp_sum > self._battle_exp
            and bool(now.party_hp)
            and all(hp > 0 for hp in now.party_hp)
        )

    def update(self, now: RamSnapshot, game_tick: int) -> tuple[str, ...]:
        """Every milestone whose predicate holds for the first time this tick,
        in story order. Usually none, occasionally one."""
        moment = Moment(self.prev, now, self._battle_result(now))
        self.prev = now
        fresh = tuple(m.name for m in MILESTONES if m.name not in self.landed and m.test(moment))
        for name in fresh:
            self.landed[name] = int(game_tick)
            self.last, self.last_tick = name, int(game_tick)
        return fresh

    def since(self, game_tick: int) -> int:
        """Ticks since the last milestone, or since the run's clock started."""
        return max(0, int(game_tick) - self.last_tick)

    # -- snapshots ---------------------------------------------------------

    def get_state(self) -> dict:
        return {
            "landed": [[name, tick] for name, tick in self.landed.items()],
            "last": self.last,
            "last_tick": self.last_tick,
            "start_tick": self.start_tick,
            "prev": None if self.prev is None else asdict(self.prev),
            "battle": self._battle,
            "battle_exp": self._battle_exp,
            "battle_lost": self._battle_lost,
        }

    def set_state(self, state: dict) -> None:
        self.landed = {str(name): int(tick) for name, tick in state["landed"]}
        self.last = state["last"]
        self.last_tick = int(state["last_tick"])
        self.start_tick = int(state["start_tick"])
        prev = state["prev"]
        if prev is None:
            self.prev = None
        else:
            values = dict(prev)
            values["party_species"] = tuple(int(v) for v in values.get("party_species", ()))
            values["party_hp"] = tuple(int(v) for v in values.get("party_hp", ()))
            self.prev = RamSnapshot(**values)
        self._battle = bool(state["battle"])
        self._battle_exp = int(state["battle_exp"])
        self._battle_lost = bool(state["battle_lost"])


# ------------------------------------------------------------ start offset ---


def sidecar_path(state_path: str | Path) -> Path:
    state_path = Path(state_path)
    return state_path.with_name(state_path.name + ".json")


def read_tick_offset(state_path: str | Path) -> int | None:
    """The game tick a savestate was taken at, from its sidecar, or None."""
    side = sidecar_path(state_path)
    if not side.is_file():
        return None
    try:
        return int(json.loads(side.read_text(encoding="utf-8"))["game_tick"])
    except (ValueError, KeyError, TypeError):
        return None


def write_tick_offset(state_path: str | Path, game_tick: int, note: str = "") -> Path:
    side = sidecar_path(state_path)
    body = {"game_tick": int(game_tick), "game_time": game_time(game_tick)}
    if note:
        body["note"] = note
    _write_json(side, body)
    return side


def _write_json(path: Path, body) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(path.name + ".partial")
    partial.write_text(json.dumps(body, indent=2) + "\n", encoding="utf-8")
    os.replace(partial, path)


# ---------------------------------------------------------------- journey ---


class JourneyLog:
    """`milestones/journey.json`: the first time each milestone was ever
    reached, across every run and every brain. Written whole each time."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.entries: list[dict] = []
        if self.path.is_file():
            body = json.loads(self.path.read_text(encoding="utf-8"))
            self.entries = list(body.get("milestones", []))

    def has(self, name: str) -> bool:
        return any(entry["name"] == name for entry in self.entries)

    def record(self, name: str, game_tick: int, *, brain: str, episodes: int, kind: str, now: datetime | None = None) -> bool:
        """Add the milestone if the journey has not reached it before. True
        when this was its first time."""
        if self.has(name):
            return False
        stamp = (now or datetime.now()).isoformat(timespec="seconds")
        self.entries.append(
            {
                "name": name,
                "label": LABELS.get(name, name),
                "game_tick": int(game_tick),
                "game_time": game_time(game_tick),
                "date": stamp,
                "brain": brain,
                "episodes_trained": int(episodes),
                "kind": kind,
            }
        )
        _write_json(self.path, {"milestones": self.entries})
        return True


# --------------------------------------------------------------- recorder ---


@dataclass
class _Buffered:
    game_tick: int
    step: int
    snapshot: object  # FlySnapshot


class MilestoneRecorder:
    """The rolling buffer and the replay writer.

    Every `snapshot_every` ticks it keeps a cheap fly snapshot, holding enough
    of them to reach `replay_lead` ticks back. Every `anchor_every` ticks of
    emulator time the snapshot is taken on a fresh full savestate instead, so
    a replay never has to fast-forward further than that. When a milestone
    lands it goes into the journey log, and its replay is written when it is
    new to the journey or has no replay yet.
    """

    def __init__(
        self,
        cfg: Config,
        root: str | Path,
        kind: str,
        journey: JourneyLog | None = None,
        say: Callable[[str], None] | None = None,
    ) -> None:
        self.cfg = cfg
        self.root = Path(root)
        self.kind = kind
        self.journey = journey
        self.say = say or (lambda line: print(line, flush=True))
        self.every = max(1, cfg.snapshot_every)
        keep = cfg.replay_lead // self.every + 2
        self.buffer: deque[_Buffered] = deque(maxlen=keep)
        self.written: list[str] = []
        self.snapshot_ms: list[float] = []

    def begin(self, fly, step: int = 0) -> None:
        """A run (or an episode) starts: forget the old buffer, keep one now."""
        self.buffer.clear()
        self._keep(fly, step)

    def _keep(self, fly, step: int) -> None:
        started = time.perf_counter()
        if fly.emulator.ticks_since_anchor >= self.cfg.anchor_every:
            fly.emulator.anchor()
        self.buffer.append(_Buffered(fly.clock, step, fly.snapshot()))
        self.snapshot_ms.append((time.perf_counter() - started) * 1000.0)
        if len(self.snapshot_ms) > 4096:
            del self.snapshot_ms[:2048]

    def __call__(self, fly, state) -> None:
        """After every tick, with the fly and the tick it produced."""
        if state.step % self.every == 0:
            self._keep(fly, state.step)
        for name in state.milestones:
            self._landed(fly, state, name)

    def _landed(self, fly, state, name: str) -> None:
        first = False
        if self.journey is not None:
            first = self.journey.record(
                name, state.game_tick, brain=fly.brain_label, episodes=fly.mushroom.episodes_trained, kind=self.kind
            )
        folder = self.root / name
        from .snapshot import FlySnapshot  # here, so the tracker imports nothing heavy

        if not (first or not FlySnapshot.exists(folder)) or not self.buffer:
            return
        target = state.game_tick - self.cfg.replay_lead
        usable = [entry for entry in self.buffer if entry.game_tick <= state.game_tick]
        chosen = min(usable, key=lambda entry: abs(entry.game_tick - target))
        snapshot = chosen.snapshot
        snapshot.meta.update(
            {
                "milestone": name,
                "label": LABELS.get(name, name),
                "landed_tick": int(state.game_tick),
                "landed_step": int(state.step),
                "start_tick": int(chosen.game_tick),
                "start_step": int(chosen.step),
                "kind": self.kind,
                "brain": fly.brain_label,
                "episodes_trained": int(fly.mushroom.episodes_trained),
                "date": datetime.now().isoformat(timespec="seconds"),
            }
        )
        snapshot.save(folder, "start")
        _write_json(folder / "replay.json", {"fingerprint": snapshot.fingerprint, **snapshot.meta})
        self.written.append(name)
        self.say(
            f"replay written: {folder} starts {game_time(state.game_tick - chosen.game_tick)} before "
            f"{LABELS.get(name, name)} ({'first time on the journey' if first else 'no replay existed yet'})"
        )
