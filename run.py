"""Entrypoint. `python run.py` with no arguments finds the ROM next to itself.

It also picks up `brains/latest.npz` when that exists, so the fly you watch is
the trained one unless you ask for `--naive`.

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
from flybrain.hud import Hud, PlainLog  # noqa: E402
from flybrain.loop import LoopOptions, run_loop  # noqa: E402


def parse_args(argv: list[str] | None = None) -> tuple[Config, LoopOptions]:
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
    parser.add_argument("--brain", type=Path, default=None, help="a saved mushroom body (default brains/latest.npz)")
    parser.add_argument("--naive", action="store_true", help="ignore any saved brain: the untrained fly")
    parser.add_argument("--learn", action="store_true", help="keep learning while you watch")
    parser.add_argument("--save-brain", action="store_true", help="with --learn, write the brain back on exit")
    parser.add_argument(
        "--start-state", action="store_true", help="start from states/bedroom.state instead of a cold boot"
    )
    args = parser.parse_args(argv)

    load_state = args.load_state
    if args.start_state and load_state is None:
        load_state = ROOT / "states" / "bedroom.state"

    cfg = replace(
        Config(),
        rom_path=args.rom,
        n_neurons=args.neurons,
        seed=args.seed,
        uncapped=args.uncapped,
        headless=args.headless,
        hud=not args.no_hud,
        max_steps=args.max_steps,
        connectome_csv=args.connectome,
        load_state=load_state,
        save_state=args.save_state,
    )

    if args.naive:
        brain_path = None
    elif args.brain is not None:
        brain_path = Path(args.brain)
        if not brain_path.is_file():
            parser.error(f"no brain file at {brain_path}")
    else:
        default = ROOT / "brains" / "latest.npz"
        brain_path = default if default.is_file() else None
    options = LoopOptions(brain_path=brain_path, learn=args.learn, save_brain=args.save_brain)
    return cfg, options


def main() -> None:
    cfg, options = parse_args()
    display = Hud(cfg) if cfg.hud else PlainLog(cfg)
    run_loop(cfg, observers=(display,), options=options)


if __name__ == "__main__":
    main()
