"""The test that says the learning rule is real.

Everything else here checks a part. This one runs the whole chain in the
two-context world of `fake_world.py` and asks whether the fly ends up pressing
the button that pays, in the context where it pays, with learning switched off
afterwards so nothing is being carried by a live dopamine signal.

The 0.70 is the contract's number and is not negotiable.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import replace

import fake_world as world
import numpy as np

from flybrain.config import Config
from flybrain.mushroom_body import MushroomBody

SEEDS = (0, 1, 2)
TRAIN_TICKS = 8_000
EVAL_TICKS = 3_000


def config(seed: int) -> Config:
    return replace(Config(), seed=seed, n_neurons=1200)


def totals(train_ticks: int) -> tuple[Counter, Counter]:
    """Train each seed, then measure with learning off. Counts sum over seeds."""
    summed = (Counter(), Counter())
    for seed in SEEDS:
        cfg = config(seed)
        mushroom = MushroomBody(cfg, seed)
        if train_ticks:
            world.run(cfg, mushroom, seed=seed + 500, ticks=train_ticks, learning=True)
        counts = world.run(cfg, mushroom, seed=seed + 900, ticks=EVAL_TICKS, learning=False)
        for context in (0, 1):
            summed[context].update(counts[context])
    return summed


def test_the_fly_learns_which_button_pays_in_which_context():
    summed = totals(TRAIN_TICKS)
    left = world.share(summed[0], "LEFT", "RIGHT")
    right = world.share(summed[1], "RIGHT", "LEFT")
    assert summed[0]["LEFT"] + summed[0]["RIGHT"] > 50, "almost no directional presses to judge"
    assert summed[1]["LEFT"] + summed[1]["RIGHT"] > 50
    assert left >= 0.70, f"under frame A, LEFT share {left:.2f} of {dict(summed[0])}"
    assert right >= 0.70, f"under frame B, RIGHT share {right:.2f} of {dict(summed[1])}"


def test_the_untrained_control_is_near_half():
    """Same world, no training. If this were already biased the test above
    would be measuring the connectome's draw and not the learning."""
    summed = totals(0)
    left = world.share(summed[0], "LEFT", "RIGHT")
    right = world.share(summed[1], "RIGHT", "LEFT")
    assert 0.35 <= left <= 0.65, f"untrained LEFT share under A is {left:.2f}"
    assert 0.35 <= right <= 0.65, f"untrained RIGHT share under B is {right:.2f}"


def test_the_critic_is_higher_where_the_reward_is():
    """A third context that never pays must end up valued below the two that
    do. The critic is what the actor's dopamine is measured against, so if this
    fails the actor is learning from a broken baseline."""
    values = {"A": [], "B": [], "never": []}
    never = world.balanced_frame(33)
    for seed in SEEDS:
        cfg = config(seed)
        mushroom = MushroomBody(cfg, seed)
        world.run(cfg, mushroom, seed=seed + 500, ticks=TRAIN_TICKS, learning=True)
        mushroom.learning = False
        for name, frame in (("A", world.FRAMES[0]), ("B", world.FRAMES[1]), ("never", never)):
            lobe_frame = frame[:: frame.shape[0] // 16, :: frame.shape[1] // 16].astype(np.float32) / 255.0
            mushroom.observe(lobe_frame)
            values[name].append(mushroom.value)
    rewarded = np.mean(values["A"] + values["B"])
    unrewarded = np.mean(values["never"])
    assert rewarded > unrewarded, f"rewarded contexts {rewarded:.3f} vs never-rewarded {unrewarded:.3f}"


def test_panic_presses_write_no_eligibility():
    """A panic burst is a reflex. Crediting it would teach the fly whatever the
    random draw happened to be."""
    cfg = config(0)
    mushroom = MushroomBody(cfg, 0)
    mushroom.observe(np.zeros((cfg.retina_size, cfg.retina_size), dtype=np.float32))

    from flybrain.connectome import synthetic
    from flybrain.motor import MotorBridge

    conn = synthetic(n=cfg.n_neurons, seed=0, cfg=cfg)
    motor = MotorBridge(conn, cfg, world.Sink())
    quiet = np.zeros(conn.n, dtype=bool)
    for _ in range(cfg.panic_after):
        motor.update(quiet, (1, 5, 5))
    assert motor.panic_count == 1
    assert motor.panicked and not motor.chosen
    mushroom.credit(motor.chosen)
    assert not np.any(mushroom.e_actor), "a panic press wrote actor eligibility"
