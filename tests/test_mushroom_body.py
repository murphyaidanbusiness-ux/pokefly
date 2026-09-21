"""The Kenyon cell code, the readouts, and the file on disk."""

from dataclasses import replace

import numpy as np
import pytest

from flybrain.config import POOL_NAMES, Config
from flybrain.mushroom_body import BrainFileMismatch, MushroomBody


def frame(seed: int, size: int = 16) -> np.ndarray:
    return np.random.default_rng(seed).random((size, size)).astype(np.float32)


def test_exactly_the_top_k_are_active():
    cfg = Config()
    mb = MushroomBody(cfg, 0)
    active = mb.kenyon_cells(frame(1))
    assert active.size == cfg.n_kc_active == 100
    assert np.unique(active).size == active.size


def test_the_code_is_deterministic_under_a_seed():
    cfg = Config()
    one, two = MushroomBody(cfg, 3), MushroomBody(cfg, 3)
    picture = frame(5)
    assert np.array_equal(np.sort(one.kenyon_cells(picture)), np.sort(two.kenyon_cells(picture)))
    other = MushroomBody(cfg, 4)
    assert not np.array_equal(np.sort(one.kenyon_cells(picture)), np.sort(other.kenyon_cells(picture)))


def test_two_different_frames_share_few_kenyon_cells():
    mb = MushroomBody(Config(), 0)
    a, b = mb.kenyon_cells(frame(1)), mb.kenyon_cells(frame(2))
    overlap = np.intersect1d(a, b).size / a.size
    assert overlap < 0.35, f"two unrelated frames share {overlap:.0%} of the code"


def test_the_same_frame_plus_small_noise_shares_most_of_the_code():
    mb = MushroomBody(Config(), 0)
    picture = frame(1)
    jittered = picture + np.random.default_rng(9).normal(0.0, 0.01, picture.shape).astype(np.float32)
    overlap = np.intersect1d(mb.kenyon_cells(picture), mb.kenyon_cells(jittered)).size / mb.n_active
    assert overlap > 0.80, f"a 1% jitter moved {1 - overlap:.0%} of the code"


def test_global_brightness_does_not_change_the_code():
    """The frame mean is subtracted, so the code is about the pattern and not
    the backlight. Otherwise every dark screen would share one code."""
    mb = MushroomBody(Config(), 0)
    picture = frame(1)
    assert np.array_equal(np.sort(mb.kenyon_cells(picture)), np.sort(mb.kenyon_cells(picture + 0.2)))
    assert np.array_equal(np.sort(mb.kenyon_cells(picture)), np.sort(mb.kenyon_cells(picture - 0.3)))


def test_an_untrained_body_biases_nothing():
    mb = MushroomBody(Config(), 0)
    mb.observe(frame(1))
    assert np.allclose(mb.pool_currents(), 0.0)
    assert mb.value == 0.0


def test_the_bias_is_squashed_and_bounded():
    cfg = Config()
    mb = MushroomBody(cfg, 0)
    mb.observe(frame(1))
    mb.w_actor[POOL_NAMES.index("UP"), mb.active] = cfg.w_actor_clip
    mb.observe(frame(1))
    currents = mb.pool_currents()
    assert abs(currents[POOL_NAMES.index("UP")]) <= cfg.mbon_gain + 1e-6
    assert currents[POOL_NAMES.index("UP")] > 0.9 * cfg.mbon_gain


def test_credit_is_a_preference_shift_and_sums_to_zero():
    """The chosen pool gets +1 and the other six get -1/6, so an update moves
    preference between pools instead of turning the whole body up."""
    mb = MushroomBody(Config(), 0)
    mb.observe(frame(1))
    mb.credit(["LEFT"])
    column = mb.e_actor[:, mb.active[0]]
    assert column[POOL_NAMES.index("LEFT")] == pytest.approx(1.0)
    assert column.sum() == pytest.approx(0.0, abs=1e-6)
    assert mb.e_actor[:, np.setdiff1d(np.arange(mb.n_kc), mb.active)].sum() == 0.0


def test_traces_decay_and_reset():
    cfg = Config()
    mb = MushroomBody(cfg, 0)
    mb.observe(frame(1))
    mb.credit(["UP"])
    mb.credit_critic()
    before = mb.e_critic.sum()
    mb.decay_traces()
    assert mb.e_critic.sum() == pytest.approx(before * cfg.lambda_critic)
    mb.reset_traces()
    assert not mb.e_actor.any() and not mb.e_critic.any()


def test_no_dopamine_on_the_first_tick_of_an_episode():
    """There is no previous state to compare against, so there is no error."""
    mb = MushroomBody(Config(), 0)
    mb.observe(frame(1))
    assert mb.learn(5.0) == 0.0


def test_the_td_error_is_reward_plus_discounted_value_minus_value():
    cfg = replace(Config(), gamma=0.9)
    mb = MushroomBody(cfg, 0)
    mb.observe(frame(1))
    mb.learn(0.0)  # priming tick
    mb.w_critic[:] = 0.01
    mb.observe(frame(2))
    expected = 1.0 + cfg.gamma * mb.value - 0.0
    mb.learning = False
    assert mb.learn(1.0) == pytest.approx(expected)


def test_save_and_load_round_trip(tmp_path):
    cfg = Config()
    mb = MushroomBody(cfg, 2)
    mb.w_actor += 0.01
    mb.w_critic += 0.02
    mb.episodes_trained, mb.ticks_trained = 17, 340_000
    path = mb.save(tmp_path / "brain.npz")

    fresh = MushroomBody(cfg, 2)
    fresh.load(path)
    assert np.array_equal(fresh.w_actor, mb.w_actor)
    assert np.array_equal(fresh.w_critic, mb.w_critic)
    assert (fresh.episodes_trained, fresh.ticks_trained) == (17, 340_000)


def test_loading_a_brain_built_for_a_different_expansion_is_an_error(tmp_path):
    cfg = Config()
    path = MushroomBody(cfg, 2).save(tmp_path / "brain.npz")
    with pytest.raises(BrainFileMismatch):
        MushroomBody(cfg, 3).load(path)  # different projection seed
    with pytest.raises(BrainFileMismatch):
        MushroomBody(replace(cfg, n_kc=1000), 2).load(path)


def test_learning_off_still_biases_from_loaded_weights(tmp_path):
    cfg = Config()
    mb = MushroomBody(cfg, 0)
    mb.observe(frame(1))
    mb.w_actor[POOL_NAMES.index("A"), mb.active] = 0.05
    path = mb.save(tmp_path / "brain.npz")

    fresh = MushroomBody(cfg, 0)
    fresh.load(path)
    fresh.learning = False
    fresh.observe(frame(1))
    assert fresh.pool_currents()[POOL_NAMES.index("A")] > 0.0


def test_learning_costs_under_a_third_of_a_millisecond():
    from flybrain.loop import measure_learning_ms

    cost = measure_learning_ms(steps=1500)
    assert cost < 0.30, f"the mushroom body costs {cost:.3f} ms/tick"
