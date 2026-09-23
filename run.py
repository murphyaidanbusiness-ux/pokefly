"""Entrypoint. `python run.py` with no arguments finds the ROM next to itself.

It also picks up `brains/latest.npz` when that exists, so the fly you watch is
the trained one unless you ask for `--naive`.

No install step: src/ goes on sys.path here.
"""

from __future__ import annotations

import argparse
import sys
import webbrowser
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from flybrain.config import Config  # noqa: E402
from flybrain.hud import Hud, PlainLog  # noqa: E402
from flybrain.loop import LoopOptions, run_loop  # noqa: E402

BEST_BRAIN = ROOT / "brains" / "latest.npz"
JOURNEY_BRAIN = ROOT / "brains" / "journey.npz"


def brain_save_target(brain: Path | None, best: Path = BEST_BRAIN, journey: Path = JOURNEY_BRAIN) -> Path:
    """Where `--learn --save-brain` writes. Never the best brain: that file is
    only ever replaced by training's evaluation blocks, and a brain that
    learned while you watched has no block score. With no `--brain`, or a
    `--brain` that is the best brain, it goes to `brains/journey.npz`."""
    if brain is None or Path(brain).resolve() == Path(best).resolve():
        return Path(journey)
    return Path(brain)


def parse_args(argv: list[str] | None = None) -> tuple[Config, LoopOptions, argparse.Namespace]:
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
    parser.add_argument(
        "--save-brain",
        action="store_true",
        help="with --learn, write the brain on exit: back to --brain, or brains/journey.npz (never brains/latest.npz)",
    )
    parser.add_argument(
        "--start-state", action="store_true", help="start from states/bedroom.state instead of a cold boot"
    )
    parser.add_argument("--couch", action="store_true", help="open the live 3D couch scene in a browser")
    parser.add_argument("--couch-port", type=int, default=Config().couch_port, help="port for the scene server")
    parser.add_argument("--no-browser", action="store_true", help="with --couch, do not open a browser tab")
    parser.add_argument("--window", action="store_true", help="with --couch, keep the SDL2 window open too")
    args = parser.parse_args(argv)

    load_state = args.load_state
    if args.start_state and load_state is None:
        load_state = ROOT / "states" / "bedroom.state"

    # The scene IS the window, so --couch is headless unless you ask for both.
    headless = args.headless or (args.couch and not args.window)

    cfg = replace(
        Config(),
        rom_path=args.rom,
        n_neurons=args.neurons,
        seed=args.seed,
        uncapped=args.uncapped,
        headless=headless,
        hud=not args.no_hud,
        max_steps=args.max_steps,
        connectome_csv=args.connectome,
        load_state=load_state,
        save_state=args.save_state,
        couch_port=args.couch_port,
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
    # PyBoy's null window runs as fast as the CPU allows (measured here: about
    # 1,400 ticks/s), so a watched headless run has to pace itself.
    pace = cfg.couch_pace_hz if (args.couch and not args.uncapped) else 0.0
    save_path = None
    if args.save_brain:
        save_path = brain_save_target(args.brain)
        print(f"--save-brain: the learned brain will be written to {save_path} on exit", flush=True)
    options = LoopOptions(
        brain_path=brain_path, learn=args.learn, save_brain=args.save_brain, save_path=save_path, pace_hz=pace
    )
    return cfg, options, args


def run_with_couch(cfg: Config, options: LoopOptions, args: argparse.Namespace, display: object) -> None:
    """The same loop, with the scene server and its observer around it."""
    from flybrain.couch import CouchServer
    from flybrain.couch_observer import CouchObserver

    server = CouchServer(cfg, port=args.couch_port).start()
    watcher = CouchObserver(cfg, server.hub)
    print(f"couch: {server.url}   scene files from {server.root}", flush=True)
    print("couch: Ctrl+C stops the run and releases the port.", flush=True)
    if not args.no_browser:
        webbrowser.open(server.url)
    try:
        run_loop(cfg, observers=(display, watcher), options=options)
    finally:
        server.stop()
        print(
            f"couch: {watcher.states_sent} state and {watcher.videos_sent} video messages published, "
            f"{server.hub.messages_sent} written to browsers, {server.hub.clients_dropped} clients dropped",
            flush=True,
        )


def main() -> None:
    cfg, options, args = parse_args()
    display = Hud(cfg) if cfg.hud else PlainLog(cfg)
    if args.couch:
        run_with_couch(cfg, options, args, display)
    else:
        run_loop(cfg, observers=(display,), options=options)


if __name__ == "__main__":
    main()
