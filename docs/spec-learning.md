# fly-brain-pokemon: learning contract (v2)

Approved by Aidan on 2026-09-20. Read `docs/spec.md` and the README first; this builds on the committed v1 (`f83ba95`). Same environment rules: work only in this folder, `.venv` python, quote the path (it has a space), numpy only (no torch, no scipy, no gym), never download a ROM, tuning numbers in `config.py`, never loosen a test to pass it, no em dashes in prose.

## Why v1 cannot learn, and the design that can

v1 has fixed wiring and sees mostly motion (frame delta). Nothing in it can come to mean "in THIS place, go DOWN". A global reward sprayed over a 2000-neuron recurrent net (plain reward-modulated STDP) is the obvious idea and it is weak: credit assignment through recurrence with a delayed scalar reward does not converge in the ticks we have. Do not build that.

Build the circuit the fly actually learns with: a **mushroom body**.

```
static 16x16 luminance (256)  ->  Kenyon cells (sparse random expansion, top-k)  ->  MBON readout (7, one per motor pool)
                                                                                 ->  value readout (1)
dopamine = TD error from RAM-derived reward, gates plasticity on the KC->MBON and KC->value synapses only
MBON output = extra input current into the matching motor pool of the existing spiking brain
```

The spiking connectome stays exactly what it is: reflexes plus exploration noise. The mushroom body is a learned, place-dependent bias on top. The final action still comes out of the spiking pools through `MotorBridge`. In Pokemon the player is always screen-centred, so the static frame is an egocentric view of the map and identifies place well; that is why vision alone is enough and the policy gets NO RAM inputs. RAM is for reward only.

## Components

### mushroom_body.py
- `MushroomBody(cfg, seed)`. Input: the optic lobe's downsampled 16x16 luminance frame, float32 in [0,1] (expose it from `OpticLobe` as a property; do not downsample twice). Subtract the frame mean so global brightness does not dominate.
- Kenyon cells: `n_kc` (default 2000). Each KC samples `kc_claws` (default 7, the real number) random input pixels with random signs/weights, seeded. APL-style global inhibition = only the top `kc_active_frac` (default 5%) are active each tick, binary. Vectorised; store the projection as index arrays, not a dense 2000x256 matmul if the index form is faster (measure).
- Readouts: `w_actor` (7, n_kc) float32 init zero, `w_critic` (n_kc,) init zero. `mbon = w_actor @ kc` (sum over active indices), `value = w_critic @ kc`.
- `pool_currents()` -> 7 signed currents, `mbon_gain * tanh(mbon)`-style squashed so a learned bias can tilt a pool but never pin it (the pool must still be able to lose to a strong reflex). Signed is fine: real MBONs come in approach and avoid types. The loop adds each current to every neuron of the matching pool on top of the sensory current; add a `pool_current` argument or a documented injection path in `Brain`, do not fake it through the sensory channels.
- Learning, three-factor, per tick:
  - actor eligibility `e_actor` (7, n_kc): decays by `lambda_actor` per tick; when `MotorBridge` STARTS a press for pool a this tick, `e_actor[a, active_kc] += 1` and, for the other six pools, `-= 1/6` (so the update is a preference shift, not a global gain change). Panic-burst presses do not write eligibility: the fly did not choose them.
  - critic eligibility `e_critic` (n_kc): decay `lambda_critic`, `+= kc` each tick.
  - dopamine `delta = r + gamma * V(s') - V(s)`, gamma per tick (default 0.997).
  - `w_actor += lr_actor * delta * e_actor`, `w_critic += lr_critic * delta * e_critic`, both clipped to a configured bound.
  - Everything sparse over active KCs where possible. Learning must cost under 0.3 ms per tick at n_kc=2000; measure and report.
- `save(path)` / `load(path)`: one `.npz` with the projection seed/config fingerprint, both weight arrays and training counters. Loading weights built for a different `n_kc`/seed is an error that says so.
- `learning: bool` switch. With learning off the body still biases the pools from loaded weights.

### reward.py
- `RewardTracker(cfg)`; `step(ram_snapshot) -> (reward: float, parts: dict[str, float])`; `reset()` per episode. The emulator exposes one `snapshot()` method returning a small dataclass of the RAM values below, so reward code never touches PyBoy.
- **Verify every address against the pret/pokered disassembly before using it** (the symbol file or `ram/wram.asm` on GitHub; you may fetch those pages). Put the verified address, the pokered symbol name and what it holds in `config.py`. If an address cannot be verified, leave that reward part out and say so; a wrong address is a reward for noise. Candidates from memory, all unverified: party count `0xD163`, party levels `0xD18C` + `0x2C` stride (6 mons), badges `0xD356` (bitfield), event flags `0xD747`-`0xD886` (bit count), battle flag `0xD057`, map `0xD35E`, Y `0xD361`, X `0xD362`.
- Parts (weights in config):
  - `tile`: first visit to a (map, x, y) this episode, +1.0.
  - `map`: first entry to a map id this episode, +5.0. The stairs cannot be farmed: a second visit pays nothing and neither do its already-seen tiles.
  - `event`: each newly set event-flag bit, +3.0 (this is what pays for meeting Oak, getting the starter, delivering the parcel).
  - `level`: increase in the sum of party levels, +5.0 per level.
  - `badge`: each new badge, +50.
  - Ignore everything until the player has control: RAM is uninitialised at boot and reads map 0 (see the README caveat). Define "has control" concretely and test it.
- No reward from anything the policy can trigger without progressing (menus opening, text advancing).

### episodes and training: train.py
- `python train.py` with no arguments must work. Flags: `--ticks N` total budget (default 2_000_000), `--episode-ticks N` (default 20_000), `--seed`, `--out brains/latest.npz`, `--resume`, `--eval-every K` episodes, `--log runs/train.csv`.
- Start state: episodes start from `states/bedroom.state`, a PyBoy savestate taken in Red's bedroom with the player in control. `python train.py --make-start-state` creates it by running the UNTRAINED fly headless from cold boot until map is Red's house 2F and the position has changed at least twice, then saving. `train.py` makes it automatically when missing. `states/` and `brains/` and `runs/` are gitignored.
- Each episode: load state, `reward.reset()`, zero eligibilities, keep weights. Headless, uncapped. Vary the brain/optic noise seed per episode so episodes differ.
- One CSV row per episode: episode, ticks, total reward and each part, distinct tiles, ordered distinct maps, furthest map reached, presses per button, panics, mean |delta|, weight norms, ticks/sec.
- Every `--eval-every` episodes run one evaluation episode with learning OFF and log it flagged as eval.
- Checkpoint every N episodes and on Ctrl+C; never lose a run to an interrupt.
- If the emulator tick is the bottleneck (it will be), say what the ticks/sec is and leave it; do not add multiprocessing in this round.

### run.py changes
- `run.py` loads `brains/latest.npz` automatically when it exists and prints one line saying which brain it loaded (episodes trained, ticks trained). `--naive` ignores it. `--brain PATH` picks another. `--learn` keeps learning on while you watch (saves on exit to the same file only with `--save-brain`). `--start-state` convenience: start from `states/bedroom.state`.
- HUD gains: dopamine (signed bar), value estimate, episode reward and its parts, the seven MBON biases, brain file/episodes trained.

### observer hook (for the 3D scene that comes next, build the hook only)
`run_loop(config, observers=())`: after each tick every observer is called with one immutable `TickState` dataclass: step, frame (the 144x160 gray array, not copied unless asked), pressed buttons, action started, pool excursions, firing rate, dopamine, value, reward parts, map id/name, x, y, in_battle, panic flag. The HUD becomes the first observer. No sockets, no rendering, nothing else in this round.

## Tests (headless, no ROM needed unless stated)
- KC code: exactly top-k active, deterministic under seed, two different frames share few active KCs, the same frame plus small noise shares most.
- **The learning rule works through the whole spiking chain**: a fake environment with no emulator shows one of two distinct static frames for a few hundred ticks at a time; pressing LEFT under frame A or RIGHT under frame B pays +1, the opposite pays 0. After a fixed budget (you choose it, keep the test under ~20 s), with learning then switched off, LEFT share of {LEFT,RIGHT} presses under A is >= 0.70 and RIGHT share under B is >= 0.70, summed over 3 seeds. An untrained control in the same test is near 0.5. This is the test that says the rule is real; do not weaken the 0.70.
- Critic: on the fake environment the value estimate is higher in the rewarded context than in a never-rewarded third context.
- Reward: first-visit semantics, stairs cannot be farmed, nothing paid before control, event-bit counting on a synthetic snapshot sequence, reset.
- Save/load round trip; mismatch error.
- Panic presses write no eligibility.
- Observer receives one TickState per tick with the documented fields.
- All 53 existing tests still pass unchanged. If one must change, say which and why.
- With the ROM present: `train.py --ticks 40000 --episode-ticks 20000` runs, writes the CSV and a brain file, and `run.py --headless --uncapped --no-hud --max-steps 2000` loads that brain.

## The real experiment (do it, report it, do not dress it up)
1. Baseline: 10 evaluation episodes of 20,000 ticks from the bedroom state with the NAIVE fly. Report per episode: reached Pallet Town (map 0 AFTER control, not the boot value)? furthest map, distinct tiles.
2. Train with the default budget. If wall clock allows, keep going to ~5M ticks; report ticks/sec and total time.
3. Same 10 evaluation episodes (same seeds) with the TRAINED fly, learning off.
4. **Primary acceptance: the trained fly reaches Pallet Town in at least 8 of 10 evaluation episodes, against the baseline's count (expected 0-1).** Stretch, report only: Route 1 (map 12), Oak's Lab (40), first event flag, starter obtained, first level gained.
5. A learning curve from the CSV in the README as a small table (episode bucket, mean reward, share of episodes leaving the house). No plotting dependency.
6. If the primary acceptance fails: diagnose from the logs (is the KC code separating 1F places? is delta informative or swamped? is the MBON gain too small to beat the reflex noise? does eligibility decay before the door pays?), change the numbers or the rule's details, retrain, and report each iteration honestly with its numbers. You may tune: learning rates, lambdas, gamma, gains, KC count/sparsity, reward weights, episode length, a slow decay of exploration noise. You may NOT: script any movement, feed RAM to the policy, reward a specific coordinate or the door tile, hard-code a direction preference, or shorten the evaluation to make it pass. If after three honest iterations it still fails, stop and report where it stands and what you think is the binding constraint.

## Definition of done
All tests green (paste output); the experiment above reported with raw numbers; `brains/latest.npz` left in place on disk (gitignored) so `python run.py` shows the trained fly; README updated (how to train, how to watch, what it learned, what it cannot learn: no planning, no reading, a realistic ceiling around the early routes); one commit ending with
`Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`; no push. Final message is a reviewer's report: what was built, pasted outputs, measured numbers, every deviation with its reason, everything unverified.
