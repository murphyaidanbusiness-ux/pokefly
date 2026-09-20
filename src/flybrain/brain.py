"""Leaky integrate-and-fire network. One brain step per emulator tick.

Per step, for every neuron at once:

    v += leak * (v_rest - v) + W @ spikes_prev + input
    spike where v >= v_thresh and the refractory counter has expired
    spiking neurons reset to v_reset and start their refractory countdown

The recurrent term is a gather-and-sum over the columns of W belonging to the
neurons that spiked on the previous step, not a full matmul: spiking is sparse
(a few percent), so this is far cheaper. W is held in Fortran order so those
columns are contiguous.
"""

from __future__ import annotations

import numpy as np

from .config import Config
from .connectome import Connectome


class Brain:
    def __init__(self, connectome: Connectome, cfg: Config) -> None:
        self.cfg = cfg
        self.conn = connectome
        self.n = connectome.n
        self.weights = np.asfortranarray(connectome.weights.astype(np.float32))
        self.sensory_idx = connectome.sensory_idx
        self.v = np.full(self.n, cfg.v_rest, dtype=np.float32)
        self.refractory = np.zeros(self.n, dtype=np.int32)
        self.spikes = np.zeros(self.n, dtype=bool)
        self._input = np.zeros(self.n, dtype=np.float32)
        self._rate = 0.0
        self.steps = 0
        # A connectome loaded from an edge list can have a different number of
        # sensory neurons than the optic lobe has channels. Channels are folded
        # onto the sensory neurons round-robin; the synthetic net is an exact
        # match and skips this entirely.
        self._fold = np.arange(cfg.n_sensory) % self.sensory_idx.size

    @property
    def firing_rate(self) -> float:
        """Exponentially smoothed fraction of neurons spiking per step."""
        return self._rate

    def pool_counts(self) -> np.ndarray:
        """(7,) int: spikes this step in each motor pool, in POOL_NAMES order."""
        return self.spikes[self.conn.pool_matrix()].sum(axis=1)

    def step(self, sensory_current: np.ndarray) -> np.ndarray:
        cfg = self.cfg
        spiking = np.flatnonzero(self.spikes)
        self._input.fill(0.0)
        if sensory_current.size == self.sensory_idx.size:
            self._input[self.sensory_idx] = sensory_current
        else:
            fold = self._fold if sensory_current.size == self._fold.size else (
                np.arange(sensory_current.size) % self.sensory_idx.size
            )
            self._input[self.sensory_idx] = np.bincount(
                fold, weights=sensory_current, minlength=self.sensory_idx.size
            ).astype(np.float32)
        if spiking.size:
            self._input += self.weights[:, spiking].sum(axis=1)

        self.v += cfg.leak * (cfg.v_rest - self.v) + self._input
        resting = self.refractory > 0
        self.v[resting] = cfg.v_reset
        np.subtract(self.refractory, 1, out=self.refractory, where=resting)

        spikes = self.v >= cfg.v_thresh
        self.v[spikes] = cfg.v_reset
        self.refractory[spikes] = cfg.refractory
        self.spikes = spikes

        instant = float(spikes.mean())
        self._rate += cfg.rate_smoothing * (instant - self._rate)
        self.steps += 1
        return spikes
