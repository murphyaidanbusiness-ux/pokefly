"""End to end through optic lobe -> brain -> motor: does the fly's button
pressing carry any information, and does it stop short of mashing?

These are the two things the pool accumulators alone cannot tell you. They run
the whole chain with a fake button sink and no emulator.
"""

import numpy as np
import pytest
from conftest import moving_blocks, pixel_noise, roaming_block

from flybrain.brain import Brain
from flybrain.config import POOL_NAMES, Config
from flybrain.connectome import synthetic
from flybrain.motor import MotorBridge
from flybrain.optic_lobe import OpticLobe

SEEDS = (0, 1, 2)


class Sink:
    """The fly presses into the void."""

    def press(self, button): ...
    def release(self, button): ...


def drive(cfg, frames, position):
    conn = synthetic(n=cfg.n_neurons, k=cfg.lattice_k, rewire_p=cfg.rewire_p, seed=cfg.seed, cfg=cfg)
    lobe, brain = OpticLobe(cfg), Brain(conn, cfg)
    motor = MotorBridge(conn, cfg, Sink())
    for frame in frames:
        motor.update(brain.step(lobe.step(frame)), position)
    return motor


def config(seed):
    return Config(seed=seed)


@pytest.mark.parametrize("seed", SEEDS)
def test_no_button_runs_at_more_than_40_percent_of_its_ceiling(seed):
    """A button can physically fire once per hold plus cooldown. Sitting at
    that ceiling means the cooldown timer is playing the game and the brain is
    deciding nothing, which is what the absolute-threshold motor layer did."""
    cfg = config(seed)
    ticks = 3000
    ceiling = ticks / (cfg.hold_frames + cfg.cooldown_ticks)
    rng = np.random.default_rng(seed)
    frames = list(pixel_noise(rng, ticks // 2)) + list(moving_blocks(rng, ticks - ticks // 2))
    motor = drive(cfg, frames, (1, 2, 3))
    for name in POOL_NAMES:
        share = motor.fire_counts[name] / ceiling
        assert share <= 0.40, f"{name} fired {motor.fire_counts[name]} times, {share:.0%} of the ceiling"
        assert motor.fire_counts[name] > 0, f"{name} never fired"


@pytest.mark.parametrize(
    ("region", "expected", "opposite"),
    [
        ("left", "LEFT", "RIGHT"),
        ("right", "RIGHT", "LEFT"),
        ("top", "UP", "DOWN"),
        ("bottom", "DOWN", "UP"),
    ],
)
def test_motion_in_one_region_biases_the_matching_pool(region, expected, opposite):
    """A bright block wandering inside one third of the screen has to move the
    fly's button statistics toward the pool that region wires to. Summed over
    three seeds because a single 1500-tick run is noisy; the 1.5x is not
    negotiable."""
    wins = losses = 0
    for seed in SEEDS:
        cfg = config(seed)
        frames = roaming_block(np.random.default_rng(seed + 100), 1500, region)
        motor = drive(cfg, frames, None)
        wins += motor.fire_counts[expected]
        losses += motor.fire_counts[opposite]
    assert losses > 0, "the opposite pool never fired at all, which is a dead pool, not selectivity"
    ratio = wins / losses
    assert ratio >= 1.5, f"{region} motion gave {expected}={wins} vs {opposite}={losses}, only {ratio:.2f}x"


def test_start_is_rarer_than_the_other_buttons():
    """START reopens the menu, so a grooming bout should be an occasional
    thing. Its threshold scale is the highest in the config."""
    cfg = config(0)
    rng = np.random.default_rng(0)
    motor = drive(cfg, moving_blocks(rng, 3000), (1, 2, 3))
    others = [motor.fire_counts[n] for n in POOL_NAMES if n != "START"]
    assert motor.fire_counts["START"] > 0
    assert motor.fire_counts["START"] < min(others)
    assert motor.fire_counts["B"] < motor.fire_counts["A"]
