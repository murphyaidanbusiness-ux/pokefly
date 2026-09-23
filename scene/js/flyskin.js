/**
 * The fly's textures, drawn in code: the compound eyes, the wing membrane
 * with its veins, a fine pitting for the cuticle, the mask for the glow on
 * the head's crown, and a small painted reflection of the room for
 * everything shiny on it.
 *
 * Nothing is downloaded. Randomness is seeded, so the fly is the same fly in
 * every take.
 */

import { FLY } from './theme.js';

let seed = 4242;
function random() {
  // mulberry32, as in textures.js.
  seed |= 0;
  seed = (seed + 0x6d2b79f5) | 0;
  let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
  t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
  return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
}

/** A small integer hash to 0..1, so a facet keeps its own shade. */
function hash2(i, j) {
  let h = Math.imul(i, 374761393) + Math.imul(j, 668265263);
  h = Math.imul(h ^ (h >>> 13), 1274126177);
  return ((h ^ (h >>> 16)) >>> 0) / 4294967296;
}

function canvas2d(width, height) {
  const canvas = document.createElement('canvas');
  canvas.width = width;
  canvas.height = height;
  return canvas;
}

function rgb(css) {
  const n = parseInt(css.slice(1), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

const smooth = (a, b, x) => {
  const t = Math.min(1, Math.max(0, (x - a) / (b - a)));
  return t * t * (3 - 2 * t);
};

// -- the compound eye ---------------------------------------------------------

/**
 * The right eye's facets, for a SphereGeometry (pole up) scaled into an
 * ellipsoid. Hexagons are laid out flat on a map of the eye seen from the
 * direction it bulges toward (out and forward), then wrapped back round the
 * sphere, so the facets stay even over the part anyone can see instead of
 * pinching at the sphere's poles. The left eye uses the same texture mirrored
 * (fly.js flips its u).
 *
 * `map` is the colour: hot orange at the top front to deep red at the back,
 * each facet a shade of its own, dark lines between them. `bump` is a dome
 * per facet, so the light catches every lens.
 */
export function eyeTextures(THREE) {
  const W = 1024;
  const H = 512;
  const colour = canvas2d(W, H);
  const height = canvas2d(W, H);
  const cctx = colour.getContext('2d');
  const hctx = height.getContext('2d');
  const cimg = cctx.createImageData(W, H);
  const himg = hctx.createImageData(W, H);

  // The direction the eye bulges toward, and two axes across it.
  const ax = [0.78, 0.14, -0.61];
  const al = Math.hypot(ax[0], ax[1], ax[2]);
  const A = ax.map((v) => v / al);
  let e1 = [A[2], 0, -A[0]]; // up x A, flattened: points round the eye
  const l1 = Math.hypot(e1[0], e1[1], e1[2]);
  e1 = e1.map((v) => v / l1);
  const e2 = [A[1] * e1[2] - A[2] * e1[1], A[2] * e1[0] - A[0] * e1[2], A[0] * e1[1] - A[1] * e1[0]];

  const S = 0.1; // facet spacing in radians: about thirty across what shows
  const R3 = Math.sqrt(3) / 2;
  const hot = rgb(FLY.eyeHot);
  const deep = rgb(FLY.eyeDeep);
  const rim = rgb(FLY.eyeRim);

  for (let py = 0; py < H; py += 1) {
    const v = 1 - (py + 0.5) / H;
    const theta = (1 - v) * Math.PI;
    const st = Math.sin(theta);
    const ct = Math.cos(theta);
    for (let px = 0; px < W; px += 1) {
      const phi = ((px + 0.5) / W) * Math.PI * 2;
      const dx = -Math.cos(phi) * st;
      const dy = ct;
      const dz = Math.sin(phi) * st;

      // Azimuthal equidistant map round A.
      const c = Math.min(1, Math.max(-1, dx * A[0] + dy * A[1] + dz * A[2]));
      const angle = Math.acos(c);
      let qx = dx - A[0] * c;
      let qy = dy - A[1] * c;
      let qz = dz - A[2] * c;
      const ql = Math.hypot(qx, qy, qz) || 1;
      qx /= ql;
      qy /= ql;
      qz /= ql;
      const x = (qx * e1[0] + qy * e1[1] + qz * e1[2]) * angle;
      const y = (qx * e2[0] + qy * e2[1] + qz * e2[2]) * angle;

      // Nearest centre of a hexagonal lattice: one of four corners of the
      // lattice cell the point falls in.
      const j0 = Math.floor(y / (S * R3));
      const i0 = Math.floor((x - j0 * S * 0.5) / S);
      let best = 1e9;
      let bi = 0;
      let bj = 0;
      let ox = 0;
      let oy = 0;
      for (let dj = 0; dj <= 1; dj += 1) {
        for (let di = 0; di <= 1; di += 1) {
          const i = i0 + di;
          const j = j0 + dj;
          const cx = i * S + j * S * 0.5;
          const cy = j * S * R3;
          const d = (x - cx) * (x - cx) + (y - cy) * (y - cy);
          if (d < best) {
            best = d;
            bi = i;
            bj = j;
            ox = x - cx;
            oy = y - cy;
          }
        }
      }
      // Distance to the hexagon's edge, 0 at the centre, 1 on the edge.
      const hx = Math.max(Math.abs(ox), Math.abs(0.5 * ox + R3 * oy), Math.abs(-0.5 * ox + R3 * oy)) / (S * 0.5);

      // Colour: hot at the top front, deep at the bottom back, a shade per
      // facet, a slightly brighter lens in the middle, dark between lenses.
      const warm = smooth(-0.5, 0.9, dy * 0.75 - dz * 0.55 + (c - 0.5) * 0.4);
      const jitter = 0.9 + 0.2 * hash2(bi, bj);
      const lens = 1.08 - 0.16 * hx * hx;
      const edge = smooth(0.8, 0.97, hx);
      const o = (py * W + px) * 4;
      for (let k = 0; k < 3; k += 1) {
        const base = (deep[k] + (hot[k] - deep[k]) * warm) * jitter * lens;
        cimg.data[o + k] = Math.min(255, base + (rim[k] - base) * edge * 0.85);
      }
      cimg.data[o + 3] = 255;
      const dome = Math.max(0, 1 - Math.pow(hx, 1.8));
      const h = 255 * dome;
      himg.data[o] = h;
      himg.data[o + 1] = h;
      himg.data[o + 2] = h;
      himg.data[o + 3] = 255;
    }
  }
  cctx.putImageData(cimg, 0, 0);
  hctx.putImageData(himg, 0, 0);

  const map = new THREE.CanvasTexture(colour);
  map.colorSpace = THREE.SRGBColorSpace;
  map.wrapS = THREE.RepeatWrapping;
  map.anisotropy = 4;
  const bump = new THREE.CanvasTexture(height);
  bump.wrapS = THREE.RepeatWrapping;
  bump.anisotropy = 4;
  return { map, bump };
}

// -- the cuticle --------------------------------------------------------------

/** Fine pitting and bristle sockets, tiled over every chitin surface as a
 *  bump map, so a highlight breaks up like it does on a real insect. */
export function chitinBump(THREE) {
  const N = 128;
  const canvas = canvas2d(N, N);
  const ctx = canvas.getContext('2d');
  ctx.fillStyle = 'rgb(128,128,128)';
  ctx.fillRect(0, 0, N, N);
  for (let i = 0; i < 520; i += 1) {
    const x = random() * N;
    const y = random() * N;
    const r = 0.8 + random() * 2.2;
    const light = random() < 0.45;
    const g = ctx.createRadialGradient(x, y, 0, x, y, r);
    g.addColorStop(0, light ? 'rgba(200,200,200,0.8)' : 'rgba(40,40,40,0.8)');
    g.addColorStop(1, 'rgba(128,128,128,0)');
    ctx.fillStyle = g;
    // Draw each spot wrapped, so the tile has no seam.
    for (const wx of [-N, 0, N]) {
      for (const wy of [-N, 0, N]) {
        ctx.save();
        ctx.translate(wx, wy);
        ctx.beginPath();
        ctx.arc(x, y, r, 0, Math.PI * 2);
        ctx.fill();
        ctx.restore();
      }
    }
  }
  const texture = new THREE.CanvasTexture(canvas);
  texture.wrapS = THREE.RepeatWrapping;
  texture.wrapT = THREE.RepeatWrapping;
  texture.repeat.set(6, 6);
  return texture;
}

// -- the wing -----------------------------------------------------------------

/** The wing outline in its own flat frame: hinge at the origin, +x toward
 *  the tip, +y the leading edge. fly.js builds the Shape from the same
 *  numbers, and the texture below is drawn over the same box. */
export const WING = {
  length: 0.48,
  yMin: -0.09,
  yMax: 0.08,
  outline: [
    // [cp1x, cp1y, cp2x, cp2y, x, y], starting from (0, 0)
    [0.08, 0.05, 0.28, 0.072, 0.415, 0.047],
    [0.47, 0.037, 0.485, -0.012, 0.448, -0.036],
    [0.35, -0.088, 0.15, -0.084, 0.05, -0.042],
    [0.025, -0.028, 0.006, -0.01, 0, 0],
  ],
};

/**
 * The membrane, clear with a faint thin-film shimmer (bands of magenta, gold,
 * green and blue out from the hinge, as a real fly wing shows against a dark
 * ground), the veins of a Drosophila wing, the two crossveins, and a fringe
 * of hairs on the trailing edge. Alpha carries the shape's translucency.
 */
export function wingTexture(THREE) {
  const W = 512;
  const H = 184;
  const canvas = canvas2d(W, H);
  const ctx = canvas.getContext('2d');
  const X = (x) => (x / WING.length) * W;
  const Y = (y) => ((WING.yMax - y) / (WING.yMax - WING.yMin)) * H;

  const outline = () => {
    ctx.beginPath();
    ctx.moveTo(X(0), Y(0));
    for (const [a, b, c, d, e, f] of WING.outline) {
      ctx.bezierCurveTo(X(a), Y(b), X(c), Y(d), X(e), Y(f));
    }
    ctx.closePath();
  };

  ctx.clearRect(0, 0, W, H);
  ctx.save();
  outline();
  ctx.clip();

  ctx.fillStyle = 'rgba(214, 228, 240, 0.34)';
  ctx.fillRect(0, 0, W, H);

  // Thin-film bands, faint.
  const film = ctx.createRadialGradient(X(0.02), Y(0.0), 4, X(0.02), Y(0.0), W * 1.02);
  film.addColorStop(0.0, 'rgba(255,255,255,0)');
  film.addColorStop(0.22, 'rgba(255,110,210,0.26)');
  film.addColorStop(0.36, 'rgba(255,214,110,0.24)');
  film.addColorStop(0.5, 'rgba(110,255,170,0.22)');
  film.addColorStop(0.64, 'rgba(100,180,255,0.26)');
  film.addColorStop(0.78, 'rgba(220,120,255,0.24)');
  film.addColorStop(0.9, 'rgba(255,190,120,0.2)');
  film.addColorStop(1.0, 'rgba(255,255,255,0)');
  ctx.fillStyle = film;
  ctx.fillRect(0, 0, W, H);

  // A slightly smoky hinge.
  const hinge = ctx.createRadialGradient(X(0), Y(0), 2, X(0), Y(0), X(0.07));
  hinge.addColorStop(0, 'rgba(120, 88, 56, 0.7)');
  hinge.addColorStop(1, 'rgba(120, 88, 56, 0)');
  ctx.fillStyle = hinge;
  ctx.fillRect(0, 0, W, H);

  // Veins.
  ctx.strokeStyle = FLY.vein;
  ctx.lineCap = 'round';
  const vein = (width, points) => {
    ctx.lineWidth = width;
    ctx.beginPath();
    ctx.moveTo(X(points[0]), Y(points[1]));
    if (points.length === 6) {
      ctx.quadraticCurveTo(X(points[2]), Y(points[3]), X(points[4]), Y(points[5]));
    } else {
      ctx.lineTo(X(points[2]), Y(points[3]));
    }
    ctx.stroke();
  };
  // Costa: along the leading edge, just inside it.
  ctx.lineWidth = 7;
  ctx.beginPath();
  ctx.moveTo(X(0.01), Y(0.004));
  ctx.bezierCurveTo(X(0.085), Y(0.047), X(0.28), Y(0.066), X(0.44), Y(0.036));
  ctx.stroke();
  vein(4.4, [0.02, 0.0, 0.1, 0.036, 0.2, 0.054]); // L1
  vein(4.2, [0.04, 0.0, 0.2, 0.034, 0.41, 0.043]); // L2
  vein(4.2, [0.04, -0.006, 0.25, 0.006, 0.465, -0.004]); // L3
  vein(4.0, [0.05, -0.016, 0.25, -0.03, 0.43, -0.043]); // L4
  vein(4.0, [0.045, -0.026, 0.17, -0.058, 0.3, -0.078]); // L5
  vein(3.4, [0.2, 0.002, 0.205, -0.024]); // anterior crossvein
  vein(3.4, [0.268, -0.034, 0.285, -0.066]); // posterior crossvein

  // Microtrichia: a light fleck all over, so the membrane is not glass.
  for (let i = 0; i < 900; i += 1) {
    ctx.fillStyle = `rgba(255,255,255,${0.05 + 0.08 * random()})`;
    ctx.fillRect(random() * W, random() * H, 1, 1);
  }
  ctx.restore();

  // A fringe of fine hairs along the trailing edge.
  ctx.strokeStyle = 'rgba(90, 70, 52, 0.45)';
  ctx.lineWidth = 1;
  for (let i = 0; i <= 60; i += 1) {
    const t = i / 60;
    // A point on the trailing edge bezier (third segment of the outline).
    const [a, b, c, d, e, f] = WING.outline[2];
    const sx = 0.448;
    const sy = -0.036;
    const u = 1 - t;
    const x = u * u * u * sx + 3 * u * u * t * a + 3 * u * t * t * c + t * t * t * e;
    const y = u * u * u * sy + 3 * u * u * t * b + 3 * u * t * t * d + t * t * t * f;
    ctx.beginPath();
    ctx.moveTo(X(x), Y(y));
    ctx.lineTo(X(x) - 3, Y(y) + 4);
    ctx.stroke();
  }

  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.anisotropy = 4;
  return texture;
}

// -- glows --------------------------------------------------------------------

/** Where the head glows: black low down, white on the crown. Read through a
 *  sphere's v, so the top of the head capsule lights and the face does not;
 *  parts that must stay dark map into the bottom row. */
export function headGlowMask(THREE) {
  const canvas = canvas2d(4, 64);
  const ctx = canvas.getContext('2d');
  const g = ctx.createLinearGradient(0, 0, 0, 64);
  g.addColorStop(0, '#ffffff');
  g.addColorStop(0.12, '#ffffff');
  g.addColorStop(0.3, '#404040');
  g.addColorStop(0.4, '#000000');
  g.addColorStop(1, '#000000');
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, 4, 64);
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  return texture;
}

/**
 * The room as the fly would see it reflected in its own eyes: a dim warm
 * box, the TV straight ahead as a bright pale-green rectangle, the floor lamp
 * off to the left, a pink smudge of lava lamp, and the string lights as
 * coloured specks up high. An equirectangular map, prefiltered by three once
 * at startup; fly.js scales its strength with the TV's brightness each frame.
 */
export function roomReflection(THREE) {
  const W = 256;
  const H = 128;
  const canvas = canvas2d(W, H);
  const ctx = canvas.getContext('2d');
  const sky = ctx.createLinearGradient(0, 0, 0, H);
  sky.addColorStop(0, '#1a1119');
  sky.addColorStop(0.35, '#3a2430');
  sky.addColorStop(0.5, '#4a3030');
  sky.addColorStop(0.62, '#1f3a38');
  sky.addColorStop(1, '#140e0c');
  ctx.fillStyle = sky;
  ctx.fillRect(0, 0, W, H);

  // three's equirect: straight ahead (-z) is u = 0.25, +x is 0.5, +z 0.75.
  const blob = (u, v, r, colour) => {
    const x = u * W;
    const y = (1 - v) * H;
    const g = ctx.createRadialGradient(x, y, 0, x, y, r);
    g.addColorStop(0, colour);
    g.addColorStop(1, 'rgba(0,0,0,0)');
    ctx.fillStyle = g;
    ctx.fillRect(x - r, y - r, r * 2, r * 2);
  };
  blob(0.25, 0.5, 34, 'rgba(190, 255, 200, 0.55)');
  ctx.fillStyle = '#eaffe6';
  ctx.fillRect(0.25 * W - 12, 0.5 * H - 10, 24, 20);
  blob(0.07, 0.56, 16, 'rgba(255, 196, 120, 0.95)');
  blob(0.97, 0.5, 9, 'rgba(255, 90, 150, 0.8)');
  const bulbs = ['#ff4a3a', '#ffb238', '#4ad86a', '#4a8cff', '#ffe2b0'];
  for (let i = 0; i < 26; i += 1) {
    const u = i / 26 + 0.01;
    ctx.fillStyle = bulbs[i % bulbs.length];
    ctx.fillRect(u * W, 26 + 6 * Math.sin(i * 1.7), 2, 2);
  }

  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.mapping = THREE.EquirectangularReflectionMapping;
  return texture;
}
