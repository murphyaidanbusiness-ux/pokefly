"""The wiring diagram: a synthetic small-world net, or a real edge list.

Index layout (the rest of the package relies on it):

    0 .. 511                    sensory neurons, one per optic-lobe channel
    512 .. n-7*pool_size-1      hidden interneurons
    n-7*pool_size .. n-1        the seven motor pools, 24 neurons each, in the
                                order UP, DOWN, LEFT, RIGHT, A, B, START

Pool names are flavour from the real fly descending-neuron classes: UP is
forward walking (DNp09), DOWN is backward walking (MDN, the moonwalker), LEFT
and RIGHT are the turning pair (DNa02), A is the interact / proboscis reach
(DNg), B is withdraw, START is a grooming pause.

Dale's law is enforced: every outgoing synapse of a neuron has one sign.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .config import POOL_NAMES, Config
from .optic_lobe import region_masks

# Which visual region drives which pool. Flies turn toward small moving objects,
# so motion on the left drives the left-turn pool.
_REGION_TO_POOL = {"left": "LEFT", "right": "RIGHT", "top": "UP", "bottom": "DOWN", "centre": "A"}

# Opposing pools, so the fly commits to a direction instead of dithering.
_OPPOSING = (("UP", "DOWN"), ("DOWN", "UP"), ("LEFT", "RIGHT"), ("RIGHT", "LEFT"))


@dataclass
class Connectome:
    weights: np.ndarray  # (n, n) float32, row = postsynaptic, col = presynaptic
    sensory_idx: np.ndarray  # (512,) int64
    motor_pools: dict[str, np.ndarray]  # pool name -> (pool_size,) int64
    n: int

    @property
    def motor_idx(self) -> np.ndarray:
        return np.concatenate([self.motor_pools[name] for name in POOL_NAMES])

    def pool_matrix(self) -> np.ndarray:
        """(7, pool_size) int64: pool membership as one array, for fast counting."""
        return np.stack([self.motor_pools[name] for name in POOL_NAMES])


def _ring_lattice_edges(n: int, k: int, rewire_p: float, rng: np.random.Generator) -> tuple[np.ndarray, np.ndarray]:
    """Directed Watts-Strogatz edges, vectorized. Returns (pre, post)."""
    half = k // 2
    offsets = np.concatenate([np.arange(1, half + 1), -np.arange(1, half + 1)])
    pre = np.repeat(np.arange(n, dtype=np.int64), offsets.size)
    post = (pre + np.tile(offsets, n)) % n

    rewire = rng.random(post.size) < rewire_p
    post = post.copy()
    post[rewire] = rng.integers(0, n, int(rewire.sum()))

    keep = pre != post  # no self loops
    pre, post = pre[keep], post[keep]

    # Collapse duplicate edges created by rewiring.
    key = pre * n + post
    _, first = np.unique(key, return_index=True)
    first.sort()

    # Position on the ring -> neuron id. Relabelling leaves the graph a
    # Watts-Strogatz graph (same degree, clustering and path length), but
    # without it the ring is aligned with the functional layout: the sensory
    # block and the motor block are contiguous and both are excitatory by
    # construction, so each becomes a self-exciting clique. Measured before
    # this was added, the UP pool took +2.78 of pure excitation from the other
    # motor neurons and saturated at 20% whatever was on screen.
    order = rng.permutation(n)
    return order[pre[first]], order[post[first]]


def _balance_inhibition(weights: np.ndarray, strength: float) -> None:
    """Inhibitory synaptic scaling: give every neuron the same net incoming
    lattice drive, in place.

    With 20 incoming synapses drawn at random and a 3.5:1 magnitude ratio
    between an inhibitory and an excitatory one, how excitable a neuron is
    comes down mostly to how many inhibitory partners it happened to draw.
    Across a 24-neuron motor pool that lottery does not average out: measured
    without this, a pool's firing rate against its opposite ranged from 0.80 to
    2.20 across seeds, correlating +0.85 to +0.91 with the gap in their
    incoming weight sums, and the crossed inhibition then amplified whichever
    way the dice fell. That intrinsic difference is the same size as the
    difference the retinotopic pathway is supposed to produce, so the fly's
    turning bias was the connectome's draw rather than what was on screen.

    Only the magnitudes of the inhibitory inputs move, never a sign, so Dale's
    law is untouched. `strength` interpolates: 0.0 leaves the raw draw alone.
    """
    if strength <= 0.0:
        return
    excitatory = np.clip(weights, 0.0, None).sum(axis=1)
    inhibitory = np.clip(weights, None, 0.0).sum(axis=1)  # negative
    target = float((excitatory + inhibitory).mean())
    scale = np.ones_like(excitatory)
    adjustable = inhibitory < -1e-9
    scale[adjustable] = np.clip((excitatory[adjustable] - target) / -inhibitory[adjustable], 0.25, 4.0)
    scale = (1.0 + strength * (scale - 1.0)).astype(np.float32)
    for start in range(0, weights.shape[0], 512):  # in blocks, to avoid an (n, n) temporary
        block = weights[start : start + 512]
        negative = np.minimum(block, 0.0)
        block -= negative
        block += negative * scale[start : start + 512, None]


def _assign_signs(n: int, protected: np.ndarray, fraction: float, rng: np.random.Generator) -> np.ndarray:
    """+1 / -1 per neuron. Sensory and motor neurons are forced excitatory so
    their pathways stay interpretable; the inhibitory quota is drawn from the
    hidden population only."""
    signs = np.ones(n, dtype=np.float32)
    free = np.setdiff1d(np.arange(n, dtype=np.int64), protected)
    want = min(int(round(fraction * n)), free.size)
    signs[rng.choice(free, size=want, replace=False)] = -1.0
    return signs


def _add_bias_pathways(
    weights: np.ndarray,
    cfg: Config,
    signs: np.ndarray,
    hidden_exc: np.ndarray,
    pools: dict[str, np.ndarray],
    rng: np.random.Generator,
) -> None:
    """Sensory -> interneuron -> motor pool, one wide-field pathway per region.

    Deliberately not a direct sensory->motor wire: the signal has to propagate
    through the hidden network, so the recurrent state still shapes behaviour.

    Each interneuron pools `bias_fan_in` channels of its region, the way a
    lobula plate tangential cell pools a whole hemifield, and its incoming
    lattice weights are attenuated by `bias_lattice_scale`. Without that
    attenuation the pathway does not work at all: the interneuron needs a total
    input around `leak * v_thresh` to sit near threshold, while its 20 lattice
    synapses fluctuate several times that, so the regional signal is buried and
    every pool responds identically whatever is on screen.
    """
    regions = region_masks(cfg.retina_size)
    picks = rng.choice(hidden_exc, size=(len(_REGION_TO_POOL), cfg.bias_interneurons), replace=False)
    for row, (region, pool) in enumerate(_REGION_TO_POOL.items()):
        scale = cfg.center_bias_scale if region == "centre" else 1.0
        channels = regions[region]
        inter = picks[row]
        weights[inter] *= cfg.bias_lattice_scale
        for neuron in inter:
            fan = rng.choice(channels, size=min(cfg.bias_fan_in, channels.size), replace=False)
            weights[neuron, fan] += cfg.w_bias_in * scale * signs[fan]
        weights[np.ix_(pools[pool], inter)] += cfg.w_bias_out * scale


def _add_crossed_inhibition(
    weights: np.ndarray,
    cfg: Config,
    hidden_inh: np.ndarray,
    pools: dict[str, np.ndarray],
    rng: np.random.Generator,
) -> None:
    """Pool A -> inhibitory interneuron -> pool B, for each opposing pair.

    Routed through a real inhibitory interneuron rather than a negative
    pool-to-pool wire, so the motor pools themselves stay excitatory and Dale's
    law is not bent to get the mutual inhibition.
    """
    picks = rng.choice(hidden_inh, size=(len(_OPPOSING), cfg.cross_inh_neurons), replace=False)
    for row, (source, target) in enumerate(_OPPOSING):
        inter = picks[row]
        weights[np.ix_(inter, pools[source])] += cfg.w_cross_in
        weights[np.ix_(pools[target], inter)] -= cfg.w_cross_out


def synthetic(n: int = 2000, k: int = 20, rewire_p: float = 0.1, seed: int = 0, cfg: Config | None = None) -> Connectome:
    """Directed Watts-Strogatz small world plus the retinotopic and crossed
    pathways. Synapse magnitudes come from `cfg` (a default Config if omitted)."""
    cfg = cfg or Config()
    if not 1000 <= n <= 5000:
        raise ValueError(f"n must be in [1000, 5000], got {n}")
    n_sensory, n_motor = cfg.n_sensory, cfg.n_motor
    if n < n_sensory + n_motor + cfg.bias_interneurons * 8:
        raise ValueError(f"n={n} leaves too few hidden neurons")
    rng = np.random.default_rng(seed)

    sensory_idx = np.arange(n_sensory, dtype=np.int64)
    motor_start = n - n_motor
    pools = {
        name: np.arange(motor_start + i * cfg.pool_size, motor_start + (i + 1) * cfg.pool_size, dtype=np.int64)
        for i, name in enumerate(POOL_NAMES)
    }
    motor_idx = np.arange(motor_start, n, dtype=np.int64)
    hidden = np.arange(n_sensory, motor_start, dtype=np.int64)

    signs = _assign_signs(n, np.concatenate([sensory_idx, motor_idx]), cfg.inhibitory_fraction, rng)
    hidden_exc = hidden[signs[hidden] > 0]
    hidden_inh = hidden[signs[hidden] < 0]

    pre, post = _ring_lattice_edges(n, k, rewire_p, rng)
    magnitude = np.where(signs[pre] > 0, cfg.w_exc, cfg.w_inh)
    weights = np.zeros((n, n), dtype=np.float32)
    weights[post, pre] = magnitude * signs[pre]
    _balance_inhibition(weights, cfg.inhibitory_balance)

    _add_bias_pathways(weights, cfg, signs, hidden_exc, pools, rng)
    _add_crossed_inhibition(weights, cfg, hidden_inh, pools, rng)
    np.fill_diagonal(weights, 0.0)
    return Connectome(weights=weights, sensory_idx=sensory_idx, motor_pools=pools, n=n)


def from_edge_list(csv_path: str | Path, cfg: Config | None = None) -> Connectome:
    """Load a real connectome export: columns `pre,post,weight[,sign]`.

    Heuristics, documented because they are guesses and not measurements:
    ids are remapped to 0..N-1 in first-seen order; the `n_sensory` neurons
    with the lowest in-degree become sensory (they feed the net and receive
    little); the `7*pool_size` neurons with the lowest out-degree become the
    motor pools (they are terminal), split into seven equal pools in that
    order. Dale's law is imposed afterwards by taking each presynaptic
    neuron's sign from the `sign` column if present, else from the sign of the
    mean of its outgoing weights.
    """
    cfg = cfg or Config()
    rows: list[tuple[str, str, float, float]] = []
    with Path(csv_path).open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            sign = float(row["sign"]) if row.get("sign") not in (None, "") else 0.0
            rows.append((row["pre"], row["post"], float(row["weight"]), sign))
    if not rows:
        raise ValueError(f"{csv_path} has no edges")

    ids: dict[str, int] = {}
    for pre_id, post_id, _, _ in rows:
        for node in (pre_id, post_id):
            ids.setdefault(node, len(ids))
    n = len(ids)
    pre = np.array([ids[r[0]] for r in rows], dtype=np.int64)
    post = np.array([ids[r[1]] for r in rows], dtype=np.int64)
    raw = np.array([r[2] for r in rows], dtype=np.float32)
    given = np.array([r[3] for r in rows], dtype=np.float32)

    # One sign per presynaptic neuron: the sign column if it says anything,
    # otherwise the sign of that neuron's summed outgoing weights.
    hint = np.bincount(pre, weights=given, minlength=n)
    fallback = np.bincount(pre, weights=raw, minlength=n)
    signs = np.where(np.where(hint != 0, hint, fallback) < 0, -1.0, 1.0).astype(np.float32)

    weights = np.zeros((n, n), dtype=np.float32)
    weights[post, pre] = np.abs(raw) * signs[pre]
    np.fill_diagonal(weights, 0.0)

    in_degree = np.bincount(post, minlength=n)
    out_degree = np.bincount(pre, minlength=n)
    n_sensory = min(cfg.n_sensory, n // 3)
    n_motor = min(cfg.n_motor, n // 3)
    sensory_idx = np.sort(np.argsort(in_degree, kind="stable")[:n_sensory]).astype(np.int64)
    motor_idx = np.sort(
        np.argsort(np.where(np.isin(np.arange(n), sensory_idx), 1 << 30, out_degree), kind="stable")[:n_motor]
    ).astype(np.int64)
    per_pool = max(1, n_motor // len(POOL_NAMES))
    pools = {name: motor_idx[i * per_pool : (i + 1) * per_pool] for i, name in enumerate(POOL_NAMES)}
    return Connectome(weights=weights, sensory_idx=sensory_idx, motor_pools=pools, n=n)
