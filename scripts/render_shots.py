"""Render every shot in docs/shot-list.md to shots/NN-<slug>.mp4, headless.

    python scripts/render_shots.py                 every shot
    python scripts/render_shots.py --only 4        just shot 4 (shot 3 is two files)
    python scripts/render_shots.py --seconds 5     every take 5 s long (a quick look)
    python scripts/render_shots.py --out DIR       somewhere other than shots/

Each shot is one `run.py --record` run, in this process, on a port of its
own that nothing else holds, so a `run.py --couch` of yours on 8765 can keep
going. A take never writes the journey save, the milestone log or a replay:
the journey shots play on from `saves/journey/` read only, learning frozen.
Prints one line per file with its length and the capture rate, and the
total wall clock at the end.
"""

from __future__ import annotations

import argparse
import socket
import sys
import time
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

import run  # noqa: E402
from flybrain.snapshot import FlySnapshot  # noqa: E402

JOURNEY = ("--portrait", "--no-learn")


@dataclass(frozen=True)
class Take:
    """One file. `seconds` None means the replay's own length plus the tail."""

    number: int
    slug: str
    line: str
    args: tuple[str, ...]
    params: str = ""
    seconds: float | None = None

    def filename(self) -> str:
        return f"{self.number:02d}-{self.slug}.mp4"


def starter_replay(milestones: Path = run.MILESTONES) -> str:
    """Shot 6 is the starter once its replay exists; until then the lab."""
    return "got_starter" if FlySnapshot.exists(milestones / "got_starter") else "entered_lab"


def takes(milestones: Path = run.MILESTONES) -> list[Take]:
    """docs/shot-list.md, as files. Shot 3 is two: the orbit, then the TV."""
    starter = starter_replay(milestones)
    return [
        Take(1, "composition", "I got a fly brain to play Pokemon Red", JOURNEY, "", 20.0),
        Take(2, "monitor", "neurons wired into PyBoy", JOURNEY, "view=4&clean=1", 15.0),
        Take(3, "orbit", "I made this couch setup for him", JOURNEY, "view=1&clean=1&orbit=1", 10.0),
        Take(3, "tv", "and the live game is on that TV", JOURNEY, "view=2&clean=1", 8.0),
        Take(4, "left-bedroom", "It took N to leave Red's bedroom", ("--replay", "left_bedroom", "--portrait")),
        Take(5, "left-house", "it hit the stairs and wandered Pallet Town", ("--replay", "left_house", "--portrait")),
        Take(6, starter.replace("_", "-"), "before triggering Professor Oak", ("--replay", starter, "--portrait")),
        Take(7, "fly", "still waiting for him to pick his starter", JOURNEY, "view=3&clean=1", 30.0),
        Take(8, "outro", "comment Pokemon", JOURNEY, "", 20.0),
    ]


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def argv_for(take: Take, out: Path, seconds: float | None, port: int, browser: str | None) -> list[str]:
    argv = [*take.args, "--record", str(out / take.filename()), "--couch-port", str(port), "--no-hud"]
    if take.params:
        argv += ["--scene-params", take.params]
    length = seconds if seconds is not None else take.seconds
    if length is not None:
        argv += ["--seconds", f"{length:g}"]
    if browser:
        argv += ["--browser", browser]
    return argv


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Render docs/shot-list.md to mp4 files.")
    parser.add_argument("--only", type=int, default=None, help="render just this shot number")
    parser.add_argument("--seconds", type=float, default=None, help="every take this long")
    parser.add_argument("--out", type=Path, default=ROOT / "shots", help="where the files go (default shots/)")
    parser.add_argument("--browser", default=None, help="the browser to render with (default Edge or Chrome)")
    args = parser.parse_args(argv)

    chosen = [take for take in takes() if args.only is None or take.number == args.only]
    if not chosen:
        parser.error(f"there is no shot {args.only}; the list runs 1 to 8")
    args.out.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    lines: list[str] = []
    for take in chosen:
        print(f"\n=== shot {take.number} ({take.slug}): \"{take.line}\"", flush=True)
        began = time.perf_counter()
        try:
            result = run.main(argv_for(take, args.out, args.seconds, free_port(), args.browser))
        except SystemExit as stop:
            line = f"shot {take.number} {take.filename()}: not rendered (exit {stop.code})"
            print(line, flush=True)
            lines.append(line)
            continue
        wall = time.perf_counter() - began
        if result is None:
            lines.append(f"shot {take.number} {take.filename()}: not rendered")
            continue
        line = (
            f"shot {take.number} {result.path}: {result.seconds:.2f} s, {result.frames} frames, "
            f"{result.size[0]}x{result.size[1]}, captured {result.capture_fps:.1f} fps "
            f"({result.used} distinct), {wall:.0f} s wall"
        )
        if result.slow:
            line += "  <-- UNDER 50 FPS, WILL STUTTER"
        if result.error:
            line += f"  ERROR: {result.error}"
        lines.append(line)
        if result.early:
            lines.append("stopped early; the rest were not rendered")
            break
    total = time.perf_counter() - started
    print("\n" + "\n".join(lines), flush=True)
    print(f"total wall clock: {total:.0f} s ({total / 60:.1f} min) for {len(lines)} files", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
