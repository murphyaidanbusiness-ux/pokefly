"""Wiring. `run.py` parses arguments and calls `run_loop(config)`.

One emulator tick, one optic-lobe read, one brain step, one motor update.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np

from .brain import Brain
from .config import POOL_NAMES, Config
from .connectome import Connectome, from_edge_list, synthetic
from .emulator import Emulator
from .hud import Hud, PlainLog
from .optic_lobe import OpticLobe

MISSING_ROM_EXIT = 2


def build_connectome(cfg: Config) -> Connectome:
    if cfg.connectome_csv is not None:
        return from_edge_list(cfg.connectome_csv, cfg)
    return synthetic(n=cfg.n_neurons, k=cfg.lattice_k, rewire_p=cfg.rewire_p, seed=cfg.seed, cfg=cfg)


def run_loop(cfg: Config) -> dict:
    """Runs until the window closes, Ctrl+C, or `max_steps`. Returns a summary
    dict (steps, presses per button, panics, positions seen) for the caller and
    for the integration test."""
    rom = Path(cfg.rom_path)
    if not rom.is_file():
        print(f"ROM not found: {rom.resolve()}", file=sys.stderr)
        print("Put your own Pokemon Red dump (1 MB, .gb) at that exact path and run again.", file=sys.stderr)
        raise SystemExit(MISSING_ROM_EXIT)

    connectome = build_connectome(cfg)
    optic = OpticLobe(cfg)
    brain = Brain(connectome, cfg)
    emulator = Emulator(rom, headless=cfg.headless, uncapped=cfg.uncapped, cfg=cfg)

    # Imported here so motor.py never needs to know about the emulator type.
    from .motor import MotorBridge

    motor = MotorBridge(connectome, cfg, emulator)
    display = Hud(cfg) if cfg.hud else PlainLog(cfg)

    if cfg.load_state is not None:
        emulator.load_state(cfg.load_state)

    step = 0
    positions: set[tuple[int, int, int]] = set()
    position: tuple[int, int, int] = (0, 0, 0)
    started = time.perf_counter()
    try:
        while cfg.max_steps == 0 or step < cfg.max_steps:
            if not emulator.tick():
                break
            step += 1
            current = optic.step(emulator.frame())
            pulse = motor.take_pulse()
            if pulse:
                current = current + pulse
            spikes = brain.step(current)
            position = emulator.position()
            positions.add(position)
            action = motor.update(spikes, position)
            display.note(action)
            display.update(step, brain, motor, position, emulator.in_battle)
    except KeyboardInterrupt:
        pass
    finally:
        elapsed = time.perf_counter() - started
        motor.release_all()
        if cfg.save_state is not None:
            emulator.save_state(cfg.save_state)
        emulator.close()
        display.close()

    summary = {
        "steps": step,
        "seconds": round(elapsed, 2),
        "ticks_per_second": round(step / elapsed, 1) if elapsed > 0 else 0.0,
        "firing_rate": round(brain.firing_rate, 5),
        "presses": dict(motor.fire_counts),
        "total_presses": int(sum(motor.fire_counts.values())),
        "panics": motor.panic_count,
        "distinct_positions": len(positions),
        "final_position": position,
        "moved": len(positions) > 1,
    }
    print(
        f"done: {summary['steps']} steps in {summary['seconds']}s "
        f"({summary['ticks_per_second']} ticks/s), firing {summary['firing_rate'] * 100:.2f}%",
        flush=True,
    )
    print(
        "presses: " + " ".join(f"{name}={motor.fire_counts[name]}" for name in POOL_NAMES)
        + f"  total={summary['total_presses']}  panics={summary['panics']}",
        flush=True,
    )
    print(
        f"positions: {summary['distinct_positions']} distinct (map_id, x, y); "
        f"moved={summary['moved']}; final={summary['final_position']}",
        flush=True,
    )
    return summary


def measure_step_ms(n: int, seed: int = 0, steps: int = 400, cfg: Config | None = None) -> float:
    """Mean milliseconds per brain step, for the README numbers."""
    cfg = cfg or Config()
    connectome = synthetic(n=n, k=cfg.lattice_k, rewire_p=cfg.rewire_p, seed=seed, cfg=cfg)
    brain = Brain(connectome, cfg)
    rng = np.random.default_rng(seed)
    currents = rng.random((steps, cfg.n_sensory), dtype=np.float32) * cfg.max_current
    for i in range(50):  # warm up
        brain.step(currents[i % steps])
    started = time.perf_counter()
    for i in range(steps):
        brain.step(currents[i])
    return (time.perf_counter() - started) / steps * 1000.0
