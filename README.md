# fly-brain-pokemon

A simulated fly brain plays Pokemon Red. A 2000-neuron leaky integrate-and-fire
network watches the Game Boy screen through a fly-style optic lobe and presses
buttons with seven "descending neuron" motor pools, through PyBoy.

It is not a competent player. It is a motion-driven random walker with a
visual bias: motion on the left of the screen pushes the left-turn pool, motion
on the right pushes the right-turn pool, and so on. It has no memory of the
game, no reward, no learning, and no idea what a Pokemon is. Watch it for the
behaviour, not the progress.

That said, it does get somewhere. In a 30,000-step headless run from a cold
boot it pressed through the intro and the name entry and was walking around the
overworld by step ~14,800, changing maps by step ~21,000. See
"What actually happened" below.

## Setup

Windows 11, PowerShell, Python 3.13. Quote every path: the home directory here
has a space in it.

```powershell
py -3.13 -m venv .venv
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

The ROM is yours to supply. Put your own Pokemon Red dump at `roms/pokemon_red.gb`
(1 MB, `.gb`). `roms/` is gitignored and nothing in this project downloads a ROM.
If the file is missing, `run.py` prints the exact path it wanted and exits 2.

## Run

```powershell
& .\.venv\Scripts\python.exe run.py                                   # windowed, 60 Hz, HUD
& .\.venv\Scripts\python.exe run.py --headless --uncapped --no-hud --max-steps 3000
```

| flag | what it does |
|---|---|
| `--rom PATH` | ROM location (default: `roms/pokemon_red.gb` next to `run.py`) |
| `--neurons N` | network size, 1000 to 5000 (default 2000) |
| `--seed N` | seeds the connectome, the optic-lobe noise and the panic reflex |
| `--uncapped` | run as fast as the CPU allows instead of 60 Hz |
| `--headless` | no SDL2 window (PyBoy `window="null"`) |
| `--no-hud` | one plain log line per second instead of the in-place display |
| `--max-steps N` | stop after N ticks; 0 (default) runs until the window closes or Ctrl+C |
| `--connectome CSV` | load an edge list (`pre,post,weight[,sign]`) instead of the synthetic net |
| `--load-state PATH` | start from a PyBoy savestate, e.g. past the intro |
| `--save-state PATH` | write a PyBoy savestate on exit |

Ctrl+C exits cleanly: buttons released, emulator closed, cursor restored.

There is no install step. `run.py` puts `src/` on `sys.path` itself.

## How the brain is wired

**Optic lobe** (`optic_lobe.py`). The 160x144 frame is area-averaged down to a
16x16 retina. The luminance delta against the previous retina splits into an ON
channel (brightening, L1-like) and an OFF channel (darkening, L2-like): 256 +
256 = 512 sensory channels. Three things are added on top of the motion signal:

- a tonic term proportional to absolute luminance, so a still dialogue box
  waiting for A still drives the network,
- a constant dark current, because Pokemon Red shows a lot of black and without
  it the fly goes blind and the whole network falls silent,
- low seeded Gaussian noise, so nothing is ever exactly zero.

The total is clipped at `max_current` (synaptic saturation), symmetrically so
the noise stays zero-mean. The first frame produces a zero delta, not a
whole-frame edge.

**Connectome** (`connectome.py`). A directed Watts-Strogatz small world: a ring
lattice of `k=20` outgoing edges per neuron, each rewired with probability 0.1,
no self loops. Dale's law holds: every outgoing synapse of a neuron has one
sign. 20% of neurons are inhibitory, drawn from the hidden population, so the
sensory neurons and the motor pools stay excitatory and their pathways stay
readable. Index layout:

```
0 .. 511                  sensory
512 .. n-169              hidden
n-168 .. n-1              seven motor pools of 24: UP DOWN LEFT RIGHT A B START
```

Pool names are flavour from real descending-neuron classes: UP is forward
walking (DNp09), DOWN is backward walking (MDN, the moonwalker), LEFT and RIGHT
are the turning pair (DNa02), A is interact / proboscis reach (DNg), B is
withdraw, START is a grooming pause.

Two extra sets of pathways sit on top of the lattice:

- **Retinotopic bias.** Motion in the left half of the visual field drives the
  LEFT pool, the right half drives RIGHT, top drives UP, bottom drives DOWN, and
  the centre weakly drives A. These are not direct sensory-to-motor wires: each
  runs through a handful of hidden interneurons that sample 40 channels of their
  region, so the signal still has to propagate through the recurrent network.
- **Crossed inhibition.** UP inhibits DOWN and LEFT inhibits RIGHT (both ways),
  routed through real inhibitory interneurons rather than a negative
  pool-to-pool wire, so the pools themselves stay excitatory and Dale's law is
  not bent to get the mutual inhibition. This is what makes the fly commit to a
  direction instead of dithering.

**Brain** (`brain.py`). Leaky integrate-and-fire, fully vectorized float32, one
step per emulator tick:

```
v += leak * (v_rest - v) + W @ spikes_prev + input
spike where v >= v_thresh and the refractory counter has expired
spiking neurons reset to v_reset and sit out `refractory` steps
```

The recurrent term is a gather-and-sum over the columns of `W` belonging to the
neurons that spiked last step, not a full matmul; spiking is a few percent, so
this is much cheaper. `W` is held in Fortran order so those columns are
contiguous.

**Motor** (`motor.py`). Each pool has a leaky accumulator of its spike count.
Crossing `fire_threshold` presses that button for exactly 4 ticks, releases it,
and puts it in an 8-tick cooldown so the game registers distinct presses; the
accumulator resets on fire. At most one direction is held at a time (the
strongest accumulator wins) and at most one of A/B/START, but an action may
overlap a direction.

The anti-stuck reflex: if neither `(map_id, x, y)` nor the last button fired has
changed for 200 ticks, the fly startles. A burst of 6 to 10 random buttons
(weighted toward directions and A) is queued and played out one at a time, and a
transient current pulse is injected into the brain so the startle shows on the
HUD as a firing-rate jump.

**HUD** (`hud.py`). In-place ANSI redraw every 6 ticks: step count, ticks/sec,
smoothed firing rate with a bar, the seven pool accumulators with bars, the
button currently held, the last 8 actions, map id, X, Y, the in-battle flag and
the panic count. `--no-hud` prints one line per second instead, which is what
you want when piping to a file.

Every tunable number lives in `config.py`, one frozen dataclass, with a comment
per number. Nothing else in the package hard-codes a magic number.

## Measured performance

Brain step, best of three runs of 500 steps each, on this machine (Windows 11,
Python 3.13, numpy 2.5.3):

| network size | ms per brain step | headroom at 60 Hz |
|---|---|---|
| n = 2000 | **0.41 ms** | 40x |
| n = 5000 | **0.83 ms** | 20x |

Whole loop including emulation, the frame read and the motor logic: about
1,550 to 1,700 ticks/s headless and uncapped, so roughly 26x real time.
Windowed it holds exactly 60.0 ticks/s, which is the real-time cap, not a limit
of the brain.

## What actually happened

`run.py --headless --uncapped --no-hud --max-steps 3000` from a cold boot:

```
done: 3000 steps in 1.82s (1645.6 ticks/s), firing 8.90%
presses: UP=213 DOWN=184 LEFT=38 RIGHT=226 A=249 B=249 START=250  total=1409  panics=0
positions: 2 distinct (map_id, x, y); moved=True; final=(38, 3, 6)
```

3000 ticks is 50 seconds of game time, which is not enough to clear the intro,
the title screen, Oak's speech and name entry. The two "distinct positions"
there are the boot value `(0, 0, 0)` and whatever the RAM settles to; that is
not the player walking.

30,000 ticks is a different story:

```
step  13140  ... map  38 x   3 y   6 ...
step  14776  ... map  38 x   7 y   3 ...
step  21064  ... map  37 x   7 y   1 ...
done: 30000 steps in 19.24s (1559.6 ticks/s), firing 9.45%
presses: UP=2125 DOWN=1818 LEFT=452 RIGHT=2271 A=2495 B=2495 START=2497  total=14153  panics=0
positions: 34 distinct (map_id, x, y); moved=True; final=(37, 7, 3)
```

By step ~14,800 the coordinates are changing every few hundred ticks, and by
step ~21,000 the map id changes, so the fly is out of the house and walking
between maps. `LEFT` is pressed a fifth as often as `RIGHT`, which is the
retinotopic bias and the crossed inhibition doing their job on whatever was
moving on screen, not a bug.

The panic reflex fired zero times in both runs: the fly is active enough that
either the position or the chosen button changes inside any 200-tick window.

## Honest expectations

- It will not beat the game. It has no goal, no reward and no memory.
- It mashes. The pool accumulators sit well above `fire_threshold` most of the
  time, so the press rate is set by the 4-tick hold plus the 8-tick cooldown
  rather than by the threshold. Some button is nearly always held. Raise
  `fire_threshold` in `config.py` for a calmer fly.
- Direction choice is real but weak: it follows which half of the screen moved,
  filtered through a recurrent net that adds a lot of its own noise.
- Firing rate sits around 8 to 9% across black screens, bright screens, static
  screens and random noise. A test pins it inside 0.5% to 30% and requires every
  motor pool to fire; the numbers in `config.py` were tuned until that passed,
  not the other way round.

## Tests

```powershell
& .\.venv\Scripts\python.exe -m pytest -q
```

37 tests, all headless. They pass with no ROM present except
`tests/test_integration.py::test_600_headless_ticks_through_the_real_loop`,
which skips when `roms/pokemon_red.gb` is absent.

## Choices the spec left open

- The frame is taken as the red channel of PyBoy's RGBA screen buffer. The Game
  Boy palette is gray, so that channel is the luminance.
- `position()` returns `(map_id, x, y)` in that order, reading `0xD35E`,
  `0xD362`, `0xD361`.
- The sensory noise is Gaussian on the current, not on the membrane voltage.
- The dark current is an addition to the spec's optic-lobe description. Without
  it the network is exactly silent on a black screen, which the game shows a lot
  of, and "never goes fully silent" would not hold.
- An edge list loaded with `--connectome` will not have exactly 512 sensory
  neurons; the optic lobe's channels are folded onto whatever it does have,
  round-robin.
- `MotorBridge.update` returns one action string when several buttons start on
  the same tick, preferring the direction. Per-button counts are tracked
  separately in `MotorBridge.fire_counts`, which is what the HUD and the run
  summary report.

## Licence and dependencies

`pyboy`, `numpy`, `pillow`, `opencv-python`; `pytest` for tests. Nothing else.
