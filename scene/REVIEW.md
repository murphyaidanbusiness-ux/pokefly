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
