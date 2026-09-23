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
  floor: 0x3a2a20,
  wall: 0x2e2733,
  rug: 0x6d2f33,
  couch: 0x4a5a6b,
  couchDark: 0x35424f,
  wood: 0x5a3b26,
  tv: 0x26262c,
  metal: 0x8d939c,
};

export const FLY = {
  thorax: 0xb9844a,
  thoraxDark: 0x6d4a28,
  head: 0xa8763f,
  eye: 0xe03a2b,
  stripeLight: 0xc79a5b,
  stripeDark: 0x46311f,
  leg: 0x3a2a1c,
  wing: 0xdfe9f2,
  pad: 0xb9b3a8,
  padDark: 0x2f333a,
};

/** Where the camera sits for each of the four views, and what it looks at.
 *  `1` `2` `3` `4` in the browser pick these. */
export const VIEWS = {
  1: { name: 'the living room', eye: [3.40, 1.80, 2.30], look: [0.10, 0.80, 0.25] },
  2: { name: 'the TV', eye: [0.02, 1.02, -0.62], look: [0.0, 0.86, -1.7] },
  3: { name: 'the fly', eye: [0.95, 1.30, 0.20], look: [0.0, 1.00, 1.35] },
  4: { name: 'the brain monitor', eye: [2.05, 1.32, 2.05], look: [1.55, 0.86, 0.75] },
};

/** The portrait layout's middle camera: in front of the fly, a little to its
 *  right and above, so the face, the head glow and the controller in its
 *  front legs are all in shot. The fly sits at (0, 0.54, 1.42) facing the TV
 *  (-z); its pad is at about (0, 0.64, 1.04). */
export const PORTRAIT_FLY = { eye: [0.62, 1.12, 0.35], look: [0.0, 0.74, 1.3], fov: 34 };

/** How much of the portrait frame the TV close-up takes, from the top. */
export const PORTRAIT_TV_SHARE = 0.45;

export const clamp = (value, low, high) => (value < low ? low : value > high ? high : value);

/** Frame-rate independent approach, the same shape as three's MathUtils.damp. */
export const approach = (current, target, lambda, dt) =>
  current + (target - current) * (1 - Math.exp(-lambda * dt));
