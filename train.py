"""Training entrypoint. `python train.py` with no arguments trains from the
bedroom savestate, making that savestate first if it is missing.

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
from flybrain.training import (  # noqa: E402
    evaluate,
    learning_curve,
    make_start_state,
    print_milestone_table,
    train,
)

MILESTONES = ROOT / "milestones"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train the fly's mushroom body on Pokemon Red.")
    parser.add_argument("--rom", type=Path, default=ROOT / "roms" / "pokemon_red.gb")
    parser.add_argument("--ticks", type=int, default=Config.train_ticks, help="total tick budget")
    parser.add_argument("--episode-ticks", type=int, default=Config.episode_ticks)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--neurons", type=int, default=2000)
    parser.add_argument(
        "--out", type=Path, default=ROOT / "brains" / "training.npz", help="the training state: always the latest weights"
    )
    parser.add_argument(
        "--best", type=Path, default=ROOT / "brains" / "latest.npz", help="the best brain by block score; run.py loads it"
    )
    parser.add_argument("--resume", action="store_true", help="continue from the training state at --out")
    parser.add_argument(
        "--eval-every", type=int, default=Config.eval_every, help="training episodes between evaluation blocks (0: none)"
    )
    parser.add_argument("--eval-block", type=int, default=Config.eval_block, help="learning-off episodes per block")
    parser.add_argument("--log", type=Path, default=ROOT / "runs" / "train.csv")
    parser.add_argument("--eval-log", type=Path, default=None, help="with --evaluate: one CSV row per episode")
    parser.add_argument("--state", type=Path, default=ROOT / "states" / "bedroom.state")
    parser.add_argument("--make-start-state", action="store_true", help="write the start savestate and stop")
    parser.add_argument("--evaluate", type=Path, default=None, help="skip training: evaluate this brain")
    parser.add_argument("--evaluate-naive", action="store_true", help="skip training: evaluate the untrained fly")
    parser.add_argument("--eval-episodes", type=int, default=10)
    parser.add_argument("--eval-seed", type=int, default=90_000)
    parser.add_argument(
        "--milestones",
        type=Path,
        nargs="?",
        const=ROOT / "runs" / "train.csv",
        default=None,
        metavar="CSV",
        help="print median ticks to each milestone by 10-episode bucket from a training CSV "
        "(default runs/train.csv), and stop",
    )
    parser.add_argument("--no-record", action="store_true", help="do not write milestones/journey.json or replays")
    return parser.parse_args(argv)


def main() -> None:
    args = parse_args()
    if args.milestones is not None:
        print_milestone_table(args.milestones)
        return
    cfg = replace(Config(), rom_path=args.rom, seed=args.seed, n_neurons=args.neurons, headless=True, uncapped=True)
    milestones_dir = None if args.no_record else MILESTONES

    if args.make_start_state:
        make_start_state(cfg, args.state)
        return

    if args.evaluate is not None or args.evaluate_naive:
        brain = None if args.evaluate_naive else args.evaluate
        label = "naive" if brain is None else "trained"
        results = evaluate(
            cfg,
            brain_path=brain,
            episodes=args.eval_episodes,
            episode_ticks=args.episode_ticks,
            state_path=args.state,
            base_seed=args.eval_seed,
            label=label,
            log_path=args.eval_log,
            milestones_dir=milestones_dir,
        )
        left = sum(r.left_house for r in results)
        mean = sum(r.reward for r in results) / max(len(results), 1)
        print(
            f"{label}: reached Pallet Town in {left} of {len(results)} episodes, mean reward {mean:.1f}", flush=True
        )
        return

    results = train(
        cfg,
        total_ticks=args.ticks,
        episode_ticks=args.episode_ticks,
        out=args.out,
        best=args.best,
        log_path=args.log,
        state_path=args.state,
        resume=args.resume,
        eval_every=args.eval_every,
        eval_block=args.eval_block,
        milestones_dir=milestones_dir,
    )
    print("\nlearning curve (training episodes only)", flush=True)
    for row in learning_curve(results):
        print(
            f"  {row['episodes']:>9s}  n={row['n']:<3d} mean reward {row['mean_reward']:8.1f}  "
            f"mean tiles {row['mean_tiles']:6.1f}  left house {row['left_house']:.2f}  "
            f"|w_a| {row['w_actor_abs']:.5f}  |w_c| {row['w_critic_abs']:.5f}  lr {row['lr_actor']:.2e}",
            flush=True,
        )


if __name__ == "__main__":
    main()
