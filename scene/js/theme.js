/**
 * Colours, sizes and the two or three numbers more than one module needs.
 *
 * The room is lit warm and low so the TV can be the key light. Anything that
 * has to read at a glance (the seven pools, the four Game Boy shades) is
 * defined once, here.
 */

export const POOLS = ['UP', 'DOWN', 'LEFT', 'RIGHT', 'A', 'B', 'START'];

/** One colour per motor pool, used by the raster rows, the MBON bars and the
 *  glow on a pressed control. Bright enough to read against a dark scope. */
export const POOL_COLOR = {
  UP: '#6ee7ff',
  DOWN: '#ffa14a',
  LEFT: '#c4a2ff',
  RIGHT: '#5be08a',
  A: '#ff5d73',
  B: '#ffd166',
  START: '#cfd4de',
};

export const POOL_HEX = {
  UP: 0x6ee7ff,
  DOWN: 0xffa14a,
  LEFT: 0xc4a2ff,
  RIGHT: 0x5be08a,
  A: 0xff5d73,
  B: 0xffd166,
  START: 0xcfd4de,
};

/** The classic four shades of a DMG screen, darkest first. */
export const GAMEBOY_SHADES = [
  [15, 56, 15],
  [48, 98, 48],
  [139, 172, 15],
  [155, 188, 15],
];

export const ROOM = {
  floor: 0x8a6a52,
  wall: 0xc9b9c2,
  rug: 0xd8ccc0,
  couch: 0xffffff,
  couchDark: 0xa9b3b8,
  tv: 0x26262c,
};

/**
 * The late-1990s living room, one name per colour. Canvas textures take the
 * string, materials and vertex colours take `hex(RETRO.name)`. Slightly
 * desaturated on purpose: dusty teal and mauve, mustard, rust, wood browns,
 * beige plastic, so the TV's cold light and the warm lamps are what pop.
 */
export const RETRO = {
  // wood
  walnut: '#4a2f1d',
  walnutLight: '#6b4529',
  oak: '#9a6b40',
  veneer: '#7a5232',
  // fabric and paint
  teal: '#2f6f6c',
  tealDeep: '#1e4a4d',
  tealLight: '#5c9a92',
  mauve: '#8c5e78',
  mauveDeep: '#5e3a52',
  mustard: '#c99a2e',
  mustardLight: '#e0bd62',
  rust: '#a24a26',
  burgundy: '#6e2433',
  cream: '#e9dcc0',
  creamDark: '#bfae8c',
  olive: '#5f6b3a',
  leaf: '#3f6b3a',
  leafLight: '#6d9a4f',
  terracotta: '#b2603c',
  // plastic and metal
  beige: '#cfc4aa',
  beigeDark: '#9f957d',
  greyPlastic: '#8d8f93',
  charcoal: '#2b2b31',
  black: '#151518',
  chrome: '#c9ccd2',
  cable: '#4a4d55',
  brass: '#b8923f',
  // light
  lavaWax: '#ff5a3c',
  lavaGlass: '#ff3d8b',
  moon: '#dfe8ff',
  sky: '#101a3a',
  ledGreen: '#63ff9a',
  ledRed: '#ff4a3a',
  water: '#2a8fb0',
  goldfish: '#ff8a2a',
};

/** '#rrggbb' to 0xrrggbb, for materials and vertex colours. */
export const hex = (css) => parseInt(css.slice(1), 16);

/** The fly. Golden tan with dark bands, the same character as the first
 *  episodes, now with the parts a real fly has. Canvas textures for the eyes
 *  and wings take the `css` strings; everything else is vertex colours. */
export const FLY = {
  thorax: 0xc08a4c, // the golden tan of the back
  thoraxDark: 0x6d4a28, // the stripes down the back, the scutellum's rim
  pleura: 0xd7ab6c, // the paler sides of the thorax
  belly: 0x8a5e34, // under the thorax, between the legs
  head: 0xc7924f,
  crown: 0x7a4020, // the dark triangle round the ocelli on top of the head
  vitta: 0xb4552c, // the orange-red stripe up the face between the eyes
  stripeLight: 0xd3a35e, // the front of each abdominal plate
  stripeDark: 0x46311f, // the dark band at the back of each plate
  sternite: 0xe4c894, // the pale underside of the abdomen
  leg: 0x3a2a1c,
  legBase: 0xb07d45, // coxae and femora start body coloured and darken out
  bristle: 0x241810,
  pulvillus: 0xf0dcc0, // the sticky pads under each foot
  labellum: 0xe8b8a0, // the sponge at the end of the proboscis
  ocellus: 0x7a1c14,
  wing: 0xdfe9f2,
  vein: 'rgba(92, 64, 40, 0.92)',
  eyeHot: '#f55a2c', // top front of the eye
  eyeDeep: '#850a18', // bottom back
  eyeRim: '#3c0608', // the lines between the facets
  pad: 0xb9b3a8,
  padDark: 0x2f333a,
};

/** Where the camera sits for each of the four views, and what it looks at.
 *  `1` `2` `3` `4` in the browser pick these. */
export const VIEWS = {
  1: { name: 'the living room', eye: [3.30, 1.80, 2.35], look: [-0.20, 0.80, 0.15] },
  2: { name: 'the TV', eye: [0.02, 1.02, -0.62], look: [0.0, 0.86, -1.7] },
  3: { name: 'the fly', eye: [0.95, 1.30, 0.20], look: [0.0, 1.00, 1.35] },
  4: { name: 'the brain monitor', eye: [2.05, 1.32, 2.05], look: [1.55, 0.86, 0.75] },
};

/** The portrait layout's middle camera: in front of the fly, a little to its
 *  right and above, so the face, the head glow and the controller in its
 *  front legs are all in shot. The fly sits at (0, 0.54, 1.42) facing the TV
 *  (-z); its pad is at about (0, 0.64, 1.04). Aimed high enough that the
 *  antennae and the ring of glow round the head clear the top of the band. */
export const PORTRAIT_FLY = { eye: [0.62, 1.12, 0.35], look: [0.0, 0.79, 1.3], fov: 35 };

/** Where the controller cable touches the rug in front of the couch. The part
 *  from the console to here is room furniture (props.js); the part from here
 *  up to the pad moves with the fly (fly.js). */
export const CABLE_FLOOR = [0.06, 0.012, 0.84];

/** How much of the portrait frame the TV close-up takes, from the top. */
export const PORTRAIT_TV_SHARE = 0.45;

export const clamp = (value, low, high) => (value < low ? low : value > high ? high : value);

/** Frame-rate independent approach, the same shape as three's MathUtils.damp. */
export const approach = (current, target, lambda, dt) =>
  current + (target - current) * (1 - Math.exp(-lambda * dt));
