# fly-brain-pokemon

A simulated fly brain plays Pokemon Red. A 2000-neuron leaky integrate-and-fire
network watches the Game Boy screen through a fly-style optic lobe and presses
buttons with seven "descending neuron" motor pools, through PyBoy.

On top of that sits a **mushroom body**: the circuit a real fly learns with. A
sparse Kenyon-cell code of the static screen feeds seven MBONs, one per motor
pool, and a value readout. A dopamine signal built from a TD error over
RAM-derived reward gates plasticity on those readouts and nothing else. The
spiking connectome underneath never changes: it stays reflexes plus exploration
noise, and the learned part is a place-dependent bias on top of it.

The untrained fly is a motion-driven random walker. It walks around Red's
bedroom, finds the stairs, and goes up and down them. In ten evaluation
episodes it left the house **0 times**. After 2,000,000 ticks of training the
same fly, same seeds, learning switched off, left the house **10 times out of
10**, and four of those ten got inside a building in Pallet Town.

That is the whole result. See "The experiment" for the raw numbers, and "What
it cannot learn" for the ceiling, which is low.

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
& .\.venv\Scripts\python.exe run.py --start-state                     # from the bedroom savestate
& .\.venv\Scripts\python.exe run.py --naive --start-state             # the untrained fly, for comparison
& .\.venv\Scripts\python.exe run.py --headless --uncapped --no-hud --max-steps 3000
```

`run.py` loads `brains/latest.npz` when that file exists and prints one line
saying which brain it loaded and how long it trained. `--naive` ignores it.

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
| `--start-state` | shorthand for `--load-state states/bedroom.state` |
| `--save-state PATH` | write a PyBoy savestate on exit |
| `--brain PATH` | load this mushroom body instead of `brains/latest.npz` |
| `--naive` | ignore any saved brain: the untrained fly |
| `--learn` | keep learning while you watch |
| `--save-brain` | with `--learn`, write the brain back on exit |

Ctrl+C exits cleanly: buttons released, emulator closed, cursor restored.

There is no install step. `run.py` puts `src/` on `sys.path` itself.

## Watch it on the couch

```powershell
& .\.venv\Scripts\python.exe run.py --couch --start-state
```

A browser tab opens on `http://127.0.0.1:8765/` with a small 3D living room:
the fly sits on a couch holding a controller and the CRT in front of it shows
the live game. The emulator runs headless at 60 Hz (add `--window` to keep the
SDL2 window too); the terminal HUD stays. Every other flag works with it
(`--brain`, `--naive`, `--learn`, `--uncapped`). `--couch-port N` moves the
server, `--no-browser` skips opening the tab. Ctrl+C stops the run and frees
the port.

| what you see | what it means |
|---|---|
| a control on the pad goes down and the front leg pokes it | that button is being pressed right now; the d-pad tilts the way the fly is walking |
| the glow inside the head | the share of neurons firing; brighter is busier |
| the glow flashes gold, antennae perk up | dopamine: something went better than expected (a new tile, a new room) |
| the glow goes cold blue, antennae droop | worse than expected |
| wings buzz, the fly hops, the camera shakes | the panic reflex (stuck for 200 ticks) |
| the front legs rub together | START fired (a grooming bout) |
| the fly leans in | a battle |
| the box by the couch | a live spike raster: seven coloured rows are the motor pools, the band below is 200 other neurons; the bars on top are the seven learned biases |
| the room brightens and dims | the TV is the key light and follows the game picture |

Keys: `1` living room, `2` the TV, `3` the fly, `4` the brain monitor, drag to
orbit, wheel to zoom, right-drag to pan, `R` reset, `G` Game Boy green or
plain gray, `H` hide the panel. The scene is plain ES modules on a vendored
copy of three.js (`scene/vendor/`, MIT), served by a stdlib HTTP server with a
hand-written WebSocket (`src/flybrain/couch.py`); there is no build step and no
new Python dependency. `scene/PROTOCOL.md` documents the messages,
`scene/REVIEW.md` is the visual checklist.

## Train

```powershell
& .\.venv\Scripts\python.exe train.py                        # 2,000,000 ticks, 100 episodes
& .\.venv\Scripts\python.exe train.py --ticks 5000000 --resume
& .\.venv\Scripts\python.exe train.py --evaluate-naive       # the 10-episode baseline
& .\.venv\Scripts\python.exe train.py --evaluate brains\latest.npz
```

Every episode starts from `states/bedroom.state`, a savestate in Red's bedroom
with the player in control. `train.py` makes it the first time it is missing,
by running the **untrained** fly from a cold boot until it is standing in the
bedroom and has moved twice. Nothing about that is scripted; it took 5,039
ticks here. `--make-start-state` does only that and stops.

| flag | what it does |
|---|---|
| `--ticks N` | total tick budget (default 2,000,000) |
| `--episode-ticks N` | ticks per episode (default 20,000) |
| `--seed N` | episode seeds derive from this |
| `--out PATH` | where the brain is written (default `brains/latest.npz`) |
| `--resume` | continue from the brain at `--out` |
| `--eval-every K` | run a learning-off evaluation episode every K episodes |
| `--log PATH` | one CSV row per episode (default `runs/train.csv`) |
| `--state PATH` | the start savestate |
| `--make-start-state` | write the start savestate and stop |
| `--evaluate PATH` / `--evaluate-naive` | skip training, run the evaluation block |

The brain is checkpointed every ten episodes and on Ctrl+C, so an interrupt
never loses a run. `brains/`, `states/` and `runs/` are gitignored.

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

The same downsample is exposed as `OpticLobe.retina`, and that is what the
mushroom body reads. One `cv2.resize` per tick, one definition of what the fly
sees: the spiking net gets the motion, the learned part gets the still picture.

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

`step` takes an optional `pool_current`, seven numbers added to every neuron of
the matching motor pool. That is the mushroom body's only way in, and it is a
real input current to real neurons rather than a shortcut around them: the pool
still has to reach threshold, and a learned bias still has to beat the reflex
and the crossed inhibition from its opposite. A test asserts that a pool current
moves exactly the 24 membrane voltages of its own pool and nothing else.

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

Each tick's presses are reported split two ways, `chosen` and `panicked`. The
mushroom body writes eligibility only for `chosen`: crediting a panic burst
would teach the fly whatever the random draw happened to be.

**Mushroom body** (`mushroom_body.py`). The only part that learns.

```
static 16x16 luminance (256)
  -> Kenyon cells: 2000 cells, 7 claws each, random signed weights, top 5% active
  -> 7 MBONs (one per motor pool)  -> mbon_gain * tanh(mbon) as a current into that pool
  -> 1 value readout               -> the TD error that gates plasticity
```

The retina is the same one the optic lobe already computed, read from
`OpticLobe.retina`, so the frame is downsampled once. Its mean is subtracted
first: the code is about the pattern on screen, not the backlight.

Why this and not reward-modulated STDP over the whole recurrent net: credit
assignment through recurrence with a delayed scalar reward does not converge in
the number of ticks available here. The fly's own answer is a feedforward
expansion into a sparse code, with plasticity confined to one synapse layer.
Only `w_actor` (7 x 2000) and `w_critic` (2000) ever change. The connectome is
untouched.

Plasticity is three-factor: a KC was active, a pool was chosen, and dopamine
says whether that was better than expected. The first two live in eligibility
traces, the third arrives a few ticks later and multiplies what is left:

```
delta   = r + gamma * V(s') - V(s)
e_actor = lambda_actor * e_actor;   on a press of pool a: e_actor[a, kc] += 1, the other six -= 1/6
e_critic= lambda_critic * e_critic; e_critic[kc] += 1
w_actor  += lr_actor  * delta * e_actor
w_critic += lr_critic * delta * e_critic
```

The `-1/6` makes an update a preference shift between pools rather than a change
in how loudly the whole body shouts: the seven rows of `e_actor` sum to zero, so
a uniform dopamine level cannot inflate every pool at once. Panic-burst presses
write no eligibility, because the fly did not choose them.

The MBON output is squashed, so a learned preference can tilt a pool but never
pin it: it still has to win against the reflex, the network noise and the
crossed inhibition from its opposite. Signed is deliberate; real MBONs come in
approach and avoidance types.

**`lr_critic` is the most sensitive number in the project and it looks wrong.**
It is 5e-5 against the actor's 2e-3. An update writes to all 100 active KCs at
once, and a critic trace whose KC keeps being active saturates at
`1/(1-lambda_critic)` = 50, so the step on the value readout is about 5000 times
`lr_critic`. At the obvious 2e-3 the value estimate swings by tens per tick, the
TD error is then noise rather than a teaching signal, and the actor random-walks
into its weight clip: measured in the two-context test world, that gave LEFT the
*most negative* weight in the context where LEFT was the only thing that paid.
Dropping `lr_critic` alone took that test from a 0.58 share to 0.87.

**Reward** (`reward.py`). RAM in, a scalar out, and the policy never sees any of
it: in Pokemon the player is always screen-centred, so the frame is an egocentric
view of the map and identifies place on its own.

| part | weight | what it is |
|---|---|---|
| tile | +1 | a (map, x, y) not stood on this episode |
| map | +5 | a map id not entered this episode |
| event | +3 | each newly set bit in `wEventFlags` |
| level | +5 | each party level gained |
| badge | +50 | each badge |

Nothing the fly can trigger without progressing pays anything. Opening the menu,
advancing text and turning on the spot are free, and the staircase cannot be
farmed: the second trip down pays nothing and neither do the tiles it already
saw. That matters, because going up and down the stairs is exactly what the
untrained fly does for sixteen minutes at a time.

Every address was read out of the pret/pokered symbol file (`symbols` branch,
`pokered.sym`) rather than remembered, and each one is in `config.py` with its
pokered symbol name: `wPartyCount` 0xD163, `wPartyMon1Level` 0xD18C with a 0x2C
stride, `wObtainedBadges` 0xD356, `wEventFlags` 0xD747 through 0xD886 inclusive
(the next symbol is `wGrassRate` at 0xD887), `wIsInBattle` 0xD057, `wCurMap`
0xD35E, `wYCoord` 0xD361, `wXCoord` 0xD362, `wPlayerName` 0xD158, `wJoyIgnore`
0xCD6B.

"Has control" is two concrete conditions: the player has a name (`wPlayerName[0]`
is not 0x00, 0x50 or 0xFF), and `wJoyIgnore` is zero. The first is what keeps the
uninitialised `wCurMap` of 0 at boot from being scored as a walk into Pallet
Town; the second drops cutscenes and map transitions, where the engine is
swallowing input and the fly is not the one doing anything.

**Observers** (`loop.py`). `run_loop(config, observers=())` calls every observer
with one immutable `TickState` per tick: step, frame, buttons held, the press
that started, pool excursions, firing rate, dopamine, value, the seven MBONs,
reward and its parts, episode reward, map id and name, x, y, in-battle, panic.
The HUD is the first observer. This is the hook a 3D scene would attach to; there
is nothing else in it yet, no sockets and no rendering.

**HUD** (`hud.py`). In-place ANSI redraw every 6 ticks: step count, ticks/sec,
smoothed firing rate with a bar, the dopamine signal on a signed bar, the value
estimate, the episode reward and its parts, each pool's excursion above its own
baseline as a share of its own threshold with that pool's MBON bias beside it,
the button currently held, the last 8 actions, the map name and id, X, Y, the
in-battle flag, the panic count, the per-button press counts, and a top line
naming the brain that is driving. `--no-hud` prints one line per second instead,
which is what you want when piping to a file.

Map ids are named from a small table in `config.py` covering Pallet Town, the
ten other towns and cities, Routes 1 and 2, Red's house and Oak's Lab. Anything
else prints as its raw number rather than a guess. Note that the map-id address
reads 0 before the game writes to it, so a "Pallet Town" at the very start of a
cold-boot run is uninitialised RAM, not a place the fly has been.

Every tunable number lives in `config.py`, one frozen dataclass, with a comment
per number. Nothing else in the package hard-codes a magic number.

## Measured performance

Best of three runs of 400 steps each, on this machine (Windows 11, Python 3.13,
numpy 2.5.3), idle:

| piece | ms per tick |
|---|---|
| spiking brain, n = 2000 | **0.27 ms** (v1 measured 0.23) |
| spiking brain, n = 5000 | **0.45 ms** (v1 measured 0.45) |
| mushroom body: KC code, both readouts, weight update, both traces | **0.09 ms** |

The contract's budget for the learning layer is 0.3 ms per tick at
`n_kc = 2000`. It costs 0.09 ms idle and 0.12 ms with another process competing
for cores, and a test fails the build if it ever goes over 0.30. The whole thing
is four dense operations on a (7, 2000) array per tick, so what is being
measured is numpy call overhead, not arithmetic.

Whole loop, headless and uncapped, including emulation, the frame read, the RAM
snapshot, the mushroom body and the motor logic:

| condition | ticks/s |
|---|---|
| idle machine, `run.py --headless --uncapped --start-state` | **1,558** |
| evaluation episodes | 1,000 to 1,400 |
| averaged over the whole 44-minute training run | **757** |

The spread is contention: another project's server was running for most of the
training. v1 measured 1,550 to 1,950 without the learning layer, so the
mushroom body costs roughly what the table above says it costs and nothing more.
The emulator tick is the bottleneck, and this round leaves it alone as the
contract says to. 2,000,000 ticks of training is 44 minutes of wall clock and
about nine hours of game time.

## The experiment

Ten evaluation episodes of 20,000 ticks each, from `states/bedroom.state`, with
learning OFF, seeds 90000 to 90009. The same ten seeds for both flies. "Reached
Pallet Town" means map 0 entered while the player had control, so the boot-time
uninitialised `wCurMap` of 0 cannot count.

### Baseline: the naive fly

```
& .\.venv\Scripts\python.exe train.py --evaluate-naive --eval-episodes 10 --episode-ticks 20000
```

| episode | reward | tiles | maps | furthest | left the house |
|---|---|---|---|---|---|
| 1 | 30 | 31 | 1 | Red's house 2F | no |
| 2 | 34 | 35 | 1 | Red's house 2F | no |
| 3 | 34 | 35 | 1 | Red's house 2F | no |
| 4 | 33 | 34 | 1 | Red's house 2F | no |
| 5 | 36 | 37 | 1 | Red's house 2F | no |
| 6 | 31 | 32 | 1 | Red's house 2F | no |
| 7 | 55 | 51 | 2 | Red's house 1F | no |
| 8 | 58 | 54 | 2 | Red's house 1F | no |
| 9 | 35 | 36 | 1 | Red's house 2F | no |
| 10 | 48 | 44 | 2 | Red's house 1F | no |
| **mean** | **39.4** | **38.9** | | | **0 of 10** |

Three of the ten got as far as downstairs. None got out. That is the v1 result
reproduced under the reward function: the bedroom holds about 42 reachable
tiles and the naive fly covers most of them, then runs out of anything new.

### Trained: 2,000,000 ticks, 100 episodes

```
& .\.venv\Scripts\python.exe train.py --evaluate brains\latest.npz --eval-episodes 10 --episode-ticks 20000
```

| episode | reward | tiles | maps | furthest | left the house |
|---|---|---|---|---|---|
| 1 | 125 | 116 | 3 | Pallet Town | yes |
| 2 | 167 | 158 | 3 | Pallet Town | yes |
| 3 | 219 | 165 | 4 | Oak's Lab | yes |
| 4 | 166 | 140 | 4 | Oak's Lab | yes |
| 5 | 143 | 134 | 3 | Pallet Town | yes |
| 6 | 211 | 194 | 4 | Blue's house | yes |
| 7 | 149 | 140 | 3 | Pallet Town | yes |
| 8 | 239 | 213 | 4 | Oak's Lab | yes |
| 9 | 171 | 162 | 3 | Pallet Town | yes |
| 10 | 205 | 196 | 3 | Pallet Town | yes |
| **mean** | **179.5** | **161.8** | | | **10 of 10** |

**Primary acceptance: 10 of 10 against the baseline's 0 of 10.** The contract
asked for 8. Reward is 4.6x the baseline and tiles covered 4.2x. Four of the ten
found a building in Pallet Town: three reached Oak's Lab, one the rival's house.

Stretch goals, reported and not dressed up: no episode reached Route 1 (map 12),
no starter, no level gained, no badge. Over the whole 2,000,000 ticks of
training, 9 of 100 episodes set at least one event flag, 7 entered the rival's
house and 4 entered Oak's Lab. The fly gets outside reliably and then wanders
Pallet Town; it has no idea the lab matters.

### The learning curve

Training episodes only, from `runs/train.csv`, twenty at a time:

| episodes | mean reward | mean tiles | share leaving the house | mean distinct maps |
|---|---|---|---|---|
| 1-20 | 66.7 | 62.8 | 0.15 | 1.85 |
| 21-40 | 93.5 | 88.2 | 0.45 | 2.25 |
| 41-60 | 123.5 | 116.3 | 0.60 | 2.65 |
| 61-80 | 130.2 | 121.7 | 0.50 | 2.70 |
| 81-100 | 131.7 | 123.1 | 0.60 | 2.80 |

The interleaved evaluation episodes (learning off, one every ten) went 0, 0, 1,
1, 0, 0, 1, 0, 1, 1 on leaving the house across episodes 10 to 100, which is the
same story with a sample size of one per point.

Two things in that table are worth saying out loud. The curve is still rising at
episode 100, so 2,000,000 ticks is where the budget ran out, not where learning
stopped. And the training share never gets near the 10 of 10 the final
evaluation got, because training episodes keep the exploration noise and the
learning-on dopamine; the evaluation is the learned policy alone.

The first episode that left the house was number 11. The first with learning
switched off was number 30.

What actually changed inside: mean absolute KC-to-MBON weight went from 0 to
0.022 against a clip of 0.05, the mean absolute TD error per tick went from
0.007 to about 0.06, and the press mix shifted from UP 23.5% / DOWN 25.7% /
LEFT 18.9% / RIGHT 20.3% in episodes 1-10 to UP 19.3% / DOWN 23.2% / LEFT 22.6%
/ RIGHT 22.4% in episodes 91-100. That is a small shift in the aggregate, which
is what you would expect: the learned part is place-dependent, so it cancels out
when you sum over a whole episode. The behaviour it produces does not.

## What v1 did, for comparison

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

v1's README ended that paragraph with "nothing is going to fix that except a
goal, and this fly does not have one". The mushroom body is that goal, and the
table above is what it bought: 10 of 10 out of the front door.

The panic reflex fired 11 times in the first 3,000 ticks and 28 times over
60,000. That distribution is the point: it fires constantly during the intro and
the long text boxes, where the player cannot move, and rarely once the fly is
walking around a room. It survives training: 53 panics across training episodes
1-10 and 70 across 91-100, which is the exploration noise the learned policy is
still riding on.

## What it cannot learn

The trained fly is still a fly. The ceiling here is the early routes, and these
are the reasons, not excuses:

- **No planning.** There is no model of the game and no search. The mushroom
  body is one linear readout of the current screen. It can learn "from a screen
  that looks like this, DOWN has paid before". It cannot learn "go back for the
  parcel first".
- **It cannot read.** Nothing in the pipeline turns pixels into text. Every
  dialogue box is a pattern to mash A at, and the difference between "you
  received a POTION" and "your rival blocks the way" is invisible.
- **No memory within an episode.** The policy input is one frame. Two places
  that look alike get the same code and the same bias, and "I have already been
  here this episode" is in the reward, not in anything the fly can see.
- **Exploration is a random walk with a bias.** The reflex net and the panic
  burst are the only things producing variation. Anything the fly has never once
  stumbled into is something the critic can never value.
- **Battles are not modelled at all.** A battle is a screen like any other. The
  reward pays for levels, so winning one pays, but nothing in the circuit knows
  what a type matchup is.
- **The reward is an exploration bonus.** It pays for new ground, new events,
  levels and badges. It does not pay for the plot, so anything the plot gates
  (Oak's parcel, the rival fight, HM moves) is reachable only by accident.

## Honest expectations

- It will not beat the game.
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

91 tests, all headless, about 80 seconds. They pass with no ROM present; the
handful that need one skip when `roms/pokemon_red.gb` is absent, and the short
training test also needs `states/bedroom.state`.

Two of them carry most of the weight.

`tests/test_learning.py::test_the_fly_learns_which_button_pays_in_which_context`
is the one that says the learning rule is real. `tests/fake_world.py` shows one
of two static frames for 300 ticks at a time; pressing LEFT under frame A pays
+1 on the next tick, pressing RIGHT under frame B pays +1, everything else pays
nothing. The whole chain runs, optic lobe to mushroom body to spiking net to
motor bridge, with nothing shortcut. After 8,000 ticks of training, with
learning then switched off, the LEFT share of {LEFT, RIGHT} under A and the
RIGHT share under B both have to be at least 0.70, summed over three seeds. The
frames are built mirror-symmetric in both axes so the fixed retinotopic pathway
has no reason to prefer either direction, and a second test holds the untrained
control inside 0.35 to 0.65 to prove that.

`tests/test_behaviour.py` holds the untrained circuit to two things no unit test
can see. No button may exceed 40% of the rate its hold plus cooldown allows, and
a bright block wandering inside one third of the screen has to bias the matching
pool by at least 1.5x over its opposite, in all four directions, summed over
three seeds.

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

And for the learning half:

- The episode machinery lives in `src/flybrain/training.py`, with `train.py` at
  the root as a thin CLI over it, mirroring how `run.py` sits over `loop.py`.
  The spec put it all in `train.py`; splitting it is what lets the tests import
  and drive an episode without a subprocess.
- The tanh has a divisor, `mbon_scale`. The spec said "`mbon_gain * tanh(mbon)`
  -style"; `mbon` is a sum over 100 active Kenyon cells, so with no divisor at
  all the squash is hard over the moment any weight is learned and the bias is
  effectively a sign bit.
- `lr_critic` is forty times smaller than `lr_actor`. That is not a typo and the
  reason is in the config comment and above: the update touches 100 KCs whose
  traces saturate at 50, so the effective step is about 5000 times the number
  written down.
- `TickState` carries two fields beyond the list in the spec, `started` and
  `panics`, so the HUD can keep the per-button press counts and the panic count
  that the first spec required of it.
- "Has control" is `wPlayerName[0]` being a real character and `wJoyIgnore`
  being zero. The spec asked for a concrete definition and a test; this is it.
  `wJoyIgnore` also drops the map-transition frames, which is deliberate: the
  fly is not the one moving during those.
- Reward is read from RAM every tick rather than sampled. The whole snapshot,
  including a popcount over the 320-byte event-flag array, measures about 10
  microseconds against a tick budget near 1000, so there was no reason to
  sample.
- All five reward parts are implemented. Every address was verified against the
  pokered symbol file, so none had to be left out.
- Episode seeds are `seed + 1000 * episode` for training and `seed + 7_000_000
  + episode` for the interleaved evaluations, so the two sets never collide and
  a training run is reproducible.

## Licence and dependencies

`pyboy`, `numpy`, `pillow`, `opencv-python`; `pytest` for tests. Nothing else.
