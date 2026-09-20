# fly-brain-pokemon

A simulated fly brain plays Pokemon Red. A 2000-neuron leaky integrate-and-fire
network watches the Game Boy screen through a fly-style optic lobe and presses
buttons with seven "descending neuron" motor pools, through PyBoy.

It is not a competent player. It is a motion-driven random walker with a
visual bias: motion on the left of the screen pushes the left-turn pool, motion
on the right pushes the right-turn pool, and so on. It has no memory of the
game, no reward, no learning, and no idea what a Pokemon is. Watch it for the
behaviour, not the progress.

That said, it does get somewhere. In a 60,000-step headless run from a cold
boot it pressed through the intro and the name entry, walked around Red's
bedroom, found the stairs, and went up and down them eleven times. It never got
out of the house. See "What actually happened" below.

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
readable.

Two things about the lattice are not obvious and both were found by measurement,
not by design:

- **The ring is built over positions, then a seeded permutation maps position to
  neuron id.** That leaves it the same Watts-Strogatz graph, but without it the
  ring is aligned with the functional layout below, and since the sensory block
  and the motor block are contiguous and both excitatory, each becomes a
  self-exciting clique. Measured: the UP pool was taking +2.78 of pure
  excitation from the other motor neurons and saturating at 20% whatever was on
  screen.
- **Inhibitory synaptic scaling.** Each neuron's incoming inhibition is rescaled
  so every neuron gets the same net lattice drive. With 20 incoming synapses and
  a 3.5:1 inhibitory-to-excitatory magnitude ratio, excitability otherwise comes
  down to how many inhibitory partners a neuron happened to draw, and across a
  24-neuron pool that does not average out. Measured without it, a pool's rate
  against its opposite ran from 0.80 to 2.20 across seeds, correlating +0.85 to
  +0.91 with the gap in their incoming weight sums. Only magnitudes move, never
  a sign, so Dale's law is untouched.

Index layout:

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
  runs through 24 hidden interneurons that pool 128 channels of their region,
  the way a lobula plate tangential cell pools a hemifield, so the signal still
  has to propagate through the recurrent network. Those interneurons keep only
  15% of their ordinary lattice input (`bias_lattice_scale`): a neuron needs a
  total input near `leak * v_thresh` to sit at threshold, while 20 lattice
  synapses fluctuate several times that, so at full strength the regional signal
  is buried and every pool responds identically whatever is on screen.
- **Crossed inhibition.** UP inhibits DOWN and LEFT inhibits RIGHT (both ways),
  routed through real inhibitory interneurons rather than a negative
  pool-to-pool wire, so the pools themselves stay excitatory and Dale's law is
  not bent to get the mutual inhibition. This is the amplifier that turns a 1.2x
  difference in regional drive into a clear turning preference. It is also the
  most dangerous number in the file: at roughly three times its current strength
  the pair latches and whichever side wins first stays won whatever the screen
  does.

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

**Motor** (`motor.py`). Each pool keeps two running averages of its own spike
count: a fast leaky accumulator (tau of a few ticks) and a slow baseline (tau of
about 300 ticks) holding the level its recent average drive would sustain. A
button fires when the **excursion**, `accum - baseline`, crosses
`fire_threshold * threshold_scale[pool]`. So a press means "this pool is more
active than it usually is", which is what visual motion and network fluctuations
produce, rather than "this pool is active", which every pool is, all the time.

That adaptation is the whole point. On an absolute threshold every pool sat far
above it and each button fired once per hold plus cooldown forever, so the
cooldown timer was playing the game and START reopened the menu every 12 ticks.
The baseline is computed from the spike counts and not from the accumulator, so
resetting the accumulator on a fire cannot drag its own baseline down after it
and stall the pool. `threshold_scale` makes START rare (2.2x) and B a little
above A (1.25x).

The press itself: held for exactly 4 ticks, released, then an 8-tick per-button
cooldown so the game registers distinct presses. At most one direction is held
at a time (the largest margin over its own threshold wins) and at most one of
A/B/START, but an action may overlap a direction.

The anti-stuck reflex: the fly startles if `(map_id, x, y)` has not changed for
200 ticks, **or** if no button at all has been pressed for 200 ticks. A burst of
6 to 10 random buttons (weighted toward directions and A) is queued and played
out one at a time, and a transient current pulse is injected into the brain so
the startle shows on the HUD as a firing-rate jump. Both counters restart from
zero afterwards. It fires during long dialogues and the intro, which is the
intent: a startled fly mashing its way out of a text box.

**HUD** (`hud.py`). In-place ANSI redraw every 6 ticks: step count, ticks/sec,
smoothed firing rate with a bar, each pool's excursion above its own baseline as
a share of its own threshold, the button currently held, the last 8 actions, the
map name and id, X, Y, the in-battle flag and the panic count. `--no-hud` prints
one line per second instead, which is what you want when piping to a file.

Map ids are named from a small table in `config.py` covering Pallet Town, the
ten other towns and cities, Routes 1 and 2, Red's house and Oak's Lab. Anything
else prints as its raw number rather than a guess. Note that the map-id address
reads 0 before the game writes to it, so a "Pallet Town" at the very start of a
cold-boot run is uninitialised RAM, not a place the fly has been.

Every tunable number lives in `config.py`, one frozen dataclass, with a comment
per number. Nothing else in the package hard-codes a magic number.

## Measured performance

Brain step, best of three runs of 500 steps each, on this machine (Windows 11,
Python 3.13, numpy 2.5.3):

| network size | ms per brain step | headroom at 60 Hz |
|---|---|---|
| n = 2000 | **0.23 ms** | 72x |
| n = 5000 | **0.45 ms** | 37x |

Whole loop including emulation, the frame read and the motor logic: about
1,550 to 1,950 ticks/s headless and uncapped, so roughly 26x to 32x real time.
Windowed it holds 60.1 ticks/s, which is the real-time cap, not a limit of the
brain.

## What actually happened

`run.py --headless --uncapped --no-hud --max-steps 3000` from a cold boot:

```
done: 3000 steps in 1.94s (1547.1 ticks/s), firing 10.59%
presses: UP=99 DOWN=85 LEFT=87 RIGHT=98 A=66 B=26 START=7  total=468  panics=11
positions: 2 distinct (map_id, x, y); moved=True; final=(38, 3, 6)
maps: Pallet Town (0), Red's house 2F (38)
route (map ids, in order entered): 0 -> 38
```

3000 ticks is 50 seconds of game time, which is not enough to clear the intro,
the title screen, Oak's speech and name entry. The leading map 0 there is the
uninitialised RAM value, not Pallet Town.

60,000 ticks, sixteen minutes of game time:

```
done: 60000 steps in 31.1s (1929.4 ticks/s), firing 8.64%
presses: UP=1030 DOWN=977 LEFT=935 RIGHT=832 A=309 B=52 START=11  total=4146  panics=28
positions: 60 distinct (map_id, x, y); moved=True; final=(37, 3, 3)
maps: Pallet Town (0), Red's house 1F (37), Red's house 2F (38)
route (map ids, in order entered): 0 -> 38 -> 37 -> 38 -> 37 -> 38 -> 37 -> 38 -> 37 -> ...
```

The fly cleared the intro and the name entry, explored Red's bedroom, found the
stairs and went up and down them eleven times. **It never left the house.**

Where it spent its time, from the same run:

| map | ticks | tiles seen | x range | y range |
|---|---|---|---|---|
| Red's house 2F | 50,812 | 42 | 0 to 7 | 1 to 7 |
| Red's house 1F | 8,334 | 17 | 2 to 7 | 1 to 4 |

Upstairs it covered essentially the whole room. Downstairs it only ever reached
y=4, and the front door is at the bottom of that room. The reason is in those
two tables rather than in the press log, which is close to even: the staircase
drops the fly into the top-right corner of 1F (its most-visited tile there,
(7,1), 1,161 ticks), and an unbiased walker that starts next to the staircase
finds the staircase again long before it finds a single door tile at the far
end. Each visit to 1F averaged about 750 ticks, twelve seconds, which is not
long enough to cross the room by chance.

Nothing is going to fix that except a goal, and this fly does not have one.

The panic reflex fired 11 times in the first 3,000 ticks and 28 times over
60,000. That distribution is the point: it fires constantly during the intro and
the long text boxes, where the player cannot move, and rarely once the fly is
walking around a room.

## Honest expectations

- It will not beat the game. It has no goal, no reward and no memory.
- It presses about one button every 14 ticks, and no single button runs at more
  than 40% of the rate its hold plus cooldown would allow. Raise
  `fire_threshold` in `config.py` for a calmer fly.
- Direction choice is real: a bright block moving inside one third of the screen
  biases the matching pool by 2.3x to 3.9x over its opposite, measured through
  the whole chain in `tests/test_behaviour.py`. In actual gameplay the screen is
  far less cooperative than that test stimulus and the directional counts come
  out close to even.
- Firing rate sits around 8 to 10% across black screens, bright screens, static
  screens, per-pixel noise and coarse moving blocks. A test pins it inside 0.5%
  to 30% on the last two and requires every motor pool to fire; the numbers in
  `config.py` were tuned until that passed, not the other way round.

## Tests

```powershell
& .\.venv\Scripts\python.exe -m pytest -q
```

53 tests, all headless, about 15 seconds. They pass with no ROM present except
`tests/test_integration.py::test_600_headless_ticks_through_the_real_loop`,
which skips when `roms/pokemon_red.gb` is absent.

`tests/test_behaviour.py` is the one that matters most: it runs the whole optic
lobe to brain to motor chain with a fake button sink and holds it to two things
that no unit test can see. No button may exceed 40% of the rate its hold plus
cooldown allows, and a bright block wandering inside one third of the screen has
to bias the matching pool by at least 1.5x over its opposite, in all four
directions, summed over three seeds.

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
- The ring lattice is built over positions and permuted onto neuron ids, and
  each neuron's incoming inhibition is rescaled to equalise net drive. Both are
  additions to the spec's connectome description, both are explained above, and
  both were added because the retinotopy measurably did not work without them.
- With no position reading at all (a test harness rather than the game) the
  anti-stuck reflex's position counter does not run, because nothing is known
  about being stuck. Only the idle counter can fire it there.
- The map-name table covers only ids worth being sure about. Everything else
  prints as a number.

## Licence and dependencies

`pyboy`, `numpy`, `pillow`, `opencv-python`; `pytest` for tests. Nothing else.
