"""Thin PyBoy wrapper. Nothing else in the package imports pyboy.

Verified against pyboy 2.7.0: `PyBoy(rom, window=..., sound_emulated=False)`,
`tick(count, render)` returning False once the window is closed,
`screen.ndarray` as (144, 160, 4) RGBA, `button_press`/`button_release` taking
lowercase names, `memory[addr]`, `set_emulation_speed(0)`, `stop(save=False)`,
and `save_state`/`load_state` taking file-like objects.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from pyboy import PyBoy

from .config import Config


class Emulator:
    def __init__(self, rom_path: str | Path, headless: bool = False, uncapped: bool = False, cfg: Config | None = None):
        self.cfg = cfg or Config()
        self.rom_path = Path(rom_path)
        self.pyboy = PyBoy(
            str(self.rom_path),
            window="null" if headless else "SDL2",
            sound_emulated=False,
        )
        if uncapped:
            self.pyboy.set_emulation_speed(0)
        self._closed = False

    # -- stepping ----------------------------------------------------------

    def tick(self) -> bool:
        """One frame. False means the window was closed and the loop should exit."""
        return bool(self.pyboy.tick(1, True))

    def frame(self) -> np.ndarray:
        """(144, 160) uint8 grayscale. PyBoy hands back RGBA; the Game Boy
        palette is gray, so the red channel alone is the luminance."""
        return np.ascontiguousarray(self.pyboy.screen.ndarray[:, :, 0])

    # -- input -------------------------------------------------------------

    def press(self, button: str) -> None:
        self.pyboy.button_press(button)

    def release(self, button: str) -> None:
        self.pyboy.button_release(button)

    # -- game state --------------------------------------------------------

    def position(self) -> tuple[int, int, int]:
        memory = self.pyboy.memory
        return (
            int(memory[self.cfg.map_id_addr]),
            int(memory[self.cfg.player_x_addr]),
            int(memory[self.cfg.player_y_addr]),
        )

    @property
    def in_battle(self) -> bool:
        return bool(self.pyboy.memory[self.cfg.in_battle_addr])

    # -- savestates --------------------------------------------------------

    def load_state(self, path: str | Path) -> None:
        with Path(path).open("rb") as handle:
            self.pyboy.load_state(handle)

    def save_state(self, path: str | Path) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("wb") as handle:
            self.pyboy.save_state(handle)

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self.pyboy.stop(save=False)
