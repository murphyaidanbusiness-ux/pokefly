# fly-brain-pokemon: the live couch scene (v3)

Approved by Aidan on 2026-09-20. Read `docs/spec.md`, `docs/spec-learning.md` and the README first. Builds on commit `b27667a`. Same rules: work only in this folder, `.venv` python, quote the path (it has a space), no new Python runtime dependencies, tuning numbers in `config.py`, never loosen a test, no em dashes in prose.

**A training run is in progress in the background while you work** (it writes `brains/latest.npz`, `runs/train2.csv`, `runs/train2.log`). Do not touch those files, do not kill python processes you did not start, and when you need a brain for your own runs use the copy at `brains/v1-2M.npz` via `--brain`.

## What it is

`python run.py --couch` opens a browser tab showing a small 3D living room: a cartoon fruit fly sits on a couch holding a controller, facing a chunky CRT TV, and the TV shows the live game the fly's brain is playing. The fly's body shows what the brain is doing. It is live: it runs while the fly plays, at 60 Hz game speed, on this PC (Windows 11, NVIDIA GPU, any current Chrome/Edge).

## Architecture

```
run_loop (existing)  --observer-->  CouchObserver  --thread-safe latest-state slot-->  CouchServer (stdlib, own thread)
                                                                                        |- GET /            scene/index.html + js + vendored three.js
                                                                                        |- WS  /ws          binary frames + JSON state, server -> client only
browser: three.js scene, a CanvasTexture on the TV, animation driven by the state messages
```

- **Server: stdlib only.** `http.server`/`socketserver` in a daemon thread on `127.0.0.1` (never 0.0.0.0), default port 8765, `--couch-port`. WebSocket by hand: RFC 6455 handshake (Sec-WebSocket-Accept) and unmasked server-to-client frames, text and binary, with the 126/127 length forms. Ignore client frames except close and ping. Multiple tabs may connect; a slow or dead client is dropped, never allowed to block the game loop. The observer never blocks: it overwrites a "latest" slot and the sender thread drains it.
- **Protocol** (document it in `scene/PROTOCOL.md`): a JSON text message per tick batch with the TickState fields the scene needs (step, pressed buttons, action started, pool excursions, firing rate, dopamine, value, episode reward and parts, MBON biases, map name, x, y, in_battle, panic, brain name/episodes trained), and a binary message per video frame: 1 type byte + 160x144 bytes of 8-bit gray. Send video at 30 fps and state at 30-60 Hz; a button press that starts and ends between two state messages must still reach the scene (send press EVENTS, not only the held set).
- **Spike raster:** add an optional `spike_sample` to the state: the spike bits of a fixed, seeded sample of 256 neurons (some from each motor pool, labelled, the rest hidden/sensory), packed. Only computed when a couch observer is attached. The scene draws it as a scrolling raster on a "brain monitor" prop.
- **three.js is vendored**, not loaded from a CDN: download the current `three.module.js` (MIT) once from jsdelivr into `scene/vendor/` with its licence file, and commit it. No npm, no bundler, no build step: plain ES modules the stdlib server serves as files. No other JS libraries.
- `--couch` implies headless emulation (no SDL window) unless `--window` is also given, paces the loop at 60 Hz itself if PyBoy's null window does not (verify which; measure the real tick rate and report it), opens the default browser once the server is listening (`--no-browser` to skip), and keeps the terminal HUD. All existing flags keep working (`--brain`, `--naive`, `--learn`, `--start-state`, `--uncapped`).
- Ctrl+C shuts the server down cleanly and releases the port.

## The scene (stylised, built from primitives in code; no downloaded models or textures)

- Room: floor with a rug, back wall, a couch, a small table, a CRT TV with a slightly curved-looking bezel on a stand, a lamp. Warm low light; the TV is the key light and its colour/intensity follows the mean luminance of the current game frame so the room flickers with the game. Soft shadows if they hold 60 fps.
- TV picture: the live frames on a CanvasTexture, nearest-neighbour filtering, mapped through the classic four-shade Game Boy green palette (toggle with `G` for plain gray). Subtle scanline/glow is welcome if cheap.
- The fly, seated upright on the couch facing the TV, clearly a Drosophila caricature: big red compound eyes, tan thorax, striped abdomen, two translucent wings, six segmented legs, antennae, a proboscis. The two front legs hold a controller with a visible d-pad, A, B and START.
  - Button presses: the matching control on the pad depresses and the leg tip on that side pokes it; the d-pad tilts toward the pressed direction. Must read clearly at a glance.
  - Firing rate: a glow inside the head (emissive brain) whose brightness follows the smoothed firing rate, with small sparks on bursts.
  - Dopamine: positive delta pulses the brain glow gold and the antennae perk up; negative pulses it cold blue and they droop. Scaled so ordinary play is calm and a new map is an obvious flash.
  - Panic reflex: wings buzz (fast oscillation), the fly hops off the cushion and lands, a short camera shake.
  - Idle life: breathing, occasional wing twitch, head follows the on-screen action a little, front legs rub together (grooming) when START fires.
  - In battle: the fly leans forward.
- Brain monitor prop (an oscilloscope-style box by the couch) showing the scrolling spike raster with the seven motor-pool rows coloured and labelled, and seven small bars for the MBON biases.
- DOM overlay, small and unobtrusive, in plain words: map name and X/Y, episode reward, brain name and how long it trained, firing rate, last actions, ticks/s, connection status. `H` hides it.
- Camera: a gentle default three-quarter view over the fly's shoulder so both the fly and the TV are visible; orbit with the mouse (write the small orbit control yourself or vendor three's OrbitControls from the same release); keys `1` couch view, `2` TV close-up, `3` fly close-up, `4` brain monitor.
- Disconnected state: if the socket drops the TV shows static and the overlay says so; it reconnects by itself.
- Must hold 60 fps on this machine and degrade gracefully (drop shadows first).

## Tests
- WebSocket: handshake accept key against the RFC's worked example; frame encoding at payload lengths 0, 125, 126, 65535, 65536; a real client connection in-process (write a minimal test client with `socket`, no dependency) receives one state message and one 23,041-byte video message; a client that stops reading is dropped and the observer call still returns in under 1 ms.
- Static serving: `/` returns the page, a path outside `scene/` is refused (no traversal), unknown path 404.
- Observer: spike sample is 256 bits, deterministic under seed, contains members of all seven pools; press events are not lost when a press starts and ends between two sends.
- The port is released after shutdown (bind it again in the test).
- JS: no test framework. Keep the scene code in small modules (`scene/js/room.js`, `fly.js`, `tv.js`, `monitor.js`, `net.js`, `main.js`) and make `net.js`'s message decoding a pure function. Run a syntax check on every JS file with `node --check` if Node is installed (it is on this machine); skip cleanly if not.
- All 91 existing tests still pass unchanged.

## Definition of done
1. Tests green, output pasted.
2. `python run.py --couch --start-state --brain brains/v1-2M.npz --no-browser --max-steps 1800` runs to completion; during it, your in-process test client or a second python process connects and you report message counts, measured state Hz, video fps and tick rate.
3. You cannot see the browser. Say so; do not claim the scene looks right. Instead make it easy to review: the reviewer will open it and look. Leave a `scene/REVIEW.md` checklist of what to look at and which key shows it.
4. README updated (how to run it, keys, what each visual means in plain words).
5. One commit ending with `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`. No push.
6. Final message is a reviewer's report: what was built, pasted outputs, measured numbers, deviations with reasons, everything unverified.
