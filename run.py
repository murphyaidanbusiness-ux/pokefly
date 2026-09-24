"""Entrypoint. `python run.py` with no arguments finds the ROM next to itself.

With no arguments it is a JOURNEY: one long save file in `saves/journey/`.
The first time, it starts from `states/bedroom.state` with a copy of
`brains/latest.npz` as the journey's own brain; every time after, it carries
on from the save (game, neurons, brain, milestone clock). It learns while you
watch, into the journey brain and never into `brains/latest.npz`, autosaves
every few minutes and always on the way out.

Any flag that chooses its own brain or start point (`--brain`, `--naive`,
`--load-state`, `--start-state`, `--save-brain`, `--connectome`, `--seed`,
`--neurons`, `--replay`) or `--no-journey` is the old behaviour: one run,
nothing saved unless asked.

`--record out.mp4` renders the couch scene to a file in headless Edge or
Chrome instead of opening a tab (`src/flybrain/record.py`). A take never
writes the journey save or the milestone log.

No install step: src/ goes on sys.path here.
"""

from __future__ import annotations

import argparse
import shutil
import sys
import time
import webbrowser
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from flybrain.config import Config  # noqa: E402
from flybrain.hud import Hud, PlainLog  # noqa: E402
from flybrain.journey import JourneySave, JourneySession  # noqa: E402
from flybrain.loop import MISSING_ROM_EXIT, LoopOptions, require_rom, run_loop  # noqa: E402
from flybrain.milestones import LABELS, JourneyLog, MilestoneRecorder, game_time  # noqa: E402
from flybrain.record import RecordError  # noqa: E402
from flybrain.snapshot import FlySnapshot, SnapshotMismatch  # noqa: E402

BEST_BRAIN = ROOT / "brains" / "latest.npz"
JOURNEY_BRAIN = ROOT / "brains" / "journey.npz"
BEDROOM = ROOT / "states" / "bedroom.state"
MILESTONES = ROOT / "milestones"
JOURNEY_DIR = ROOT / "saves" / "journey"


def brain_save_target(brain: Path | None, best: Path = BEST_BRAIN, journey: Path = JOURNEY_BRAIN) -> Path:
    """Where `--learn --save-brain` writes. Never the best brain: that file is
    only ever replaced by training's evaluation blocks, and a brain that
    learned while you watched has no block score. With no `--brain`, or a
    `--brain` that is the best brain, it goes to `brains/journey.npz`."""
    if brain is None or Path(brain).resolve() == Path(best).resolve():
        return Path(journey)
    return Path(brain)


def require_start_state(path: str | Path) -> Path:
    """The savestate a run wants to start from, or a plain message and exit 2.

    `states/` is gitignored, so a fresh clone has no `states/bedroom.state`
    until `train.py --make-start-state` (or a first `train.py`) has made one.
    Without this the emulator window would open and then a FileNotFoundError
    traceback would land on top of it.
    """
    state = Path(path)
    if state.is_file():
        return state
    print(f"savestate not found: {state.resolve()}", file=sys.stderr)
    if state.resolve() == BEDROOM.resolve():
        print(
            "Make it first with `python train.py --make-start-state` (the naive fly plays from a cold boot "
            "until it is standing in Red's bedroom, about ten seconds), then run again.",
            file=sys.stderr,
        )
    raise SystemExit(MISSING_ROM_EXIT)


def journey_off_because(args: argparse.Namespace) -> str | None:
    """Why this run is not a journey, or None when it is."""
    if args.no_journey:
        return "--no-journey"
    for flag, chosen in (
        ("--replay", args.replay is not None),
        ("--brain", args.brain is not None),
        ("--naive", args.naive),
        ("--load-state", args.load_state is not None),
        ("--start-state", args.start_state),
        ("--save-brain", args.save_brain),
        ("--connectome", args.connectome is not None),
        ("--seed", args.seed != 0),
        ("--neurons", args.neurons != Config().n_neurons),
    ):
        if chosen:
            return flag
    return None


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
    parser.add_argument("--portrait", action="store_true", help="open the couch scene in the 9:16 layout (implies --couch)")
    parser.add_argument(
        "--replay",
        metavar="NAME",
        default=None,
        help="replay a milestone from milestones/NAME/ (implies --couch unless --headless)",
    )
    parser.add_argument("--no-journey", action="store_true", help="one run, no journey save")
    parser.add_argument("--fresh", action="store_true", help="discard the journey save and start a new journey")
    parser.add_argument("--yes", action="store_true", help="with --fresh, do not ask")
    parser.add_argument("--no-learn", action="store_true", help="journey mode: freeze the journey brain")
    parser.add_argument(
        "--record",
        metavar="OUT.mp4",
        type=Path,
        default=None,
        help="render the couch scene to an mp4 in headless Edge/Chrome (1080x1920 with --portrait, else 1920x1080)",
    )
    parser.add_argument(
        "--seconds",
        type=float,
        default=None,
        help="with --record, the take's length (default 20; a replay's own length plus 5)",
    )
    parser.add_argument("--record-fps", type=int, default=None, help="with --record, frames per second (default 60)")
    parser.add_argument("--browser", type=Path, default=None, help="with --record, the browser to render with")
    parser.add_argument(
        "--record-crf",
        type=int,
        default=None,
        help="with --record, libx264 quality: lower is better and bigger (default 23)",
    )
    parser.add_argument(
        "--scene-params",
        metavar="QUERY",
        default="",
        help="extra query parameters for the scene page, e.g. view=4&clean=1 (see README, Portrait mode)",
    )
    args = parser.parse_args(argv)

    if args.record is not None:
        # A take: the scene renders in a headless browser, so no SDL window
        # and no tab of ours opens. The terminal HUD stays.
        args.couch = True
        args.no_browser = True
        args.window = False
        if args.fresh:
            parser.error("--record never writes the journey, so --fresh has nothing to start")
        if args.seconds is not None and args.seconds <= 0:
            parser.error("--seconds must be positive")
        if args.record_fps is not None and args.record_fps <= 0:
            parser.error("--record-fps must be positive")
        if args.record_crf is not None and not 0 <= args.record_crf <= 51:
            parser.error("--record-crf runs from 0 to 51")
    elif any(value is not None for value in (args.seconds, args.record_fps, args.browser, args.record_crf)):
        parser.error("--seconds, --record-fps, --record-crf and --browser only mean something with --record")
    if args.portrait:
        args.couch = True
    if args.replay is not None and not args.headless:
        args.couch = True
    args.journey_off = journey_off_because(args)
    args.journey = args.journey_off is None
    if args.fresh and not args.journey:
        parser.error(f"--fresh starts a new journey, and {args.journey_off} means this run is not one")

    load_state = args.load_state
    if args.start_state and load_state is None:
        load_state = BEDROOM

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
        brain_path = BEST_BRAIN if BEST_BRAIN.is_file() else None
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


# ------------------------------------------------------------------ journey ---


def confirm_fresh(store: JourneySave, yes: bool, stdin=None, ask=input) -> bool:
    """Discard the journey save for `--fresh`. True when there is nothing in
    the way any more. A save is only thrown away on `--yes` or a `y` typed at
    a real terminal: on a pipe with no `--yes` it refuses."""
    stdin = sys.stdin if stdin is None else stdin
    if not store.folder.exists():
        return True
    manifest = store.manifest()
    what = (
        f"the journey save in {store.folder} ({manifest['game_time']} of game time, saved {manifest['saved_at']})"
        if manifest
        else f"everything in {store.folder}"
    )
    if not yes:
        if not (hasattr(stdin, "isatty") and stdin.isatty()):
            print(f"--fresh would discard {what}; not on a pipe without --yes. Nothing was touched.", flush=True)
            return False
        try:
            answer = ask(f"--fresh discards {what}. Type y to discard it: ").strip().lower()
        except (EOFError, OSError):
            # Windows calls the NUL device a terminal; reading it ends at once.
            answer = ""
            print()
        if answer != "y":
            print("kept the journey save; nothing was touched.", flush=True)
            return False
    store.discard()
    print(f"discarded {what}", flush=True)
    return True


def set_up_journey(cfg: Config, options: LoopOptions, args: argparse.Namespace, store: JourneySave) -> Config:
    """Continue the journey save, or start a new journey from the bedroom with
    a copy of the best brain. Returns the config to run with."""
    options.hourly_schedule = True
    learn = not args.no_learn
    if store.exists():
        snapshot, manifest = store.load()
        options.start = snapshot
        options.learn = learn
        options.brain_path = None
        print(
            f"continuing the journey: {manifest['game_time']} of game time, brain at "
            f"{manifest['episodes_trained']} episodes, saved {manifest['saved_at']} "
            f"({'learning' if learn else 'learning frozen'}; saves in {store.folder})",
            flush=True,
        )
        return replace(cfg, load_state=None)

    store.folder.mkdir(parents=True, exist_ok=True)
    brain = store.brain_path()
    if BEST_BRAIN.is_file():
        shutil.copyfile(BEST_BRAIN, brain)
        options.brain_path = brain
        options.brain_label = f"journey (copy of {BEST_BRAIN.name})"
        source = f"a copy of {BEST_BRAIN.relative_to(ROOT)}"
    else:
        options.brain_path = None
        options.brain_label = "journey (naive)"
        source = "a naive brain (no brains/latest.npz)"
    options.learn = learn
    print(
        f"new journey from {BEDROOM.relative_to(ROOT)} with {source} "
        f"({'learning' if learn else 'learning frozen'}; saves in {store.folder})",
        flush=True,
    )
    return replace(cfg, load_state=BEDROOM)


# --------------------------------------------------------------------- take ---


def set_up_take(cfg: Config, options: LoopOptions, args: argparse.Namespace, store: JourneySave) -> Config:
    """A `--record` run that is not a replay. A take never writes: no journey
    save, no milestone log, no replay folders. When the run would have been a
    journey it plays on from the journey save (read only, learning as asked)
    so the strip and the game time are the journey's; with no save yet it
    starts from the bedroom with the best brain, without copying anything."""
    if not args.journey:
        print(f"record: one run ({args.journey_off}); a take writes nothing", flush=True)
        return cfg
    learn = not args.no_learn
    options.hourly_schedule = True
    options.learn = learn
    if store.exists():
        snapshot, manifest = store.load()
        options.start = snapshot
        options.brain_path = None
        print(
            f"record: a take from the journey save ({manifest['game_time']} of game time, brain at "
            f"{manifest['episodes_trained']} episodes, {'learning' if learn else 'learning frozen'}); "
            "nothing is written back",
            flush=True,
        )
        return replace(cfg, load_state=None)
    require_start_state(BEDROOM)
    options.brain_path = BEST_BRAIN if BEST_BRAIN.is_file() else None
    print(
        f"record: no journey save yet, so the take starts from {BEDROOM} with "
        f"{options.brain_path or 'a naive brain'}; nothing is written",
        flush=True,
    )
    return replace(cfg, load_state=BEDROOM)


class TakeStarter:
    """An observer that starts the take once the page has had the game's
    first frame for `lead` seconds, so a take opens on the game and not on
    the TV's static. A page that never gets a frame still starts after two
    seconds of ticks, so the take cannot wait for ever."""

    def __init__(self, recorder, watcher, lead: float, clock=None) -> None:
        self.recorder, self.watcher, self.lead = recorder, watcher, float(lead)
        self.clock = clock or time.perf_counter
        self.first_tick: float | None = None
        self.first_video: float | None = None
        self.started = False

    def __call__(self, tick) -> None:
        if self.started:
            return
        now = self.clock()
        if self.first_tick is None:
            self.first_tick = now
        if self.first_video is None and self.watcher.videos_sent > 0:
            self.first_video = now
        if (self.first_video is not None and now - self.first_video >= self.lead) or now - self.first_tick >= 2.0:
            self.recorder.begin()
            self.started = True


def scene_url(base: str, portrait: bool, params: str = "") -> str:
    """The page a run opens: `portrait=1` first when asked, then whatever
    `--scene-params` adds (`view=4&clean=1`)."""
    parts = []
    if portrait:
        parts.append("portrait=1")
    extra = params.strip().lstrip("?&")
    if extra:
        parts.append(extra)
    return base + ("?" + "&".join(parts) if parts else "")


# ------------------------------------------------------------------- replay ---


class ReplayCheck:
    """Says whether the milestone landed on the tick it was recorded at."""

    def __init__(self, name: str, landed_tick: int) -> None:
        self.name, self.landed_tick = name, int(landed_tick)
        self.seen: int | None = None

    def __call__(self, tick) -> None:
        if self.seen is None and self.name in tick.milestones:
            self.seen = tick.game_tick
            same = self.seen == self.landed_tick
            print(
                f"replay: {LABELS.get(self.name, self.name)} landed at {game_time(self.seen)} (tick {self.seen}), "
                + ("exactly as recorded" if same else f"but it was recorded at tick {self.landed_tick}: DIVERGED"),
                flush=True,
            )

    def close(self) -> None:
        if self.seen is None:
            print(
                f"replay: {LABELS.get(self.name, self.name)} did not land in this run "
                f"(recorded at {game_time(self.landed_tick)}, tick {self.landed_tick})",
                flush=True,
            )


def set_up_replay(cfg: Config, options: LoopOptions, name: str) -> tuple[Config, ReplayCheck]:
    folder = MILESTONES / name
    if not FlySnapshot.exists(folder):
        known = sorted(p.name for p in MILESTONES.iterdir() if FlySnapshot.exists(p)) if MILESTONES.is_dir() else []
        print(
            f"no replay at {folder}. Replays there: {', '.join(known) or 'none yet'}",
            file=sys.stderr,
        )
        raise SystemExit(2)
    snapshot = FlySnapshot.load(folder)
    meta = snapshot.meta
    landed = int(meta["landed_tick"])
    options.start = snapshot
    options.learn = None  # exactly what the recorded run was doing
    options.brain_path = None
    print(
        f"replay: {meta.get('label', name)}, recorded {meta.get('date', '?')} in a {meta.get('kind', '?')} run "
        f"with {meta.get('brain') or 'no brain'} at {meta.get('episodes_trained', '?')} episodes. "
        f"Starts at {game_time(meta['start_tick'])} of game time, {game_time(landed - meta['start_tick'])} "
        f"before it lands at {game_time(landed)}. Fast-forwarding {snapshot.emulator.ticks} ticks of "
        "recorded input from the savestate first.",
        flush=True,
    )
    return replace(cfg, load_state=None), ReplayCheck(name, landed)


# --------------------------------------------------------------------- main ---


def run_with_couch(cfg: Config, options: LoopOptions, args: argparse.Namespace, observers: list, extras=None,
                   replay_target=None):
    """The same loop, with the scene server and its observer around it. With
    `--record` a headless browser renders the page into the file, the loop
    waits for it before its first tick, and the run ends with the take.
    Returns the RecordResult for a take, None otherwise."""
    from flybrain.couch import CouchServer
    from flybrain.couch_observer import CouchObserver

    server = CouchServer(cfg, port=args.couch_port).start()
    watcher = CouchObserver(cfg, server.hub)
    watcher.extras = extras
    watcher.replay_target = replay_target
    options.commands.append(server.hub.take_commands)
    url = scene_url(server.url, args.portrait, args.scene_params)
    print(f"couch: {url}   scene files from {server.root}", flush=True)
    print("couch: Ctrl+C stops the run and releases the port.", flush=True)
    recorder = None
    if args.record is not None:
        from flybrain.record import Recorder, frame_size

        size = frame_size(args.portrait)
        recorder = Recorder(
            cfg, url, args.record, args.seconds, fps=args.record_fps, size=size, browser=args.browser,
            crf=args.record_crf,
        ).start()
        print(
            f"record: {args.record}, {args.seconds:g} s at {recorder.fps} fps, {size[0]}x{size[1]}; "
            "the game waits for the browser",
            flush=True,
        )

        options.on_start = lambda fly: recorder.wait_ready()
        options.stop_when = recorder.take_over.is_set
        observers = [*observers, TakeStarter(recorder, watcher, cfg.couch_record_lead)]
    elif not args.no_browser:
        webbrowser.open(url)
    result = None
    try:
        run_loop(cfg, observers=(*observers, watcher), options=options)
    finally:
        if recorder is not None:
            # Before the server goes, so the last frames are of a live page.
            recorder.stop()
            result = recorder.join()
            print(f"record: {result.line()}", flush=True)
            warning = result.warning()
            if warning:
                print(f"record: {warning}", flush=True)
        server.stop()
        print(
            f"couch: {watcher.states_sent} state and {watcher.videos_sent} video messages published, "
            f"{server.hub.messages_sent} written to browsers, {server.hub.clients_dropped} clients dropped, "
            f"{server.hub.commands_received} commands from the page",
            flush=True,
        )
    return result


def main(argv: list[str] | None = None):
    """One run. Returns the RecordResult for a `--record` take, else None
    (`scripts/render_shots.py` calls this in-process, once per shot)."""
    cfg, options, args = parse_args(argv)
    # Everything a run needs from disk is checked here, before a journey
    # folder is made, a brain copied or the HUD has cleared the screen.
    require_rom(cfg)
    if cfg.load_state is not None:
        require_start_state(cfg.load_state)
    if args.record is not None:
        from flybrain.record import find_browser

        if find_browser(args.browser) is None:
            where = args.browser or "Edge or Chrome in the usual places"
            print(f"cannot record: no browser found ({where}); pass --browser PATH", file=sys.stderr)
            raise SystemExit(2)
    extras = None
    replay_target = None
    observers: list = []

    if args.replay is not None:
        cfg, check = set_up_replay(cfg, options, args.replay)
        observers.append(check)
        replay_target = (check.name, check.landed_tick)
        if args.record is not None and args.seconds is None:
            # The replay's own length, then long enough for the flash.
            start = int(options.start.meta["start_tick"])
            args.seconds = (check.landed_tick - start) / cfg.game_hz + cfg.couch_record_tail
    elif args.record is not None:
        cfg = set_up_take(cfg, options, args, JourneySave(JOURNEY_DIR))
    else:
        options.recorder = MilestoneRecorder(cfg, MILESTONES, "watch", JourneyLog(MILESTONES / "journey.json"))
        if args.journey:
            store = JourneySave(JOURNEY_DIR)
            if args.fresh and not confirm_fresh(store, args.yes):
                raise SystemExit(2)
            if not store.exists():
                require_start_state(BEDROOM)
            cfg = set_up_journey(cfg, options, args, store)
            session = JourneySession(store, cfg)
            options.journey = session
            extras = session.status
        else:
            print(f"journey off ({args.journey_off}): one run, nothing saved unless asked", flush=True)

    display = Hud(cfg) if cfg.hud else PlainLog(cfg)
    if extras is not None and hasattr(display, "status"):
        display.status = extras
    observers.insert(0, display)
    if args.record is not None and args.seconds is None:
        args.seconds = cfg.couch_record_seconds
    result = None
    try:
        if args.couch:
            result = run_with_couch(cfg, options, args, observers, extras=extras, replay_target=replay_target)
        else:
            run_loop(cfg, observers=tuple(observers), options=options)
    except RecordError as error:
        display.close()
        print(f"cannot record: {error}", file=sys.stderr)
        raise SystemExit(2) from None
    except KeyboardInterrupt:
        # Ctrl+C while the browser was still starting: the loop never ran,
        # and the recorder has already closed whatever file it had.
        if args.record is None:
            raise
        display.close()
        print("record: stopped before the take began", file=sys.stderr)
    except SnapshotMismatch as error:
        # A journey save or a replay from a fly built with other numbers: say
        # so in one line rather than a traceback under a half-drawn HUD.
        display.close()
        print(f"cannot continue: {error}", file=sys.stderr)
        if args.journey:
            print("A changed tuning value needs a new journey: run again with --fresh.", file=sys.stderr)
        raise SystemExit(2) from None
    finally:
        # The loop closes its observers on the way out of a run; when it
        # never got that far (PyBoy refused the ROM, a state failed to load)
        # the HUD still has to give the cursor back.
        display.close()
    return result


if __name__ == "__main__":
    main()
