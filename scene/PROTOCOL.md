# The couch feed

What `run.py --couch` sends the browser. One WebSocket, `ws://127.0.0.1:8765/ws`,
server to client, with exactly two exceptions: the page may send
`{"cmd": "save"}` or `{"cmd": "pause"}` (see "Commands from the page"). A ping
is answered with a pong, a close is obeyed, everything else is dropped on the
floor.

Written by hand against RFC 6455 in `src/flybrain/couch.py`. Server frames are
unmasked, never fragmented, and use all three length forms. Client frames are
masked and unmasked on arrival.

`PROTOCOL_VERSION` is `2`, in `couch.py` and in `scene/js/net.js`. The page says
so in the overlay if the two disagree rather than drawing nonsense. Version 2
added the journey fields on `state`, the `status` message, `game_hz` and
`milestone_labels` on `hello`, and the two commands.

## Rates

| message | rate | set by |
|---|---|---|
| video | 30 a second | `Config.couch_video_fps` |
| state | 45 a second | `Config.couch_state_hz` |
| hello | once per connection, and again when the fly is attached | |
| status | when the run pauses or resumes, and after a save made while paused | |

Both rates are wall clock, not tick counts, so `--couch --uncapped` floods
nothing. The server keeps one slot per kind of message and overwrites it, so a
browser that cannot keep up loses frames and never builds a queue. A client that
stops draining its socket for `couch_send_timeout` seconds is dropped.

## Text messages (opcode 1)

JSON, always an object with a `type`.

### `hello`

Sent as soon as a client connects, and again once the observer has the fly, at
which point it carries the spike-sample labels.

```json
{
  "type": "hello",
  "protocol": 2,
  "pools": ["UP","DOWN","LEFT","RIGHT","A","B","START"],
  "thresholds": [6.4, 6.4, 6.4, 6.4, 6.4, 8.0, 14.08],
  "reward_parts": ["tile","map","event","level","badge"],
  "brain": "brain: v1-2M.npz (100 episodes, 2000000 ticks trained)",
  "spike_labels": ["UP","UP", ... , "", ""],
  "spike_bits": 256,
  "video": {"message": 1, "width": 160, "height": 144, "bytes": 23040},
  "state_hz": 45.0,
  "video_fps": 30.0,
  "game_hz": 60,
  "milestone_labels": {"left_bedroom": "left the bedroom", "left_house": "left the house", "...": "..."}
}
```

`spike_labels[i]` is the motor pool neuron `i` of the sample belongs to, or the
empty string for one of the sensory or hidden neurons. `thresholds[i]` is what
`excursion[i]` has to cross for that pool to press its button.

### `state`

```json
{
  "type": "state",
  "t": 12.482,
  "step": 748,
  "tps": 59.9,
  "pressed": ["UP"],
  "events": [{"step": 744, "pool": "UP", "panic": false}],
  "action": "UP",
  "history": ["A","UP","UP","LEFT"],
  "excursion": [7.21, 1.04, 3.88, 2.10, 0.55, 0.12, 0.03],
  "share": [1.127, 0.163, 0.606, 0.328, 0.086, 0.015, 0.002],
  "firing_rate": 0.08714,
  "dopamine": 0.0312,
  "value": 4.118,
  "mbon": [0.42, -0.11, 0.03, 0.27, -0.55, 0.01, -0.02],
  "reward": 0.0,
  "episode_reward": 131.0,
  "parts": {"tile": 116.0, "map": 15.0, "event": 0.0, "level": 0.0, "badge": 0.0},
  "map_id": 0,
  "map_name": "Pallet Town",
  "x": 6,
  "y": 7,
  "in_battle": false,
  "panic": false,
  "panics": 12,
  "spikes": "AAAQAAA...",
  "game_tick": 15180,
  "game_time": "4:13",
  "milestones": [],
  "last_milestone": {"name": "left_house", "label": "left the house", "game_tick": 15120, "game_time": "4:12"},
  "since_milestone": 60,
  "since_time": "0:01",
  "generation": 100,
  "brain_file": "journey brain (from latest.npz)",
  "countdown": null,
  "paused": false,
  "journey": true,
  "saved_ago": 12.4
}
```

Notes on the fields that are not obvious:

- **`events` is the one that matters for the animation.** A press is held for
  four ticks and released, and state messages are about twenty milliseconds
  apart, so a press can start and finish between two of them. `pressed` is the
  set held at the instant of the message and would lose it; `events` is every
  press that STARTED since the last message and never does. The list is cleared
  on every send, so no event is delivered twice.
- `panic` on an event means the anti-stuck reflex chose that button, not the
  fly. `panic` at the top level is true only on the tick the reflex fired.
- `share[i]` is `excursion[i] / thresholds[i]`: at 1.0 that pool presses.
- `spikes` is base64 of `spike_bits / 8` bytes, one bit per sampled neuron, the
  first neuron in the high bit of the first byte (numpy's `packbits`). It is
  `null` until the observer has been attached to a fly.
- No value is ever `NaN` or `Infinity`: a non-finite number is sent as `0.0`,
  because `JSON.parse` refuses both and the scene would die on the first tick
  before the mushroom body has a value.

The journey fields:

- `game_tick` is game time in ticks since the cold boot (60 a second), and
  `game_time` the same as `m:ss` (or `h:mm:ss`). A run from a savestate starts
  at the state's own offset, not at zero.
- **`milestones` is latched like `events`**: every milestone that landed since
  the last state message, each `{name, label, game_tick, game_time}`, sent on
  exactly one message. This is what triggers the flash; `last_milestone` is
  the most recent one this run (or the one a restored save or replay already
  had), `null` before any, and is what the strip shows.
- `since_milestone` is game ticks since `last_milestone` (or since the run
  began), `since_time` the same as `m:ss`: the strip's live timer.
- `generation` is the brain's `episodes_trained`, `brain_file` which brain it is.
- `countdown` is only set during `run.py --replay`:
  `{"name": "left_house", "label": "left the house", "ticks": 420, "text": "left the house in 0:07"}`
  until the milestone's recorded tick, `null` after.
- `journey` and `saved_ago` are only present in journey mode: seconds since the
  newest journey save on disk, `null` when there is none yet. The page counts
  on from the value it last received, so the "saved ... ago" keeps moving
  while the run is paused.
- `paused` is always `false` on a state message: nothing ticks while paused.

### `status`

No tick runs while the game is paused, so no state message goes out; this one
does, when the run pauses, when it resumes, and after a save made while
paused.

```json
{"type": "status", "paused": true, "journey": true, "saved_ago": 0.0}
```

## Commands from the page

The page's Save and Pause buttons (and its `S`, `P` and `Space` keys) send one
masked text frame each:

```json
{"cmd": "save"}
{"cmd": "pause"}
```

`pause` toggles, exactly like `P` in the terminal. `save` writes the journey
save at once; outside journey mode it does nothing. The server's reader thread
parses the frame (at most 256 bytes, JSON, an object whose `cmd` is one of the
two words) and drops the word into a queue of at most 16 on the `Hub`; the game
loop takes the queue between ticks. Anything else, including non-JSON, other
words, binary frames and oversized payloads, is ignored and counted
(`Hub.frames_ignored`). A frame over 64 KB closes that client's connection, as
before. None of it can block or reach the loop except as one of those two
words.

## Binary messages (opcode 2)

One type byte, then the payload.

| byte 0 | meaning | length |
|---|---|---|
| `1` | one video frame | 1 + 160*144 = 23,041 |

The frame is 144 rows of 160 bytes, top row first, one 8-bit grayscale byte per
pixel: exactly what PyBoy's screen buffer holds, which on a Game Boy is four
distinct values. The scene maps each byte through a 256 entry lookup table into
the classic DMG green (or plain gray, `G`), darkening every other row for the
scanline, and puts it on a CanvasTexture with nearest-neighbour filtering.

The mean of the frame is the TV's brightness as a light, which is why the room
flickers with the game. That is computed in the browser from this message; it is
not sent.
