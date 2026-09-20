# fly-brain-pokemon: build contract

A simulated Drosophila brain plays Pokemon Red through PyBoy. Approved by Aidan on 2026-09-20.
This file is the contract. Where it is silent, pick the simplest thing and say so in the README.

## Environment

- Windows 11, PowerShell. The home path contains a space (`C:\Users\aidan murphy\...`): quote every path, use `pathlib` everywhere, never build paths by string concatenation.
- Python 3.13 at `py -3.13`. Create `.venv` in the project root and install into it. Never install into the global interpreter.
- The ROM is already at `roms/pokemon_red.gb` (1 MB, the user's own dump). `roms/` is gitignored. NEVER download a ROM from anywhere.
- Dependencies: `pyboy` (2.x API), `numpy`, `pillow`, `opencv-python`. Dev: `pytest`. Nothing else (no scipy, no rich, no torch).
- PyBoy 2.x API to use: `PyBoy(path, window="SDL2"|"null", sound_emulated=False)`, `pyboy.tick(count, render)` returns False when the window is closed, `pyboy.screen.ndarray` (144,160,4 RGBA), `pyboy.button_press(name)` / `pyboy.button_release(name)`, `pyboy.memory[addr]`, `pyboy.set_emulation_speed(0)` for uncapped, `pyboy.stop(save=False)`. Verify against the installed version (`pip show pyboy`, read its source if anything differs) rather than trusting this list.

## Layout

```
run.py                   the single entrypoint; adds src/ to sys.path so it runs with no install step
pyproject.toml           project metadata + dependencies; requirements.txt mirrors it
README.md                setup, run, flags, what to expect, how the brain is wired
.gitignore               .venv, roms/, __pycache__, *.state, .pytest_cache
src/flybrain/
  __init__.py
  config.py              one frozen dataclass holding every tunable number, with a comment per number
  emulator.py            Emulator: PyBoy wrapper
  optic_lobe.py          OpticLobe: frame -> sensory currents
  connectome.py          Connectome dataclass + synthetic builder + edge-list loader
  brain.py               Brain: leaky integrate-and-fire network
  motor.py               MotorBridge: pools -> button presses, panic reflex
  hud.py                 Hud: in-place terminal display
  loop.py                run_loop(config): wires the above; run.py only parses args and calls it
tests/                   pytest, headless, must pass with NO rom present (except one test that skips when the rom is missing)
```

## Components

### emulator.py
- `Emulator(rom_path, headless=False, uncapped=False)`. Windowed SDL2 by default so the game is visible. 60 Hz by default, `uncapped` sets emulation speed 0.
- `tick() -> bool` (False = window closed, loop exits cleanly), `frame() -> np.ndarray` (144,160 uint8 grayscale), `press(button)`, `release(button)`, `position() -> (map_id, x, y)`, `close()`.
- Pokemon Red RAM: map id `0xD35E`, player Y `0xD361`, player X `0xD362`. Also expose `in_battle` from `0xD057` (nonzero = battle) for the HUD.
- Sound off.

### optic_lobe.py
- Downsample the 160x144 frame to 16x16 grayscale with `cv2.resize(..., interpolation=cv2.INTER_AREA)`, float32 in [0,1].
- Luminance delta against the previous downsampled frame. Split into ON (brightening) and OFF (darkening) channels, like fly L1/L2 pathways: 256 + 256 = 512 sensory channels.
- Output: a float32 vector of 512 input currents = gain * rectified delta, plus a small tonic term proportional to absolute luminance so a static screen (dialogue box waiting for A) still produces some drive. Add low Gaussian noise (seeded RNG) so the network never goes fully silent.
- First frame: delta is zero, not the whole frame.

### connectome.py
- `Connectome`: `weights` (N,N float32, row = postsynaptic, col = presynaptic), `sensory_idx` (512), `motor_pools: dict[str, np.ndarray]`, `n`.
- `synthetic(n=2000, k=20, rewire_p=0.1, seed=0)`: Watts-Strogatz small world built with numpy only (ring lattice, rewire each edge with probability p), directed, no self loops. 80% excitatory / 20% inhibitory by presynaptic neuron (Dale's law: every outgoing weight of a neuron has one sign). Inhibitory weights scaled so the network is roughly balanced and neither dies nor saturates. `n` accepted in [1000, 5000]. Must build in well under 2 seconds at n=5000; vectorize.
- Layout: first 512 neurons are sensory. Seven motor pools of 24 neurons each at the END of the index range, named after real descending-neuron classes as flavour:
  - UP = forward walk (DNp09), DOWN = backward walk (MDN, moonwalker), LEFT / RIGHT = turning (DNa02, left and right), A = interact / proboscis-reach (DNg), B = withdraw/cancel, START = pause (grooming bout).
- Retinotopic bias so behaviour is not pure noise: motion on the left of the visual field drives LEFT turning (flies turn toward small moving objects), motion on the right drives RIGHT, top drives UP, bottom drives DOWN. Central/overall change drives A weakly. Implement as a few extra sparse sensory->interneuron->pool pathways, not direct sensory->motor wires, so signals still propagate through the hidden network.
- Mutual inhibition between opposing pools (UP vs DOWN, LEFT vs RIGHT) so the fly commits to a direction.
- `from_edge_list(csv_path, ...)`: loader for a real connectome export with columns `pre,post,weight[,sign]`. Remaps ids to 0..N-1, assigns sensory and motor pools by in/out-degree heuristics documented in the docstring. This is a hook for later, keep it under ~60 lines, test it with a tiny CSV fixture. No FlyWire download code.

### brain.py
- Leaky integrate-and-fire, fully vectorized, float32. Per step: `v += dt/tau * (v_rest - v) + W @ spikes_prev + input`; spike where `v >= v_thresh`; reset to `v_reset`; refractory counter (2-3 steps). One brain step per emulator tick.
- `step(sensory_current: np.ndarray) -> np.ndarray` (bool spikes, N). `firing_rate` property: fraction of neurons that spiked, exponentially smoothed for the HUD.
- Must sustain 60 Hz at n=2000 with room to spare on a normal desktop. Dense `W @ spikes` via `W[:, spiking_idx].sum(axis=1)` is fine and faster than a full matmul when spiking is sparse. Measure it; put the measured ms/step for n=2000 and n=5000 in the README.
- Sanity target, enforced by a test: driven by random frames for 600 steps, mean firing rate stays between 0.5% and 30% and every motor pool fires at least once.

### motor.py
- Each pool has a leaky accumulator of its spike count. When it crosses `fire_threshold`, press that button for exactly 4 frames, then release, then a short per-button cooldown (about 8 ticks) so the game registers distinct presses. Accumulator resets on fire.
- At most one directional button held at a time (strongest pool wins); A/B/START may overlap a direction but not each other.
- Anti-stuck panic reflex: track `(map_id, x, y)` and the last button fired. If neither position nor the chosen action has changed for 200 ticks, fire a panic burst: 6-10 random buttons in sequence (each 4 frames, drawn from all seven, weighted toward directions and A), and inject a transient current pulse into the brain so the HUD shows the startle. Counter resets afterwards. Seeded RNG.
- `update(spikes, position) -> str | None` returns the action that started this tick (or `"PANIC"`), for the HUD.
- MotorBridge talks to the emulator through a two-method protocol (`press`, `release`) so tests use a fake.

### hud.py
- In-place redraw with ANSI escapes (cursor home + clear lines), stdlib only, refreshed every 6 ticks. On Windows enable VT processing (`os.system("")` is enough). `--no-hud` falls back to one plain log line per second.
- Shows: step count, ticks/sec, smoothed firing rate (% and a small bar), per-pool activation bars for all seven pools, current action, last 8 actions, map id, X, Y, in-battle flag, panic count.
- Ctrl+C exits cleanly: release all buttons, close the emulator, restore the cursor.

### run.py
`python run.py` with no arguments must work: it finds `roms/pokemon_red.gb` relative to itself. Flags: `--rom PATH`, `--neurons N` (default 2000), `--seed`, `--uncapped`, `--headless`, `--no-hud`, `--max-steps N` (0 = forever), `--connectome CSV`, `--load-state PATH` and `--save-state PATH` (PyBoy savestates, so a run can start past the intro).
Missing ROM: print exactly where to put the file and exit 2. Do not stack-trace.

## Tests (pytest, all headless)
- optic_lobe: shape, first-frame zero delta, ON/OFF split on a synthetic brightening frame.
- connectome: size, no self loops, Dale's law holds, pools disjoint and the right size, deterministic under a seed, builds under 2 s at n=5000, edge-list loader on a tiny CSV.
- brain: the firing-rate sanity target above; determinism under a seed.
- motor: 4-frame hold then release (fake emulator records calls), cooldown, one direction at a time, panic fires at 200 stuck ticks and not at 199, panic resets.
- integration: if `roms/pokemon_red.gb` exists, run 600 ticks headless (`window="null"`) through the real loop with `--max-steps`, assert no exception, at least one button press, position readable. Skip when the ROM is absent.

## Definition of done
1. `.venv` created, dependencies installed, `pytest -q` green. Paste the output.
2. `python run.py --headless --uncapped --no-hud --max-steps 3000` runs to completion against the real ROM. Paste the final log lines.
3. `python run.py --max-steps 600` (windowed) opens a window and exits cleanly. If SDL2 cannot open in your shell, say so plainly rather than claiming it worked.
4. README is accurate to what was built, including honest expectations: this is a motion-driven random walker, not a competent player.
5. One git commit of everything except `.venv` and `roms/`. Do not push anywhere.
6. Final report: what was built, measured ms/step, test output, anything that deviates from this contract and why, anything unverified.

## Rules
- Tuning numbers live in `config.py`, not scattered.
- If the network dies or saturates, tune weights/gain/threshold until the sanity test passes. Do not loosen the test.
- No em dashes in prose. No filler.
- Do not touch anything outside `C:\Users\aidan murphy\fly-brain-pokemon`.
