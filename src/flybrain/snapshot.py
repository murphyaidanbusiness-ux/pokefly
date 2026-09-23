"""A fly snapshot on disk: one `.state` and one `.npz` beside it.

`Fly.snapshot()` returns a `FlySnapshot`: the emulator's `EmulatorPoint` (a
full savestate anchor plus the button events since it, see `emulator.py`) and
one plain dict per component holding every array and number that decides the
next tick, with the bit-generator state of each RNG. This module only moves
that between memory and disk.

- `<stem>.state` is the anchor savestate, exactly what PyBoy wrote. When the
  snapshot was taken right on an anchor (a journey save always is), it is a
  savestate of the very tick and loads in any PyBoy on its own.
- `<stem>.npz` holds every array, keyed `component/name`, and one JSON string
  `meta` with everything else: the scalars, the RNG states (PCG64 states are
  128-bit integers, which JSON keeps exactly), the button events since the
  anchor and the dynamics fingerprint of the config the fly was built from.

Both files are written to a temporary name and renamed into place.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from .emulator import EmulatorPoint

SNAPSHOT_VERSION = 1


class SnapshotMismatch(ValueError):
    """A snapshot taken from a fly built with different numbers."""


@dataclass
class FlySnapshot:
    emulator: EmulatorPoint
    parts: dict[str, dict]  # component name -> its get_state()
    fingerprint: str
    meta: dict = field(default_factory=dict)  # game tick, step, brain, ... (informational)

    # -- disk ---------------------------------------------------------------

    def save(self, folder: str | Path, stem: str = "start") -> tuple[Path, Path]:
        folder = Path(folder)
        folder.mkdir(parents=True, exist_ok=True)
        state_path = folder / f"{stem}.state"
        npz_path = folder / f"{stem}.npz"
        self.write(state_path, npz_path)
        return state_path, npz_path

    def write(self, state_path: str | Path, npz_path: str | Path) -> None:
        """Both files, each written whole or not at all."""
        state_path, npz_path = Path(state_path), Path(npz_path)
        arrays: dict[str, np.ndarray] = {}
        scalars: dict[str, dict] = {}
        for part, state in self.parts.items():
            plain = {}
            for key, value in state.items():
                if isinstance(value, np.ndarray):
                    arrays[f"{part}/{key}"] = value
                else:
                    plain[key] = value
            scalars[part] = plain
        point = self.emulator
        meta = {
            "version": SNAPSHOT_VERSION,
            "fingerprint": self.fingerprint,
            "meta": self.meta,
            "parts": scalars,
            "emulator": {
                "events": [[tick, [[button, pressed] for button, pressed in evs]] for tick, evs in point.events],
                "ticks": point.ticks,
                "pending": [[button, pressed] for button, pressed in point.pending],
            },
        }
        _write_atomic(state_path, point.anchor)
        partial = npz_path.with_name(npz_path.name + ".partial")
        with partial.open("wb") as handle:
            np.savez(handle, meta=np.array(json.dumps(meta)), **arrays)
        os.replace(partial, npz_path)

    @classmethod
    def load(cls, folder: str | Path, stem: str = "start") -> FlySnapshot:
        folder = Path(folder)
        return cls.read(folder / f"{stem}.state", folder / f"{stem}.npz")

    @classmethod
    def read(cls, state_path: str | Path, npz_path: str | Path) -> FlySnapshot:
        anchor = Path(state_path).read_bytes()
        with np.load(Path(npz_path), allow_pickle=False) as data:
            meta = json.loads(str(data["meta"]))
            arrays = {name: np.array(data[name]) for name in data.files if name != "meta"}
        if meta.get("version") != SNAPSHOT_VERSION:
            raise SnapshotMismatch(f"{npz_path} is snapshot version {meta.get('version')}, not {SNAPSHOT_VERSION}")
        parts: dict[str, dict] = {name: dict(values) for name, values in meta["parts"].items()}
        for key, value in arrays.items():
            part, name = key.split("/", 1)
            parts.setdefault(part, {})[name] = value
        emu = meta["emulator"]
        point = EmulatorPoint(
            anchor=anchor,
            events=tuple(
                (int(tick), tuple((str(button), bool(pressed)) for button, pressed in evs)) for tick, evs in emu["events"]
            ),
            ticks=int(emu["ticks"]),
            pending=tuple((str(button), bool(pressed)) for button, pressed in emu["pending"]),
        )
        return cls(emulator=point, parts=parts, fingerprint=str(meta["fingerprint"]), meta=dict(meta.get("meta", {})))

    @staticmethod
    def exists(folder: str | Path, stem: str = "start") -> bool:
        folder = Path(folder)
        return (folder / f"{stem}.state").is_file() and (folder / f"{stem}.npz").is_file()


def _write_atomic(path: Path, data: bytes) -> None:
    partial = path.with_name(path.name + ".partial")
    partial.write_bytes(data)
    os.replace(partial, path)
