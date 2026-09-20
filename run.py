"""Entrypoint. `python run.py` with no arguments finds the ROM next to itself.

No install step: src/ goes on sys.path here.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from flybrain.config import Config  # noqa: E402
from flybrain.loop import run_loop  # noqa: E402


def parse_args(argv: list[str] | None = None) -> Config:
    parser = argparse.ArgumentParser(description="A simulated fly brain plays Pokemon Red.")
    parser.add_argument("--rom", type=Path, default=ROOT / "roms" / "pokemon_red.gb")
    parser.add_argument("--neurons", type=int, default=2000, help="1000 to 5000")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--uncapped", action="store_true", help="run as fast as the CPU allows")
    parser.add_argument("--headless", action="store_true", help="no SDL2 window")
    parser.add_argument("--no-hud", action="store_true", help="one log line per second instead")
    parser.add_argument("--max-steps", type=int, default=0, help="0 = run until the window closes")
    parser.add_argument("--connectome", type=Path, default=None, help="edge-list CSV: pre,post,weight[,sign]")
    parser.add_argument("--load-state", type=Path, default=None)
    parser.add_argument("--save-state", type=Path, default=None)
    args = parser.parse_args(argv)

    return replace(
        Config(),
        rom_path=args.rom,
        n_neurons=args.neurons,
        seed=args.seed,
        uncapped=args.uncapped,
        headless=args.headless,
        hud=not args.no_hud,
        max_steps=args.max_steps,
        connectome_csv=args.connectome,
        load_state=args.load_state,
        save_state=args.save_state,
    )


def main() -> None:
    run_loop(parse_args())


if __name__ == "__main__":
    main()
