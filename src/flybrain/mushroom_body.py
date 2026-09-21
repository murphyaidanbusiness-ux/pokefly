"""The learned circuit: a mushroom body sitting on top of the fixed spiking net.

```
static 16x16 luminance (256)
    -> Kenyon cells (sparse random expansion, `kc_claws` claws each, top-k)
    -> 7 MBONs, one per motor pool   -> an extra current into that pool
    -> 1 value readout               -> the TD error that gates plasticity
```

Only the KC->MBON and KC->value synapses learn. The connectome underneath is
untouched: it stays reflexes plus exploration noise, and the mushroom body is a
learned, place-dependent bias on top of it. The final button still comes out of
the spiking pools through `MotorBridge`, so a learned preference has to win
against the reflex rather than replace it.

The policy gets no RAM. In Pokemon the player is always screen-centred, so the
static frame is an egocentric view of the map and identifies place on its own.
RAM is used for reward and nothing else.

Plasticity is three-factor, which is what the real circuit does: a KC was
active, an MBON's pool was chosen, and dopamine says whether that was better or
worse than expected. The first two are held in eligibility traces; the third is
the TD error, which arrives a few ticks later and multiplies whatever is still
in the trace.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from .config import POOL_NAMES, Config

# Bumped when the on-disk layout changes.
FILE_VERSION = 1


class BrainFileMismatch(ValueError):
    """A saved brain whose expansion layer is not the one being loaded into."""


class MushroomBody:
    def __init__(self, cfg: Config, seed: int | None = None) -> None:
        self.cfg = cfg
        self.seed = cfg.seed if seed is None else seed
        rng = np.random.default_rng(self.seed + 7)

        self.n_input = cfg.retina_size * cfg.retina_size
        self.n_kc = cfg.n_kc
        self.n_active = cfg.n_kc_active
        self.n_pools = len(POOL_NAMES)

        # The random expansion. Each KC samples `kc_claws` pixels with random
        # signed weights; stored as index arrays, so the "matmul" is a gather
        # of n_kc * kc_claws values rather than a dense (n_kc, 256) product.
        self.claw_idx = rng.integers(0, self.n_input, size=(self.n_kc, cfg.kc_claws)).astype(np.int32)
        self.claw_w = rng.normal(0.0, 1.0, size=(self.n_kc, cfg.kc_claws)).astype(np.float32)

        self.w_actor = np.zeros((self.n_pools, self.n_kc), dtype=np.float32)
        self.w_critic = np.zeros(self.n_kc, dtype=np.float32)
        self.e_actor = np.zeros_like(self.w_actor)
        self.e_critic = np.zeros_like(self.w_critic)
        self._scratch = np.zeros_like(self.w_actor)  # so the update allocates nothing

        self.learning = True
        self.active = np.zeros(0, dtype=np.int64)  # indices of the active KCs
        self.mbon = np.zeros(self.n_pools, dtype=np.float32)
        self.value = 0.0
        self.dopamine = 0.0
        self._prev_value = 0.0
        self._primed = False  # no TD error until there is a previous state

        # Training counters, saved with the weights.
        self.episodes_trained = 0
        self.ticks_trained = 0

    # -- sensing -----------------------------------------------------------

    def kenyon_cells(self, retina: np.ndarray) -> np.ndarray:
        """Indices of the active KCs for one 16x16 luminance frame.

        The frame mean is subtracted first, so a screen that is uniformly
        bright and one that is uniformly dark do not give different codes:
        the code is about the pattern, not the backlight.
        """
        flat = retina.reshape(-1).astype(np.float32, copy=False)
        flat = flat - flat.mean()
        drive = np.einsum("kc,kc->k", self.claw_w, flat[self.claw_idx])
        # APL-style global inhibition: keep only the strongest `n_active`.
        return np.argpartition(drive, self.n_kc - self.n_active)[self.n_kc - self.n_active :]

    def observe(self, retina: np.ndarray) -> None:
        """Take one frame: new KC code, new MBON outputs, new value estimate."""
        self.active = self.kenyon_cells(retina)
        self.mbon = self.w_actor[:, self.active].sum(axis=1)
        self._prev_value = self.value
        self.value = float(self.w_critic[self.active].sum())

    def pool_currents(self) -> np.ndarray:
        """(7,) signed currents, one per motor pool, in POOL_NAMES order.

        Squashed, so however strong a learned preference gets it can only tilt
        a pool and never pin it: the pool still has to win against the reflex
        and the network noise. Signed is deliberate; real MBONs come in
        approach and avoidance types.
        """
        return (self.cfg.mbon_gain * np.tanh(self.mbon / self.cfg.mbon_scale)).astype(np.float32)

    # -- plasticity --------------------------------------------------------

    def learn(self, reward: float) -> float:
        """One dopamine release. Returns the TD error.

        `delta = r + gamma * V(s') - V(s)`, where s' is the state just handed
        to `observe` and s is the one before it. The traces still hold what
        happened in s, so this is the three-factor product.
        """
        if not self._primed:
            self._primed = True
            self.dopamine = 0.0
            return 0.0
        delta = float(reward) / self.cfg.reward_scale + self.cfg.gamma * self.value - self._prev_value
        self.dopamine = delta
        if self.learning and delta != 0.0:
            cfg = self.cfg
            np.multiply(self.e_actor, cfg.lr_actor * delta, out=self._scratch)
            np.add(self.w_actor, self._scratch, out=self.w_actor)
            self.w_critic += (cfg.lr_critic * delta) * self.e_critic
            np.clip(self.w_actor, -cfg.w_actor_clip, cfg.w_actor_clip, out=self.w_actor)
            np.clip(self.w_critic, -cfg.w_critic_clip, cfg.w_critic_clip, out=self.w_critic)
        return delta

    def decay_traces(self) -> None:
        self.e_actor *= self.cfg.lambda_actor
        self.e_critic *= self.cfg.lambda_critic

    def credit(self, pools: list[str] | tuple[str, ...]) -> None:
        """Write actor eligibility for the buttons that STARTED this tick.

        The chosen pool gets +1 on every active KC and the other six get -1/6,
        so an update is a preference shift between the pools rather than a
        global change in how loudly the mushroom body shouts. Panic-burst
        presses never get here: the fly did not choose those.
        """
        if not pools:
            return
        share = 1.0 / (self.n_pools - 1)
        for name in pools:
            index = POOL_NAMES.index(name)
            self.e_actor[:, self.active] -= share
            self.e_actor[index, self.active] += 1.0 + share

    def credit_critic(self) -> None:
        self.e_critic[self.active] += 1.0

    # -- episodes ----------------------------------------------------------

    def reset_traces(self) -> None:
        """Between episodes: the traces go, the weights stay."""
        self.e_actor.fill(0.0)
        self.e_critic.fill(0.0)
        self.value = 0.0
        self._prev_value = 0.0
        self.dopamine = 0.0
        self._primed = False
        self.active = np.zeros(0, dtype=np.int64)
        self.mbon = np.zeros(self.n_pools, dtype=np.float32)

    # -- disk --------------------------------------------------------------

    def fingerprint(self) -> np.ndarray:
        """What has to match for saved weights to mean anything here."""
        return np.array(
            [FILE_VERSION, self.seed, self.n_kc, self.cfg.kc_claws, self.n_active, self.n_input, self.n_pools],
            dtype=np.int64,
        )

    def save(self, path: str | Path) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        np.savez(
            target,
            fingerprint=self.fingerprint(),
            w_actor=self.w_actor,
            w_critic=self.w_critic,
            episodes_trained=np.int64(self.episodes_trained),
            ticks_trained=np.int64(self.ticks_trained),
        )
        return target

    def load(self, path: str | Path) -> None:
        with np.load(Path(path)) as data:
            saved = np.asarray(data["fingerprint"], dtype=np.int64)
            mine = self.fingerprint()
            if saved.shape != mine.shape or not np.array_equal(saved, mine):
                raise BrainFileMismatch(
                    f"{path} was built for a different expansion layer: "
                    f"saved {saved.tolist()} vs this one {mine.tolist()} "
                    "(version, seed, n_kc, kc_claws, n_active, n_input, n_pools)"
                )
            self.w_actor = np.ascontiguousarray(data["w_actor"], dtype=np.float32)
            self.w_critic = np.ascontiguousarray(data["w_critic"], dtype=np.float32)
            self.episodes_trained = int(data["episodes_trained"])
            self.ticks_trained = int(data["ticks_trained"])
        self.e_actor = np.zeros_like(self.w_actor)
        self.e_critic = np.zeros_like(self.w_critic)
        self._scratch = np.zeros_like(self.w_actor)

    @property
    def weight_norms(self) -> tuple[float, float]:
        return float(np.abs(self.w_actor).mean()), float(np.abs(self.w_critic).mean())
