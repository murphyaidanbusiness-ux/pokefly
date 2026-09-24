import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from flybrain.loop import find_rom  # noqa: E402

ROM = find_rom(ROOT / "roms")

HEIGHT, WIDTH = 144, 160


def pixel_noise(rng, n):
    """Per-pixel uniform noise. Nearly flat after the 16x16 area downsample, so
    this mostly exercises the tonic and dark-current path."""
    for _ in range(n):
        yield rng.integers(0, 256, size=(HEIGHT, WIDTH), dtype=np.uint8)


def moving_blocks(rng, n):
    """Coarse random blocks, 16x16 image pixels each. These survive the
    downsample, so this is the condition that actually drives the ON/OFF
    motion channels."""
    for _ in range(n):
        small = rng.integers(0, 256, size=(9, 10), dtype=np.uint8)
        yield np.repeat(np.repeat(small, 16, axis=0), 16, axis=1)


def roaming_block(rng, n, region, size=46):
    """One bright block wandering inside one third of an otherwise dark
    screen. `region` is "left", "right", "top" or "bottom"."""
    if region in ("left", "right"):
        x0, x1 = (0, WIDTH // 3) if region == "left" else (WIDTH - WIDTH // 3, WIDTH)
        y0, y1 = 0, HEIGHT
    else:
        y0, y1 = (0, HEIGHT // 3) if region == "top" else (HEIGHT - HEIGHT // 3, HEIGHT)
        x0, x1 = 0, WIDTH
    px, py = (x0 + x1 - size) // 2, (y0 + y1 - size) // 2
    for _ in range(n):
        px = int(np.clip(px + rng.integers(-7, 8), x0, max(x0, x1 - size)))
        py = int(np.clip(py + rng.integers(-7, 8), y0, max(y0, y1 - size)))
        frame = np.full((HEIGHT, WIDTH), 16, dtype=np.uint8)
        frame[py : py + size, px : px + size] = 240
        yield frame
