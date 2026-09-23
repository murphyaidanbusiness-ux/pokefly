"""The journey save: watching as one long save file.

`saves/journey/` holds one fly snapshot (`fly.state` + `fly.npz`, the same
pair a milestone replay uses, taken on a fresh savestate so it needs no
fast-forward) and the brain the journey is learning into (`brain.npz`, an
ordinary mushroom-body file that `run.py --brain` can load anywhere). A
manifest, `journey.json`, names the three files by SHA-256.

A save never corrupts the one before it, however it is interrupted:

1. every new file is written under a `.tmp` name,
2. each data file in turn: the current one becomes `.bak`, the `.tmp` takes
   its place,
3. the manifest last, the same way.

At every instant some manifest (`journey.json`, else `journey.json.bak`, else
the `.tmp`) names three files that exist somewhere under the name, its `.bak`
or its `.tmp` with exactly the recorded hash, so the loader always finds one
whole save: the new one once step 3 is done, the previous one before. After a
completed save the previous one is the `.bak` set.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from .config import Config
from .milestones import game_time
from .snapshot import FlySnapshot

MANIFEST = "journey.json"
STATE = "fly.state"
FLY = "fly.npz"
BRAIN = "brain.npz"
DATA_FILES = (STATE, FLY, BRAIN)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class JourneySave:
    def __init__(self, folder: str | Path) -> None:
        self.folder = Path(folder)

    # -- reading -------------------------------------------------------------

    def _whole(self) -> tuple[dict, dict[str, Path]] | None:
        """The newest manifest whose three files are all present and intact,
        with where each one is, or None."""
        for name in (MANIFEST, MANIFEST + ".bak", MANIFEST + ".tmp"):
            path = self.folder / name
            if not path.is_file():
                continue
            try:
                manifest = json.loads(path.read_text(encoding="utf-8"))
                wanted = dict(manifest["files"])
            except (ValueError, KeyError, TypeError):
                continue
            found: dict[str, Path] = {}
            for data_name, digest in wanted.items():
                for suffix in ("", ".bak", ".tmp"):
                    candidate = self.folder / (data_name + suffix)
                    if candidate.is_file() and _sha(candidate) == digest:
                        found[data_name] = candidate
                        break
            if set(found) == set(DATA_FILES):
                return manifest, found
        return None

    def exists(self) -> bool:
        return self._whole() is not None

    def manifest(self) -> dict | None:
        whole = self._whole()
        return None if whole is None else whole[0]

    def load(self) -> tuple[FlySnapshot, dict]:
        whole = self._whole()
        if whole is None:
            raise FileNotFoundError(f"no whole journey save in {self.folder}")
        manifest, found = whole
        return FlySnapshot.read(found[STATE], found[FLY]), manifest

    def brain_path(self) -> Path:
        return self.folder / BRAIN

    # -- writing -------------------------------------------------------------

    def save(self, fly, extra: dict | None = None) -> dict:
        """Write the fly as it stands, on a fresh savestate. Returns the manifest."""
        self.folder.mkdir(parents=True, exist_ok=True)
        snapshot = fly.snapshot(full=True)
        tmp = {name: self.folder / (name + ".tmp") for name in DATA_FILES}
        snapshot.write(tmp[STATE], tmp[FLY])
        fly.mushroom.save(tmp[BRAIN])
        previous = self.manifest() or {}
        manifest = {
            "version": 1,
            "game_tick": int(fly.clock),
            "game_time": game_time(fly.clock),
            "saved_at": datetime.now().isoformat(timespec="seconds"),
            "saves": int(previous.get("saves", 0)) + 1,
            "episodes_trained": int(fly.mushroom.episodes_trained),
            "ticks_trained": int(fly.mushroom.ticks_trained),
            "fingerprint": snapshot.fingerprint,
            "files": {name: _sha(path) for name, path in tmp.items()},
            **(extra or {}),
        }
        manifest_tmp = self.folder / (MANIFEST + ".tmp")
        manifest_tmp.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        for name in DATA_FILES:
            self._rotate(name)
        self._rotate(MANIFEST)
        return manifest

    def _rotate(self, name: str) -> None:
        current = self.folder / name
        if current.is_file():
            os.replace(current, self.folder / (name + ".bak"))
        os.replace(self.folder / (name + ".tmp"), current)

    def discard(self) -> None:
        """`--fresh`: the whole folder goes, backups included."""
        if self.folder.exists():
            shutil.rmtree(self.folder)


class JourneySession:
    """Autosave and Save, around one run of the loop.

    `run_loop` calls `start` once, `after_tick` every tick and `save` on a
    Save request and on the way out. `clock` is injectable so the autosave
    schedule can be tested without waiting five minutes.
    """

    def __init__(
        self,
        store: JourneySave,
        cfg: Config,
        *,
        clock: Callable[[], float] = time.monotonic,
        say: Callable[[str], None] | None = None,
        extra: dict | None = None,
    ) -> None:
        self.store = store
        self.every = max(1.0, cfg.autosave_minutes * 60.0)
        self.clock = clock
        self.say = say or (lambda line: print(line, flush=True))
        self.extra = dict(extra or {})
        self.last_save: float | None = None  # clock() of the last save this run
        self.saved_wall: float | None = None  # wall time of the newest save on disk
        self._timer = 0.0
        self.saves = 0
        self.game_tick = 0

    def start(self, fly) -> None:
        self._timer = self.clock()
        self.game_tick = fly.clock
        manifest = self.store.manifest()
        if manifest and manifest.get("saved_at"):
            try:
                self.saved_wall = datetime.fromisoformat(manifest["saved_at"]).timestamp()
            except ValueError:
                self.saved_wall = None

    def after_tick(self, fly) -> None:
        self.game_tick = fly.clock
        if self.clock() - self._timer >= self.every:
            self.save(fly, "autosave")

    def save(self, fly, reason: str) -> dict:
        started = time.perf_counter()
        manifest = self.store.save(fly, self.extra)
        self.last_save = self._timer = self.clock()
        self.saved_wall = time.time()
        self.saves += 1
        self.game_tick = fly.clock
        self.say(
            f"journey saved ({reason}): {game_time(fly.clock)} of game time, brain at "
            f"{fly.mushroom.episodes_trained} episodes, {(time.perf_counter() - started) * 1000:.0f} ms, "
            f"to {self.store.folder}"
        )
        return manifest

    def status(self) -> dict:
        """For the overlay: seconds since the newest save on disk, None when
        there is none yet."""
        return {
            "journey": True,
            "saved_ago": None if self.saved_wall is None else round(max(0.0, time.time() - self.saved_wall), 1),
        }
