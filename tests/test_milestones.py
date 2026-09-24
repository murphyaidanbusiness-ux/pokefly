"""The milestone table, the tracker, the journey log and the game clock.

Everything here runs on synthetic `RamSnapshot`s: no ROM. The one test that
checks the start-state offset on the real game skips without the ROM.
"""

from __future__ import annotations

import csv
import json
import shutil
from dataclasses import replace

import pytest
from conftest import ROM, ROOT

from flybrain.config import POKEMON_CENTERS, Config
from flybrain.milestones import (
    LABELS,
    MILESTONE_NAMES,
    JourneyLog,
    MilestoneTracker,
    game_time,
    milestone_line,
    read_tick_offset,
    write_tick_offset,
)
from flybrain.reward import RamSnapshot
from flybrain.training import CSV_FIELDS, EpisodeResult, milestone_table

NAMED = 0x80  # "A" in Pokemon's charmap: any real first letter will do


def snap(**changes) -> RamSnapshot:
    base = dict(
        map_id=0x26,
        x=3,
        y=6,
        in_battle=False,
        party_count=0,
        level_sum=0,
        badge_bits=0,
        event_bits=0,
        name_byte=NAMED,
        joy_ignore=0,
        battle=0,
        party_species=(),
        party_hp=(),
        exp_sum=0,
    )
    base.update(changes)
    base["in_battle"] = bool(base["battle"])
    return RamSnapshot(**base)


def feed(tracker: MilestoneTracker, *snapshots: RamSnapshot, start: int = 1) -> dict[int, tuple[str, ...]]:
    """Feed snapshots on consecutive ticks; return {tick: what landed}."""
    landed = {}
    for offset, one in enumerate(snapshots):
        got = tracker.update(one, start + offset)
        if got:
            landed[start + offset] = got
    return landed


def lands(*snapshots: RamSnapshot) -> set[str]:
    tracker = MilestoneTracker()
    return {name for names in feed(tracker, *snapshots).values() for name in names}


# ------------------------------------------------------------ the table ----


def test_the_table_is_in_story_order_and_has_every_milestone_the_spec_names():
    assert MILESTONE_NAMES == (
        "left_bedroom",
        "left_house",
        "entered_lab",
        "got_starter",
        "first_battle",
        "first_win",
        "route_1",
        "viridian_city",
        "first_level_up",
        "pokemon_center",
        "viridian_forest",
        "pewter_city",
        "first_badge",
    )
    assert set(LABELS) == set(MILESTONE_NAMES)
    # Plain words for the overlay, never a field name.
    assert all(label and "_" not in label for label in LABELS.values())


def test_the_map_ids_are_the_pokered_constants():
    from flybrain import config

    assert (config.PALLET_TOWN, config.VIRIDIAN_CITY, config.PEWTER_CITY, config.ROUTE_1) == (0x00, 0x01, 0x02, 0x0C)
    assert (config.REDS_HOUSE_1F, config.REDS_HOUSE_2F, config.OAKS_LAB, config.VIRIDIAN_FOREST) == (
        0x25,
        0x26,
        0x28,
        0x33,
    )
    assert {0x29, 0x3A, 0x40, 0x44} <= POKEMON_CENTERS and len(POKEMON_CENTERS) == 11


# ------------------------------------------------------------ predicates ----


def test_left_bedroom_is_the_stairs_down_and_only_with_a_game_running():
    assert lands(snap(map_id=0x26), snap(map_id=0x25)) == {"left_bedroom"}
    assert "left_bedroom" not in lands(snap(map_id=0x26, name_byte=0x50), snap(map_id=0x25, name_byte=0x50))
    assert "left_bedroom" not in lands(snap(map_id=0x25), snap(map_id=0x25))


def test_left_house_is_red_s_front_door_and_not_the_lab_door():
    assert "left_house" in lands(snap(map_id=0x25), snap(map_id=0x00))
    assert "left_house" not in lands(snap(map_id=0x28), snap(map_id=0x00))
    assert "left_house" not in lands(snap(map_id=0x27), snap(map_id=0x00))


def test_a_map_milestone_waits_for_control():
    """The lab is entered in a cutscene (Oak walks you in), so it lands on the
    first tick the player has control there, not on the map write."""
    tracker = MilestoneTracker()
    landed = feed(tracker, snap(map_id=0x00), snap(map_id=0x28, joy_ignore=0xFF), snap(map_id=0x28))
    assert landed == {3: ("entered_lab",)}
    # And never from uninitialised RAM before there is a name.
    assert "entered_lab" not in lands(snap(map_id=0x28, name_byte=0xFF))


@pytest.mark.parametrize(
    ("map_id", "name"),
    [(0x0C, "route_1"), (0x01, "viridian_city"), (0x33, "viridian_forest"), (0x02, "pewter_city")],
)
def test_arriving_somewhere(map_id, name):
    assert lands(snap(map_id=map_id)) == {name}


@pytest.mark.parametrize("center", sorted(POKEMON_CENTERS))
def test_any_pokemon_center(center):
    assert lands(snap(map_id=center)) == {"pokemon_center"}


def test_got_starter_is_the_party_going_from_nothing_to_one():
    assert "got_starter" in lands(snap(map_id=0x28), snap(map_id=0x28, party_count=1, level_sum=5, party_hp=(20,)))
    # A party that was already there is not a starter.
    one = dict(party_count=1, level_sum=5, party_hp=(20,))
    assert "got_starter" not in lands(snap(map_id=0x28, **one), snap(map_id=0x28, **one))


def test_first_battle_is_wild_or_trainer():
    assert "first_battle" in lands(snap(), snap(battle=1))
    assert "first_battle" in lands(snap(), snap(battle=2))
    assert "first_battle" not in lands(snap(battle=1, name_byte=0x00))


def _battle(end_exp, end_hp=(15,), lost=False):
    party = dict(party_count=1, level_sum=5, party_species=(0xB1,))
    frames = [
        snap(map_id=0x28, exp_sum=100, party_hp=(20,), **party),
        snap(map_id=0x28, battle=2, exp_sum=100, party_hp=(20,), **party),
        snap(map_id=0x28, battle=2, exp_sum=end_exp, party_hp=end_hp, **party),
    ]
    if lost:
        frames.append(snap(map_id=0x28, battle=0xFF, exp_sum=end_exp, party_hp=end_hp, **party))
    frames.append(snap(map_id=0x28, battle=0, exp_sum=end_exp, party_hp=end_hp, **party))
    return frames


def test_a_battle_that_ends_with_experience_and_nobody_fainted_is_a_win():
    tracker = MilestoneTracker()
    landed = feed(tracker, *_battle(end_exp=160))
    assert landed[2] == ("first_battle",)
    assert landed[4] == ("first_win",), "it lands on the tick the battle ends"


def test_running_away_losing_or_fainting_is_not_a_win():
    assert "first_win" not in lands(*_battle(end_exp=100)), "no experience: it ran away"
    assert "first_win" not in lands(*_battle(end_exp=160, lost=True)), "wIsInBattle read $FF: lost"
    assert "first_win" not in lands(*_battle(end_exp=160, end_hp=(0,))), "the lead fainted"


def test_first_level_up_is_more_levels_in_the_same_party():
    party = dict(party_count=1, party_hp=(20,))
    assert "first_level_up" in lands(snap(level_sum=5, **party), snap(level_sum=6, **party))
    # The starter arriving raises the level sum from 0 to 5: not a level up.
    assert "first_level_up" not in lands(snap(), snap(level_sum=5, **party))
    # Nor does a catch (party of 1 to 2).
    assert "first_level_up" not in lands(
        snap(level_sum=6, **party), snap(level_sum=9, party_count=2, party_hp=(20, 12))
    )


def test_first_badge_is_the_boulder_badge_bit():
    assert "first_badge" in lands(snap(map_id=0x36, badge_bits=0b1))
    assert "first_badge" not in lands(snap(map_id=0x36, badge_bits=0b10))


# ----------------------------------------------------------- the tracker ----


def test_a_milestone_lands_once_however_long_it_stays_true():
    tracker = MilestoneTracker()
    frames = [snap(map_id=0x0C)] * 50 + [snap(map_id=0x00)] + [snap(map_id=0x0C)] * 5
    landed = feed(tracker, *frames, start=100)
    assert landed == {100: ("route_1",)}
    assert tracker.landed == {"route_1": 100}


def test_since_and_last_follow_the_game_clock():
    tracker = MilestoneTracker(start_tick=5047)
    assert tracker.since(5100) == 53 and tracker.last is None
    feed(tracker, snap(map_id=0x26), snap(map_id=0x25), start=5200)
    assert tracker.last == "left_bedroom" and tracker.since(5301) == 100


def test_the_tracker_state_round_trips_through_json():
    first = MilestoneTracker()
    feed(first, *_battle(end_exp=160)[:3], start=10)  # mid-battle, starter gone
    state = json.loads(json.dumps(first.get_state()))
    second = MilestoneTracker()
    second.set_state(state)
    tail = _battle(end_exp=160)[3:]
    assert feed(first, *tail, start=13) == feed(second, *tail, start=13) == {13: ("first_win",)}


# ------------------------------------------------------------ game time ----


def test_game_time_is_minutes_and_seconds_at_60_ticks():
    assert game_time(0) == "0:00"
    assert game_time(15_120) == "4:12"
    assert game_time(59) == "0:00"
    assert game_time(216_000 + 61 * 60) == "1:01:01"


def test_the_milestone_line_is_the_one_in_the_spec():
    assert (
        milestone_line("left_house", 15_120, "latest.npz", 100)
        == "milestone: left the house  4:12 of game time  (brain latest.npz, 100 episodes)"
    )


# ------------------------------------------------------------- journey ----


def test_the_journey_log_keeps_the_first_time_across_two_lifetimes(tmp_path):
    path = tmp_path / "milestones" / "journey.json"
    first = JourneyLog(path)
    assert first.record("left_bedroom", 5400, brain="latest.npz", episodes=230, kind="train")
    assert not first.record("left_bedroom", 5100, brain="latest.npz", episodes=231, kind="train")

    second = JourneyLog(path)  # a later run reads what the first one wrote
    assert second.has("left_bedroom") and not second.has("left_house")
    assert not second.record("left_bedroom", 5000, brain="journey", episodes=1, kind="watch")
    assert second.record("left_house", 9000, brain="journey", episodes=231, kind="watch")

    entries = json.loads(path.read_text(encoding="utf-8"))["milestones"]
    assert [e["name"] for e in entries] == ["left_bedroom", "left_house"]
    assert entries[0]["game_tick"] == 5400 and entries[0]["game_time"] == "1:30"
    assert entries[0]["kind"] == "train" and entries[1]["kind"] == "watch"
    assert set(entries[0]) == {"name", "label", "game_tick", "game_time", "date", "brain", "episodes_trained", "kind"}


# ------------------------------------------------------- start offsets ----


def test_a_state_sidecar_carries_its_tick_offset(tmp_path):
    state = tmp_path / "x.state"
    state.write_bytes(b"")
    assert read_tick_offset(state) is None
    write_tick_offset(state, 5047)
    assert read_tick_offset(state) == 5047
    assert (tmp_path / "x.state.json").is_file()


@pytest.mark.skipif(not ROM.is_file(), reason="no ROM in roms/")
@pytest.mark.skipif(not (ROOT / "states" / "bedroom.state").is_file(), reason="states/bedroom.state not present")
def test_a_run_from_a_state_counts_game_time_from_its_offset(tmp_path):
    from flybrain.loop import run_loop

    state = tmp_path / "bedroom.state"
    shutil.copyfile(ROOT / "states" / "bedroom.state", state)
    write_tick_offset(state, 5047)
    ticks = []
    cfg = replace(Config(), rom_path=ROM, headless=True, uncapped=True, hud=False, max_steps=20, load_state=state)
    summary = run_loop(cfg, observers=(lambda t: ticks.append(t.game_tick),))
    assert ticks[0] == 5048 and ticks[-1] == 5067 and summary["game_tick"] == 5067

    # Without a sidecar the clock starts at zero, and says so.
    (tmp_path / "bedroom.state.json").unlink()
    ticks.clear()
    run_loop(cfg, observers=(lambda t: ticks.append(t.game_tick),))
    assert ticks[0] == 1


@pytest.mark.skipif(not ROM.is_file(), reason="no ROM in roms/")
@pytest.mark.skipif(not (ROOT / "states" / "bedroom.state").is_file(), reason="states/bedroom.state not present")
def test_a_training_episode_starts_its_clock_at_the_state_offset(tmp_path):
    from flybrain.emulator import Emulator
    from flybrain.loop import Fly
    from flybrain.training import run_episode

    state = tmp_path / "bedroom.state"
    shutil.copyfile(ROOT / "states" / "bedroom.state", state)
    write_tick_offset(state, 1234)
    cfg = replace(Config(), rom_path=ROM, headless=True, uncapped=True)
    emulator = Emulator(ROM, headless=True, uncapped=True, cfg=cfg)
    try:
        fly = Fly(cfg, emulator)
        run_episode(fly, 10, seed=1, learning=False, state_path=state)
        assert fly.clock == 1244
    finally:
        emulator.close()


# ----------------------------------------------------------- the CSV ------


def result(episode, milestones):
    return EpisodeResult(
        episode=episode,
        kind="train",
        ticks=20_000,
        reward=1.0,
        parts=dict.fromkeys(("tile", "map", "event", "level", "badge"), 0.0),
        tiles=1,
        maps=[0x26],
        furthest=0x26,
        left_house=False,
        presses=dict.fromkeys(("UP", "DOWN", "LEFT", "RIGHT", "A", "B", "START"), 0),
        panics=0,
        mean_abs_delta=0.0,
        w_actor_abs=0.0,
        w_critic_abs=0.0,
        ticks_per_second=1.0,
        seed=episode,
        milestones=milestones,
    )


def test_every_milestone_has_a_csv_column_and_blank_means_never():
    row = result(1, {"left_bedroom": 812}).row()
    assert set(row) == set(CSV_FIELDS)
    assert row["ms_left_bedroom"] == 812 and row["ms_left_house"] == ""
    assert [f for f in CSV_FIELDS if f.startswith("ms_")] == [f"ms_{name}" for name in MILESTONE_NAMES]


def test_the_milestone_table_is_the_median_by_bucket(tmp_path):
    path = tmp_path / "train.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for episode in range(1, 21):
            got = {"left_bedroom": 1000 - episode}
            if episode > 10 and episode % 2:
                got["left_house"] = 5000 + episode
            writer.writerow(result(episode, got).row())
    table = milestone_table(path, bucket=10)
    assert [line["episodes"] for line in table] == ["1-10", "11-20"]
    assert table[0]["milestones"]["left_bedroom"] == (10, 994.5)
    assert table[0]["milestones"]["left_house"] == (0, None)
    assert table[1]["milestones"]["left_house"] == (5, 5015)
