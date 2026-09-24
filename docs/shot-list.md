# Shot list: B-roll for a 9:16 Reel

Every shot here is recorded on the machine with the ROM, from the couch
scene in the portrait layout, at 1080x1920 and 60 fps (see "How to record"
in the README). One server per shot: `run.py` holds the port for as long as
it runs, so start the run, open the URL in the recording browser, record,
Ctrl+C, next shot. The page's query parameters (`view`, `clean`, `green`)
are what change the framing without a keypress.

Numbers on screen come from your own journey: `milestones/journey.json`
holds the game time of every first, and the flash and the strip show the
same number. Say the number that file says, or the picture will contradict
the voice.

| # | script line | shot | command and URL |
|---|---|---|---|
| 1 | "I got a fly brain to play Pokemon Red" | the portrait composition: the game on the TV above, the fly on the couch below, strip on. Let it run 20 s so there is a press and a startle in the take | `run.py --portrait --no-learn` then `http://127.0.0.1:8765/?portrait=1` |
| 2 | "neurons wired into PyBoy" | the brain monitor: the spike raster scrolling, seven coloured pool rows. Landscape framing cropped to 9:16 in the edit, or portrait with view 4 | `run.py --portrait --no-learn` then `?portrait=1&view=4&clean=1` |
| 3 | "I made this couch setup for him and the live game is on that TV" | a slow orbit of the room. Start on view 1, drag gently right for 6 s; then cut to the TV close-up | `?portrait=1&view=1&clean=1`, then `?portrait=1&view=2&clean=1` |
| 4 | "It took N to leave Red's bedroom" | the recorded replay: the countdown counts to zero, the flash says "left the bedroom" with the game time. Start recording, then start the run; it begins about 15 s before the moment | `run.py --replay left_bedroom --portrait` then `?portrait=1` |
| 5 | "it hit the stairs and wandered Pallet Town" | the replay of leaving the house, the same way; it ends outside | `run.py --replay left_house --portrait` |
| 6 | "before triggering Professor Oak" | the replay of the starter, when there is one (`milestones/got_starter/`). Until then, `entered_lab` is the closest moment that exists | `run.py --replay got_starter --portrait` (or `entered_lab`) |
| 7 | "still waiting for him to pick his starter" | the fly close-up, idle: breathing, an antenna twitch, a press or two. Long take, 30 s | `run.py --portrait --no-learn` then `?portrait=1&view=3&clean=1` |
| 8 | outro, "comment Pokemon" | the composition again with the strip on, so the milestone list and game time are visible under the call to action | `?portrait=1` |

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
