"""A two-context world with no emulator in it.

Two static frames, A and B, shown for a few hundred ticks at a time in a random
order. Pressing LEFT under A pays +1 on the next tick; pressing RIGHT under B
pays +1; the opposite press pays nothing, and so does everything else.

The frames are built to be exactly balanced left/right and top/bottom, so the
fixed retinotopic pathway in the connectome has no reason to prefer either
direction under either frame. That is what makes the untrained control land
near 0.5 and what makes a trained result mean something.

The whole chain runs here: optic lobe, mushroom body, spiking brain, motor
bridge. Nothing is shortcut. If the fly learns in this world, the learning rule
works through the real circuit.
"""

from __future__ import annotations

from collections import Counter

import numpy as np

from flybrain.brain import Brain
from flybrain.connectome import synthetic
from flybrain.motor import MotorBridge
from flybrain.mushroom_body import MushroomBody
from flybrain.optic_lobe import OpticLobe

HEIGHT, WIDTH = 144, 160
DARK, BRIGHT = 40, 220


class Sink:
    """The fly presses into the void."""

    def press(self, button): ...
    def release(self, button): ...


def balanced_frame(seed: int, size: int = 16) -> np.ndarray:
    """A 144x160 frame whose 16x16 downsample is mirror-symmetric in both axes.

    The quadrant is random, so two seeds give two very different patterns, but
    every one of them has the same total luminance in its left and right halves
    and in its top and bottom halves.
    """
    half = size // 2
    rng = np.random.default_rng(seed)
    quadrant = np.where(rng.random((half, half)) < 0.5, DARK, BRIGHT).astype(np.uint8)
    top = np.concatenate([quadrant, np.fliplr(quadrant)], axis=1)
    pattern = np.concatenate([top, np.flipud(top)], axis=0)
    # 16 * 9 = 144 rows and 16 * 10 = 160 columns, so INTER_AREA recovers the
    # pattern exactly and the retina sees what was drawn.
    return np.repeat(np.repeat(pattern, HEIGHT // size, axis=0), WIDTH // size, axis=1)


FRAMES = (balanced_frame(11), balanced_frame(22))
WANTED = ("LEFT", "RIGHT")  # the paying button under frame A and under frame B


def run(cfg, mushroom: MushroomBody, seed: int, ticks: int, *, learning: bool, dwell: int = 300):
    """Drive the whole chain for `ticks`. Returns per-context press counters."""
    conn = synthetic(n=cfg.n_neurons, k=cfg.lattice_k, rewire_p=cfg.rewire_p, seed=cfg.seed, cfg=cfg)
    lobe, brain = OpticLobe(cfg), Brain(conn, cfg)
    motor = MotorBridge(conn, cfg, Sink())
    mushroom.learning = learning
    mushroom.reset_traces()

    rng = np.random.default_rng(seed)
    counts = (Counter(), Counter())
    context = int(rng.integers(0, 2))
    pending = 0.0
    for tick in range(ticks):
        if tick and tick % dwell == 0:
            context = int(rng.integers(0, 2))
            lobe.reset()  # a context switch is a cut, not motion

        current = lobe.step(FRAMES[context])
        pulse = motor.take_pulse()
        if pulse:
            current = current + pulse

        reward, pending = pending, 0.0
        mushroom.observe(lobe.retina)
        mushroom.learn(reward)
        mushroom.decay_traces()

        spikes = brain.step(current, mushroom.pool_currents())
        motor.update(spikes, None)
        mushroom.credit(motor.chosen)
        mushroom.credit_critic()

        for pool in motor.chosen:
            counts[context][pool] += 1
            if pool == WANTED[context]:
                pending += 1.0
    return counts


def share(counter: Counter, wanted: str, other: str) -> float:
    total = counter[wanted] + counter[other]
    return counter[wanted] / total if total else 0.0
