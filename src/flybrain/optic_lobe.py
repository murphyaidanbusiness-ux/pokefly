"""Frame -> sensory currents, in the shape of a fly's first optic neuropil.

The 160x144 Game Boy frame is area-averaged down to a 16x16 retina. Each
step takes the luminance delta against the previous retina and splits it into
an ON channel (brightening, L1-like) and an OFF channel (darkening, L2-like),
so 256 + 256 = 512 sensory channels. On top of the motion signal sits a small
tonic term proportional to absolute luminance, so a still dialogue box waiting
for A still drives the network, a constant dark current so the game's many
black screens do not blind the fly outright, and low seeded Gaussian noise so
nothing ever goes completely silent.
"""

from __future__ import annotations

import cv2
import numpy as np

from .config import Config


def region_masks(size: int) -> dict[str, np.ndarray]:
    """Index arrays into the 2*size*size sensory vector, one per visual region.

    The retinotopic bias pathways in `connectome.py` are built from these, so
    the mapping from screen position to channel index is defined in exactly one
    place. Both the ON block (0 .. size*size-1) and the OFF block
    (size*size .. 2*size*size-1) are included in every region.
    """
    rows, cols = np.meshgrid(np.arange(size), np.arange(size), indexing="ij")
    flat_rows, flat_cols = rows.ravel(), cols.ravel()
    half = size // 2
    quarter = size // 4

    def both(pixel_mask: np.ndarray) -> np.ndarray:
        idx = np.flatnonzero(pixel_mask)
        return np.concatenate([idx, idx + size * size]).astype(np.int64)

    centre = (
        (flat_rows >= quarter)
        & (flat_rows < size - quarter)
        & (flat_cols >= quarter)
        & (flat_cols < size - quarter)
    )
    return {
        "left": both(flat_cols < half),
        "right": both(flat_cols >= half),
        "top": both(flat_rows < half),
        "bottom": both(flat_rows >= half),
        "centre": both(centre),
    }


class OpticLobe:
    """Stateful: it holds the previous retina so it can take a delta."""

    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.size = cfg.retina_size
        self.n_channels = 2 * self.size * self.size
        self.rng = np.random.default_rng(cfg.seed + 1)
        self._prev: np.ndarray | None = None
        self._retina = np.zeros((self.size, self.size), dtype=np.float32)

    @property
    def retina(self) -> np.ndarray:
        """The downsampled luminance frame this step, (size, size) float32 in
        [0,1]. The mushroom body reads it from here rather than downsampling
        the frame a second time: one `cv2.resize` per tick, one definition of
        what the fly sees."""
        return self._retina

    def reset(self) -> None:
        """Forget the previous frame, so the next one is a first frame again."""
        self._prev = None

    def step(self, frame: np.ndarray) -> np.ndarray:
        """frame: (144,160) uint8 grayscale. Returns (512,) float32 currents."""
        small = cv2.resize(
            frame, (self.size, self.size), interpolation=cv2.INTER_AREA
        ).astype(np.float32) / 255.0
        if self._prev is None:
            delta = np.zeros_like(small)  # first frame: no motion, not a whole-frame edge
        else:
            delta = small - self._prev
        self._prev = small
        self._retina = small

        on = np.maximum(delta, 0.0).ravel()
        off = np.maximum(-delta, 0.0).ravel()
        tonic = self.cfg.dark_current + self.cfg.tonic_gain * small.ravel()

        current = np.concatenate(
            [self.cfg.motion_gain * on + tonic, self.cfg.motion_gain * off + tonic]
        )
        current += self.rng.normal(0.0, self.cfg.noise_sigma, current.shape)
        # Synaptic saturation, symmetric so the noise stays zero-mean.
        np.clip(current, -self.cfg.max_current, self.cfg.max_current, out=current)
        return current.astype(np.float32)
