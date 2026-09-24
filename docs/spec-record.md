# pokefly: render the shots to 9:16 mp4 files (v6)

Approved by Aidan on 2026-09-23. Builds on commit `99989bb`. Same rules as every earlier spec (work only in this folder, `.venv` python, quote the path, tuning numbers in `config.py`, never loosen a test, no em dashes in prose, one commit, push to `origin main` at the end this time).

## The problem

"Record the browser window" does not give a 9:16 video: the page is only 9:16 if the window is, and nothing on this machine records at all (no OBS, no ffmpeg, Game Bar ignores browser windows half the time). Aidan wants the shots in `docs/shot-list.md` as files. So the project renders them itself.

## What to build: `run.py --record out.mp4`

- **Renderer: headless Edge driven over CDP.** `C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe` exists here; look for Chrome too and take whichever is present (`--browser PATH` overrides). Launch it with `--headless=new --window-size=1080,1920 --remote-debugging-port=<free port> --user-data-dir=<temp> --disable-gpu-vsync --hide-scrollbars --autoplay-policy=no-user-gesture-required` plus whatever the vendored three.js needs to get WebGL in headless (`--use-angle=default` or `--enable-unsafe-swiftshader` if the GPU path refuses; measure which gives 60 fps and say so). Point it at the scene URL with the shot's query string.
- **Frames over CDP, stdlib only.** The couch server already speaks WebSocket server-side; write the small client side (masked frames, handshake) and talk JSON-RPC to `Page.startScreencast` (`format: "jpeg", quality: 90, maxWidth: 1080, maxHeight: 1920, everyNthFrame: 1`), acknowledging each frame with `Page.screencastFrameAck`. Decode with `cv2.imdecode`.
- **Constant frame rate output.** `cv2.VideoWriter` (`mp4v`, 60 fps, 1080x1920; opencv-python is already a dependency and this works here, verified). Screencast frames come whenever the page repaints; pace the file by the frame's `metadata.timestamp`: repeat the last frame to fill gaps, drop extras, so N seconds of recording is exactly 60N frames. `--record-fps 30` for a lighter file. Print the real capture rate at the end; if it is under 50 fps say so loudly, because a 60 fps file made of 20 fps captures is a stutter.
- **Size:** always 1080x1920 in portrait, 1920x1080 in landscape (`--record` without `--portrait`). The page must be told its viewport is exactly that: `Emulation.setDeviceMetricsOverride` with DPR 1.
- **Duration:** `--seconds N` (default 20) stops the run and finishes the file; for a `--replay` the default is the replay's own length plus 5 s after the milestone lands, so the flash is in the take. The game keeps its 60 Hz pacing while recording; if the machine cannot hold both, the capture rate line will say so.
- **Headless game:** `--record` implies no SDL window and no browser tab opening; the terminal HUD stays. Ctrl+C finishes the file rather than corrupting it (VideoWriter needs `release()`).
- Also expose it as a function (`flybrain.record.record(cfg, url, out, seconds)`) so the shot runner below can call it in-process.

## The shot runner becomes a render: `scripts/render_shots.py`

`python scripts/render_shots.py` renders every row of `docs/shot-list.md` to `shots/NN-<slug>.mp4` with no one at the keyboard: shot 1 the composition for 20 s, shot 2 the monitor, shot 3 the orbit (drive the orbit by a query parameter `orbit=1` you add to the page: a slow automatic rotation, then cut to a second file for the TV close-up), shots 4 to 6 the replays (6 uses `got_starter` when its replay exists, else `entered_lab`), shot 7 the fly close-up for 30 s, shot 8 the composition again. `--only N`, `--seconds`, `--out DIR`. Print one line per shot with the file, its duration and the capture rate. `shots/` is gitignored. Delete `scripts/shots.ps1` and rewrite `docs/shot-list.md`'s intro and README "How to record" around the render (keep the OBS note as the alternative for anyone who wants a live take).

## Tests
- The CDP client's masking and handshake against the RFC example; JSON-RPC id matching; screencast ack.
- The frame pacer as a pure function: timestamps in, frame indices out (gaps repeated, extras dropped, exact count for N seconds).
- An end-to-end test that skips cleanly when no browser is present: record 3 seconds of the scene headless, assert the file exists, opens with `cv2.VideoCapture`, has 1080x1920 frames and about 180 of them, and that a mid-file frame is not black and not identical to the first (the TV is showing a game).
- All 225 existing tests pass; name any that had to change and why.

## Definition of done
Tests green (paste). `python scripts/render_shots.py` run for real here: paste its per-shot lines and the total wall clock; open the shot 4 file with `cv2.VideoCapture` and confirm the frame count and size. README updated. One commit ending `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`, then `git push origin main`. Reviewer's report: what was built, pasted outputs, capture rates, which browser flags were needed for WebGL in headless, deviations with reasons, everything unverified. The reviewer will watch the files.
