# fly-brain-pokemon: milestones, replay and portrait mode (v5)

Approved by Aidan on 2026-09-22. Builds on whatever commit follows `docs/spec-training-stability.md`. Same rules as every earlier spec (work only in this folder, `.venv` python, quote the path, numpy only, tuning numbers and RAM addresses in `config.py` with the pokered symbol name, never loosen a test, no em dashes in prose, one commit, no push). The point of this round: Aidan is making an Instagram series of the fly's journey through Pokemon Red. Everything here serves a camera.

## 1. Milestones (`src/flybrain/milestones.py`)

A fixed ordered table `MILESTONES` of named game events, each a pure predicate over `RamSnapshot` (extend the snapshot only with verified addresses; the party species list, the current map, the badge byte and the event flags are the likely needs). At least, in story order: `left_bedroom` (map leaves Red's house 2F), `left_house` (map is Pallet Town after control), `entered_lab` (Oak's Lab, 0x28), `got_starter` (party count 0 to 1), `first_battle` (wIsInBattle nonzero), `first_win` (a battle ended with the party's lead HP above zero and no faint: define it from verified RAM, or leave it out and say so), `route_1` (map 0x0C), `viridian_city` (0x01), `first_level_up`, `pokemon_center` (any), `viridian_forest`, `pewter_city`, `first_badge` (badge bit 0). Map ids beyond those already confirmed in a run must come from the pokered constants file (`constants/map_constants.asm`), cite it.

`MilestoneTracker(cfg)` is fed each tick's `RamSnapshot` plus the tick number and reports the first time each predicate becomes true. Every milestone is recorded once per JOURNEY, not per episode: `milestones/journey.json` accumulates across runs and brains (name, game time in ticks and as m:ss at 60 ticks per second, the wall-clock date, the brain file and its episodes trained, the run kind: watch / train / eval). A run that starts from `--start-state` counts its ticks from the state's own tick offset so game time is honest; store that offset in the state's sidecar.

`TickState` gains `milestone: str | None` (the one that landed this tick) and `since_milestone: int` (ticks since the last one). The terminal HUD and plain log print a line when one lands: `milestone: left the house  4:12 of game time  (brain latest.npz, 100 episodes)`. `championator`-style plain words: a `LABELS` table maps names to what the overlay says.

Training: `training.py` CSV rows gain one column per milestone holding the tick it landed in that episode (blank if never), so a learning curve of "median ticks to leave the house by 10-episode bucket" can be read off the CSV. Add `train.py --milestones` that prints that table from a CSV.

## 2. Deterministic replay (`Fly.snapshot()` / `Fly.restore()`, `run.py --replay NAME`)

The series needs each milestone on camera at real speed after it was found headless at 1,500 ticks per second. So a headless run must be able to hand the couch scene the seconds leading up to the moment, and the fly must do the same thing again.

- A fly snapshot is the emulator savestate plus every array that decides the next tick: brain membrane potentials and refractory counters and the previous-spike vector, optic lobe previous frame, motor accumulators and baselines and cooldowns and panic counters, mushroom-body eligibilities and `_prev_value`, the reward tracker's visited sets and counters, and the bit-generator state of every RNG in the chain (optic noise, panic draws; find them all). One `.npz` beside the `.state` under `milestones/<name>/`, with the config fingerprint.
- A rolling buffer keeps a snapshot every `snapshot_every` ticks (default 300, five seconds) for the last `replay_lead` ticks (default 900); when a milestone lands, the buffer entry nearest `replay_lead` before it is written as that milestone's replay start, together with the tick the milestone landed at. Cost must stay under 2 ms per snapshot at n=2000 (measure; savestate to a BytesIO is the bulk of it).
- `run.py --replay left_house` restores that snapshot with the same brain and runs on from it: the fly repeats the milestone exactly. **Test:** run 600 ticks from a snapshot twice and assert the press sequences and positions are identical; and a headless run that takes a snapshot, runs on 600 ticks, restores and runs 600 again gives the same presses. If some element cannot be made deterministic, say which and why rather than weakening the test.
- `--replay` implies `--couch` unless `--headless`, and the couch overlay shows a countdown to the milestone ("left the house in 0:07") then the milestone flash.

## 3. Portrait mode (`run.py --portrait`)

A 9:16 layout of the couch scene for Reels: the CRT picture large at the top (the game must be legible at phone size, so the TV close-up framing, roughly the top 45 percent), the fly on the couch in the middle with the controller clearly visible, the milestone strip at the bottom: last milestone, live game-time timer since it, brain generation. The overlay panel becomes a compact bar. Camera presets 1-4 keep working; `1` in portrait is the portrait composition. The page must fill a 1080x1920 browser window without scrollbars; render at device pixel ratio so a recording is sharp. Add a `?portrait=1` URL form too so a second tab can be portrait while the first is not. The milestone flash in both layouts: name, game time, a short gold pulse on the fly's head, readable for 3 seconds.

## 4. Tests
- Every predicate on synthetic snapshots, first-time-only semantics, journey persistence across two tracker lifetimes, the start-state tick offset.
- The replay determinism tests above (ROM present; skip cleanly without it).
- Snapshot cost measured and asserted under 5 ms in the test (2 ms is the target to report).
- Observer: `TickState` carries the new fields; the couch protocol carries them (update `scene/PROTOCOL.md`); `node --check` on every JS file.
- All existing tests pass; name any that had to change and why.

## 5. Definition of done
Tests green (paste). A headless run from the bedroom state with `brains/latest.npz` for 60,000 ticks reporting which milestones landed and at what game time, with the replay snapshots written; then `run.py --replay left_house --headless --max-steps 1200` reproducing it (paste the milestone line from both). README section "The journey" (milestones, the journey file, replaying one for the camera, portrait mode, how to record: OBS or Win+Alt+R on the browser window). One commit ending `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`, no push. You cannot see the browser: say so, leave `scene/REVIEW.md` updated with what to check in portrait, and the reviewer will look. Final message is a reviewer's report with pasted outputs, numbers, deviations with reasons, everything unverified.

## 6. Continue where it left off (added the same day)

Watching should feel like one long save file, not a restart every time.

- **The journey save.** `saves/journey/` holds a fly snapshot (the same `.state` + `.npz` pair from section 2) and the brain the journey is learning into, `saves/journey/brain.npz`. `python run.py` with no flags: if a journey save exists, it continues from it (game, neurons, brain, milestone clock) and prints one line saying so with the game time; otherwise it starts a new journey from `states/bedroom.state` with a copy of `brains/latest.npz` and says that instead. `--fresh` discards the journey save (asks for a `y` on the terminal first, or `--fresh --yes`) and starts over. `--no-journey` is the old behaviour: run without touching the save.
- **Learning stays on while watching by default** in journey mode, into the journey brain, using the same learning-rate schedule as training (its `episodes_trained` counter advances once per hour of game time so the schedule keeps decaying). `brains/latest.npz` (the best evaluated brain) is never written by watching. `--no-learn` freezes the journey brain.
- **Autosave** every `autosave_minutes` of wall clock (default 5, `config.py`) and always on exit (Ctrl+C, window closed, `--max-steps` reached). A save is atomic: write to a temp name, then replace, so an interrupted save never corrupts the previous one. Keep the previous save as `.bak`.
- **Save now:** `S` on the terminal (beside the existing `P` pause) and a "Save" button on the couch overlay. The button needs the browser to send one text frame `{"cmd": "save"}`; the server currently reads only close and ping from clients, so parse masked client text frames for exactly this command set (`save`, `pause`), ignore anything else, and never let a client frame block or crash the loop. Add `pause` to the overlay too since the plumbing is the same. The overlay shows "saved 0:12 ago" and the game time.
- **Tests:** a save then restore continues with identical presses (reuse the determinism test), autosave fires on the schedule with a fake clock, exit always saves, `--fresh` without `--yes` on a non-tty refuses, the server accepts the `save` command from the in-process test client and ignores garbage frames, `latest.npz` is byte-identical after a journey run.
- README: "Continue where it left off" under The journey.
