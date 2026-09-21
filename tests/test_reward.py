"""Reward semantics on synthetic snapshots. No emulator, no ROM."""

import pytest

from flybrain.config import Config
from flybrain.reward import PARTS, RamSnapshot, RewardTracker, has_control

NAMED = 0x91  # a real character: the player has a name


def snap(map_id=0x26, x=3, y=6, **overrides):
    base = dict(
        map_id=map_id,
        x=x,
        y=y,
        in_battle=False,
        party_count=0,
        level_sum=0,
        badge_bits=0,
        event_bits=0,
        name_byte=NAMED,
        joy_ignore=0,
    )
    base.update(overrides)
    return RamSnapshot(**base)


def tracker():
    tracked = RewardTracker(Config())
    tracked.step(snap())  # the first controlled tick books the start square
    return tracked


def test_nothing_is_paid_before_the_player_has_control():
    """Uninitialised RAM reads map 0, which is Pallet Town's id. Paying for it
    would score the boot sequence as a walk into town."""
    assert not has_control(snap(name_byte=0x00))
    assert not has_control(snap(name_byte=0x50))  # the string terminator
    assert not has_control(snap(name_byte=0xFF))
    assert not has_control(snap(joy_ignore=0xFF))  # a cutscene
    assert has_control(snap())

    tracked = RewardTracker(Config())
    for _ in range(50):
        reward, _ = tracked.step(snap(map_id=0x00, x=5, y=5, name_byte=0x00))
        assert reward == 0.0
    assert not tracked.started
    assert tracked.maps == set()


def test_the_start_square_pays_nothing_and_neither_does_standing_still():
    tracked = RewardTracker(Config())
    assert tracked.step(snap())[0] == 0.0
    for _ in range(20):
        assert tracked.step(snap())[0] == 0.0
    assert tracked.total == 0.0


def test_a_new_tile_pays_once():
    cfg = Config()
    tracked = tracker()
    reward, parts = tracked.step(snap(y=7))
    assert reward == cfg.reward_tile and parts["tile"] == cfg.reward_tile
    assert tracked.step(snap(y=7))[0] == 0.0
    assert tracked.step(snap(y=6))[0] == 0.0  # back to the start square
    assert tracked.step(snap(y=8))[0] == cfg.reward_tile


def test_a_new_map_pays_its_own_reward_on_top_of_the_tile():
    cfg = Config()
    tracked = tracker()
    reward, parts = tracked.step(snap(map_id=0x25, x=7, y=1))
    assert parts["map"] == cfg.reward_map
    assert parts["tile"] == cfg.reward_tile
    assert reward == cfg.reward_map + cfg.reward_tile


def test_the_stairs_cannot_be_farmed():
    """Up and down the staircase eleven times is what the untrained fly did for
    sixteen minutes. It has to be worth nothing after the first trip."""
    cfg = Config()
    tracked = tracker()
    first = tracked.step(snap(map_id=0x25, x=7, y=1))[0]
    assert first == cfg.reward_map + cfg.reward_tile
    earned = 0.0
    for _ in range(11):
        earned += tracked.step(snap(map_id=0x26, x=3, y=6))[0]
        earned += tracked.step(snap(map_id=0x25, x=7, y=1))[0]
    assert earned == 0.0


def test_each_new_event_bit_pays_once():
    cfg = Config()
    tracked = tracker()
    assert tracked.step(snap(event_bits=0))[0] == 0.0
    assert tracked.step(snap(event_bits=3))[0] == 3 * cfg.reward_event
    assert tracked.step(snap(event_bits=3))[0] == 0.0
    assert tracked.step(snap(event_bits=4))[0] == cfg.reward_event
    assert tracked.step(snap(event_bits=2))[0] == 0.0  # a cleared flag never refunds
    assert tracked.step(snap(event_bits=5))[0] == cfg.reward_event


def test_levels_and_badges():
    cfg = Config()
    tracked = tracker()
    assert tracked.step(snap(party_count=1, level_sum=5))[0] == 5 * cfg.reward_level
    assert tracked.step(snap(party_count=1, level_sum=5))[0] == 0.0
    assert tracked.step(snap(party_count=1, level_sum=6))[0] == cfg.reward_level
    assert tracked.step(snap(badge_bits=0b0000_0001))[0] == cfg.reward_badge
    assert tracked.step(snap(badge_bits=0b0000_0011))[0] == cfg.reward_badge
    assert tracked.step(snap(badge_bits=0b0000_0011))[0] == 0.0


def test_the_baseline_is_taken_on_the_first_controlled_tick():
    """A savestate with a party already in it must not pay for that party."""
    cfg = Config()
    tracked = RewardTracker(cfg)
    tracked.step(snap(party_count=1, level_sum=9, event_bits=40, badge_bits=0b11))
    assert tracked.step(snap(party_count=1, level_sum=9, event_bits=40, badge_bits=0b11))[0] == 0.0
    assert tracked.step(snap(party_count=1, level_sum=10, event_bits=41, badge_bits=0b11))[0] == pytest.approx(
        cfg.reward_level + cfg.reward_event
    )


def test_reset_clears_the_episode():
    tracked = tracker()
    tracked.step(snap(map_id=0x25, x=7, y=1))
    assert tracked.total > 0
    tracked.reset()
    assert tracked.total == 0.0 and not tracked.tiles and not tracked.maps and not tracked.started
    assert all(tracked.parts[name] == 0.0 for name in PARTS)
    tracked.step(snap())
    assert tracked.step(snap(map_id=0x25, x=7, y=1))[0] > 0  # the map is new again


def test_parts_add_up_to_the_total():
    tracked = tracker()
    total = sum(tracked.step(s)[0] for s in (snap(y=7), snap(map_id=0x25, x=7, y=1), snap(event_bits=2)))
    assert tracked.total == pytest.approx(total)
    assert sum(tracked.parts.values()) == pytest.approx(total)
