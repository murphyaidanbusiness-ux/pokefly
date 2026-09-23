# Reviewing the couch scene

**I have not seen this scene.** There is no browser in the environment it was
written in, so every claim below is about what the code does, not about what it
looks like. The Python half is tested; the three.js half is checked for syntax
with `node --check` and for API existence by reading the vendored
`three.module.js`, and that is all. Please actually look at it.

## Run it

```powershell
cd "C:\Users\aidan murphy\fly-brain-pokemon"
& .\.venv\Scripts\python.exe run.py --couch --start-state --brain brains\v1-2M.npz
```

A browser tab opens on `http://127.0.0.1:8765/`. The terminal keeps the usual
HUD. Ctrl+C stops the run and releases the port.

If the tab is black, the page itself will say why: any uncaught error, failed
import or missing file is printed in a red panel over the scene, and a watchdog
prints one if the module has not booted within eight seconds. If that panel is
empty and the scene is still wrong, the browser console has the rest.

## The five-minute pass

| look at | how | what it should be |
|---|---|---|
| the room | opens on it | a small living room, warm and dim, a couch facing a chunky CRT, a rug, a lamp on the left, a side table on the right with an instrument on it |
| the picture | key `2` | the live game, Game Boy green, square pixels, faint scanlines, a slight curve to the glass |
| green or gray | key `G` | the picture switches to plain gray and back |
| the TV as key light | watch a dark room in game, then a bright one | the whole room dims and brightens with the game. This is the thing most worth checking |
| the fly | key `3` | clearly a fruit fly: big red compound eyes, tan thorax, striped abdomen, two translucent wings, six segmented legs, antennae, a proboscis, sitting upright holding a controller |
| button presses | key `3`, watch the pad | the pressed control goes down and lights in its own colour, the d-pad tilts the way the fly is walking, the front leg on that side pokes it. This should read without being told |
| the head glow | any view | a glow inside the head that tracks the firing rate, gold when something went better than expected and cold blue when it went worse |
| antennae | after a new room is entered | they perk up on a big positive dopamine flash and droop on a negative one |
| the startle | wait for a panic (the HUD counts them) | wings buzz, the fly hops off the cushion, the camera shakes |
| grooming | when START fires | the front legs come off the pad and rub together |
| leaning in | if a battle starts | the fly leans toward the TV |
| the brain monitor | key `4` | a scrolling spike raster, seven coloured labelled rows of eight neurons each at the top, a speckled band of 200 other neurons below, and seven bars on the ledge for the learned biases |
| the overlay | top left | plain words, no field names. `H` hides it |
| the camera | drag, wheel, right drag, `R` | turns, zooms, pans, resets |
| frame rate | the note under the keys | should sit at 60. If it drops the scene turns shadows off by itself and says so |
| a dropped feed | Ctrl+C the run while the tab is open | the TV goes to static and the overlay says "not connected". Start the run again and it reconnects on its own |

## Things I would check first, because they are the likeliest to be wrong

1. **Scale and framing of the default view.** The camera, the couch and the fly
   were placed by arithmetic, not by eye. If the fly is too small in the frame,
   or the TV is out of shot, the numbers to move are `VIEWS` in
   `scene/js/theme.js`.
2. **Light levels.** three.js light intensities are physical units and the
   values here (lamp 11, TV spot 5 to 35) were chosen by reasoning about
   inverse-square falloff, not by looking. If the room is too dark or blown out,
   `Television._buildLights` and `buildLamp` are the two places.
3. **Whether a press reads at a glance.** The contract says it must. If it does
   not, the emissive on a pressed control (`_controls` in `fly.js`,
   `emissiveIntensity` 0.05 to 2.45) is the dial.
4. **The wings.** Their orientation is the fiddliest piece of arithmetic in the
   fly and the easiest thing to have got backwards. They should sweep back over
   the abdomen, not stick out sideways or through the body.
5. **The controller in the front legs.** The legs are posed, not solved: the
   tips were placed at the pad by hand. If a leg misses the pad, the points are
   in `FlyActor._legs` and the pad is at `(0, 0.10, -0.38)` in the same frame.
6. **The raster rows.** 256 neurons in a 240 pixel canvas is tight. If the
   hidden band is a solid block rather than a speckle, `HIDDEN_HEIGHT` in
   `monitor.js` wants more room.

## What is not in the scene

- No downloaded models or textures. Every shape is a three.js primitive, a
  lathe, or a hand-drawn `Shape`; the floor, the rug, the picture on the wall
  and the controller labels are canvases drawn in code.
- Only three.js is vendored (`scene/vendor/`, r186, MIT, with its LICENCE). The
  orbit control is ours, in `scene/js/orbit.js`, because it is eighty lines and
  vendoring the example version would have needed an import map.
- No build step and no npm. The stdlib server serves the files as they are.

## Round two: portrait, the milestone strip, the flash, Save and Pause

**I have not seen any of this either.** Same caveat as above: the JS was
written against the vendored r186 (`setViewport`, `setScissor`,
`setScissorTest`, `clear` all exist there and take CSS pixels from the bottom
left), passes `node --check`, and the Python side of every message is tested.
Nothing about how it looks has been checked.

### Run it

```powershell
cd "C:\Users\aidan murphy\fly-brain-pokemon"
# a replay, portrait, with the countdown and the flash (needs milestones\left_house\ from a recorded run)
& .\.venv\Scripts\python.exe run.py --replay left_house --portrait
# the journey, landscape, with the Save button live
& .\.venv\Scripts\python.exe run.py --couch
```

For a true 1080x1920 frame, open Chrome DevTools, device toolbar, a custom
device of 1080 x 1920 at DPR 1, on `http://127.0.0.1:8765/?portrait=1`. A
second tab without `?portrait=1` stays landscape on the same feed.

### Portrait pass

| look at | what it should be |
|---|---|
| the whole window at 1080x1920 | no scrollbars, nothing cut off at the right or bottom edge |
| the top 45 percent | the CRT picture filling the width, the whole 160x144 picture visible with a thin bezel above and below it, pixels square and legible at phone size. The numbers to move: `PORTRAIT_TV_SHARE` in `theme.js`, the `1.07` margins in `frameTelevision` in `main.js` |
| the middle band | the fly facing the camera three-quarters on, head and head glow clearly visible, the controller in its front legs clearly visible and not cropped. The camera is `PORTRAIT_FLY` in `theme.js` (eye, look, fov): it was placed by arithmetic, not by eye, so this is the likeliest thing to need moving |
| the bottom band | the strip, full width: last milestone (big, gold), "at m:ss of game time", a live "+m:ss" since it that counts up at game speed, "generation N" and the brain file; under it one compact line: live/not connected, game time, where, "saved m:ss ago", Save, Pause |
| no gap or overlap | the fly band should end exactly where the strip begins (the canvas reads the strip's height each frame). If the strip is taller than 30 percent of the window it is clamped and will overlap |
| keys `2` `3` `4` | the ordinary orbit views, full frame, strip still at the bottom; `1` or `R` back to the composition |
| sharpness | the canvas draws at the full device pixel ratio in portrait and never lowers it to hold the frame rate (it may still turn shadows off, and the corner note would say so, but the note is hidden in portrait: check the console if the frame rate looks low) |
| the corner panel | hidden in portrait; `H` does nothing visible there |

### The milestone flash (both layouts)

Watch `run.py --replay left_house --portrait` (or the landscape form without
`--portrait`). During the replay the strip shows a gold countdown line, "left
the house in 0:14", counting down in game time. When it reaches zero:

- a gold-bordered banner appears (centre in landscape, over the fly band in
  portrait): "MILESTONE", the name in large type, "m:ss of game time" under
  it; it pops in, holds, and fades out over **3 seconds**. Is it readable in
  that time on a phone-sized recording?
- the glow inside the fly's head pulses gold three times over about 1.6 s and
  fades back to its usual colour; the head itself warms up. It should read as a
  distinct event, not as the ordinary dopamine flash.
- the countdown line disappears and the strip's "last milestone" becomes
  "left the house" with its time; the "+m:ss" restarts from zero.

The terminal prints `replay: left the house landed at m:ss (tick N), exactly
as recorded`; if it says DIVERGED, that is a bug worth a report.

### Save and Pause

| do | expect |
|---|---|
| journey mode (`run.py --couch`), click **Save** or press `S` in the page | the strip says "saving..." for a moment, then "saved 0:00 ago", counting up; the terminal prints "journey saved (on request) ..." |
| click **Pause** or press `P`/`Space` in the page | the game and the fly freeze, the button reads **Resume** with a gold tint, the terminal says "paused"; clicking again resumes. `P` in the terminal and the page button toggle the same pause |
| Save while paused | saves at once, "saved 0:00 ago" updates while still paused |
| a replay or `--no-journey` run | no Save button (nothing to save); Pause still works |
| clicking a button | must not also orbit the camera or type into anything |

### Likeliest to be wrong

1. The portrait fly camera (`PORTRAIT_FLY`): cropped controller, or the fly too
   small or too far to one side.
2. The flash position in portrait (`body.portrait #flash { top: 60% }` in
   `index.html`) landing on the fly's face instead of above it.
3. Strip font sizes in portrait are in `vh`; at 1920 tall they should be
   comfortably readable on a phone, but at a small window they get tiny.
4. Two renders a frame in the portrait composition: if the frame rate drops
   under 48 the scene turns shadows off, which changes the look.
