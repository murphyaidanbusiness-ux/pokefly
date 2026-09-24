# Shot list: B-roll for a 9:16 Reel

Every shot here renders to a file on the machine with the ROM, with nobody at
the keyboard:

```powershell
& .\.venv\Scripts\python.exe scripts\render_shots.py              # every shot, into shots/
& .\.venv\Scripts\python.exe scripts\render_shots.py --only 4     # just shot 4
& .\.venv\Scripts\python.exe scripts\render_shots.py --seconds 5  # every take 5 s, for a quick look
```

Each row is one `run.py --record` run (README, "How to record"): headless Edge
draws the couch scene at exactly 1080x1920, the frames come over the DevTools
protocol, and a constant 60 fps H.264 mp4 (libx264, crf 23, about 1.3 to 1.7
MB a second) lands in `shots/NN-<name>.mp4` (gitignored). The whole list is
about 230 MB and takes about six minutes, most of the extra over the takes'
own length being the encode that runs after each take.
Every shot gets a port of its own, so a `run.py --couch` of yours on 8765 can
keep going while it renders. A take never writes: the journey shots (1, 2, 3,
7, 8) play on from `saves/journey/` read only with learning frozen, and nothing
goes into `milestones/`. The script prints one line per file with its length
and the capture rate; anything under 50 captures a second is flagged, because
a 60 fps file made of fewer captures stutters.

Numbers on screen come from your own journey: `milestones/journey.json`
holds the game time of every first, and the flash and the strip show the
same number. Say the number that file says, or the picture will contradict
the voice.

| # | script line | shot | file, and what renders it |
|---|---|---|---|
| 1 | "I got a fly brain to play Pokemon Red" | the portrait composition: the game on the TV above, the fly on the couch below, strip on. 20 s, so there is a press and a startle in the take | `01-composition.mp4`: `run.py --portrait --no-learn`, page `?portrait=1` |
| 2 | "neurons wired into PyBoy" | the brain monitor: the spike raster scrolling, seven coloured pool rows. 15 s | `02-monitor.mp4`: page `?portrait=1&view=4&clean=1` |
| 3 | "I made this couch setup for him and the live game is on that TV" | a slow orbit of the room from view 1, 10 s; then cut to the TV close-up, 8 s | `03-orbit.mp4`: page `?portrait=1&view=1&clean=1&orbit=1`; `03-tv.mp4`: `?portrait=1&view=2&clean=1` |
| 4 | "It took N to leave Red's bedroom" | the recorded replay: the countdown counts to zero, the flash says "left the bedroom" with the game time. The take is the replay's own length (about 15 s) plus 5 s after the flash | `04-left-bedroom.mp4`: `run.py --replay left_bedroom --portrait` |
| 5 | "it hit the stairs and wandered Pallet Town" | the replay of leaving the house, the same way; it ends outside | `05-left-house.mp4`: `run.py --replay left_house --portrait` |
| 6 | "before triggering Professor Oak" | the replay of the starter, when there is one (`milestones/got_starter/`). Until then, `entered_lab` is the closest moment that exists, and the script picks it | `06-got-starter.mp4` or `06-entered-lab.mp4`: `run.py --replay got_starter --portrait` (or `entered_lab`) |
| 7 | "still waiting for him to pick his starter" | the fly close-up, idle: breathing, an antenna twitch, a press or two. Long take, 30 s | `07-fly.mp4`: page `?portrait=1&view=3&clean=1` |
| 8 | outro, "comment Pokemon" | the composition again with the strip on, so the milestone list and game time are visible under the call to action. 20 s | `08-outro.mp4`: page `?portrait=1` |

The orbit turns the way a drag to the left does. The shot list used to say
"drag gently right", but from view 1 that direction runs the camera through
the brain monitor, the back of the couch and a lamp inside ten seconds; the
left turn sweeps across the couch to the lamp and the coffee table. In
portrait, view 1 is normally the two-band composition, which has no orbit
camera, so `orbit=1` shows view 1 full frame instead.

One shot by hand, any length: `run.py --record out.mp4 --portrait --no-learn
--seconds 12 --scene-params "view=3&clean=1" --couch-port 8790`.

For a live take in OBS instead, see the OBS note under "How to record" in the
README.

Replays only exist for milestones the journey has reached. `run.py --replay
NAME` with no replay lists the ones there are. A replay that prints
`DIVERGED` was recorded before the savestate fix in `emulator.py`; run the
journey on until the milestone lands again and it is rewritten.

Two lines in a script tend to drift from what the repository says, and a
viewer who follows the link will read the README:

- The brain is 2,000 neurons on a synthetic network built in the fly's
  style, not the 139,000-neuron FlyWire map. "A simulated fly brain" is
  right; "the fruit fly's brain" and "139,000 neurons" are not.
- It will not beat the game (README, "What it cannot learn"). "Until it
  beats the game" is fine as a bit; "it can" is not.
