/**
 * Every texture in the room, drawn into a canvas here in code.
 *
 * Nothing is downloaded. The big surfaces (floor, wallpaper, panelling, rug,
 * ceiling, the couch plaid, wood grain) each get a small repeating canvas.
 * Everything printed (posters, tape labels, the pizza lid, the clock face)
 * shares one 512 px atlas, so all of it draws in one call; `atlas.uv.name`
 * is the rectangle a Batch part should map into.
 *
 * Randomness is seeded, so the room looks the same on every load and in
 * every take of a recording.
 */

import { RETRO } from './theme.js';

let seed = 1997;
function random() {
  // mulberry32: small, fast, and the same sequence every time.
  seed |= 0;
  seed = (seed + 0x6d2b79f5) | 0;
  let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
  t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
  return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
}

function canvas2d(width, height) {
  const canvas = document.createElement('canvas');
  canvas.width = width;
  canvas.height = height;
  return canvas;
}

function toTexture(THREE, canvas, { repeat = true, srgb = true, anisotropy = 4 } = {}) {
  const texture = new THREE.CanvasTexture(canvas);
  if (srgb) texture.colorSpace = THREE.SRGBColorSpace;
  if (repeat) {
    texture.wrapS = THREE.RepeatWrapping;
    texture.wrapT = THREE.RepeatWrapping;
  }
  texture.anisotropy = anisotropy;
  return texture;
}

/** Speckle a region with light and dark flecks: paper, pile, plaster. */
function speckle(ctx, x, y, w, h, count, alpha, size = 1) {
  for (let i = 0; i < count; i += 1) {
    const light = random() < 0.5;
    ctx.fillStyle = light ? `rgba(255,255,255,${alpha * random()})` : `rgba(0,0,0,${alpha * random()})`;
    ctx.fillRect(x + random() * w, y + random() * h, size, size);
  }
}

// -- big surfaces ---------------------------------------------------------

/** Honey oak planks with staggered ends. One tile is about 3 m square. */
export function floorTexture(THREE) {
  const canvas = canvas2d(512, 512);
  const ctx = canvas.getContext('2d');
  ctx.fillStyle = '#6e4c30';
  ctx.fillRect(0, 0, 512, 512);
  for (let y = 0; y < 512; y += 43) {
    let x = -Math.floor(random() * 200);
    while (x < 512) {
      const length = 180 + Math.floor(random() * 220);
      const shade = Math.floor(random() * 28);
      ctx.fillStyle = `rgb(${120 + shade}, ${84 + shade * 0.7}, ${52 + shade * 0.4})`;
      ctx.fillRect(x, y, length, 41);
      for (let i = 0; i < 9; i += 1) {
        ctx.strokeStyle = `rgba(60,34,16,${0.08 + random() * 0.14})`;
        ctx.lineWidth = 1;
        const gy = y + 3 + random() * 36;
        ctx.beginPath();
        ctx.moveTo(x, gy);
        ctx.bezierCurveTo(x + length * 0.3, gy + (random() - 0.5) * 6, x + length * 0.6, gy + (random() - 0.5) * 6, x + length, gy);
        ctx.stroke();
      }
      ctx.fillStyle = 'rgba(30,16,8,0.55)';
      ctx.fillRect(x + length - 1, y, 2, 41);
      x += length;
    }
    ctx.fillStyle = 'rgba(25,14,6,0.6)';
    ctx.fillRect(0, y + 41, 512, 2);
  }
  return toTexture(THREE, canvas);
}

/** Dusty mauve wallpaper: cream pin stripes and a small teal and mustard
 *  sprig between them. One tile is 0.6 m. */
export function wallpaperTexture(THREE) {
  const canvas = canvas2d(256, 256);
  const ctx = canvas.getContext('2d');
  ctx.fillStyle = RETRO.mauveDeep;
  ctx.fillRect(0, 0, 256, 256);
  ctx.fillStyle = 'rgba(181,143,164,0.22)';
  ctx.fillRect(0, 0, 128, 256);
  for (const x of [0, 128]) {
    ctx.fillStyle = 'rgba(233,220,192,0.55)';
    ctx.fillRect(x + 2, 0, 3, 256);
    ctx.fillRect(x + 9, 0, 1, 256);
  }
  const sprig = (cx, cy) => {
    ctx.fillStyle = RETRO.tealLight;
    ctx.beginPath();
    ctx.ellipse(cx - 7, cy + 4, 7, 3, -0.6, 0, Math.PI * 2);
    ctx.ellipse(cx + 7, cy + 4, 7, 3, 0.6, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = RETRO.mustardLight;
    ctx.beginPath();
    ctx.arc(cx, cy - 3, 5, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = 'rgba(0,0,0,0.25)';
    ctx.beginPath();
    ctx.arc(cx, cy - 3, 2, 0, Math.PI * 2);
    ctx.fill();
  };
  sprig(66, 60);
  sprig(194, 188);
  speckle(ctx, 0, 0, 256, 256, 2600, 0.12);
  return toTexture(THREE, canvas);
}

/** Dark wood-veneer panelling, grooved boards. One tile is 1.2 m wide and
 *  the full panelling height. */
export function panellingTexture(THREE) {
  const canvas = canvas2d(512, 256);
  const ctx = canvas.getContext('2d');
  let x = 0;
  while (x < 512) {
    const width = 58 + Math.floor(random() * 30);
    const shade = Math.floor(random() * 22);
    ctx.fillStyle = `rgb(${86 + shade}, ${56 + shade * 0.6}, ${34 + shade * 0.3})`;
    ctx.fillRect(x, 0, width, 256);
    for (let i = 0; i < 14; i += 1) {
      ctx.strokeStyle = `rgba(35,18,8,${0.1 + random() * 0.2})`;
      ctx.lineWidth = 1 + random() * 1.5;
      const gx = x + random() * width;
      ctx.beginPath();
      ctx.moveTo(gx, 0);
      ctx.bezierCurveTo(gx + (random() - 0.5) * 14, 85, gx + (random() - 0.5) * 14, 170, gx + (random() - 0.5) * 6, 256);
      ctx.stroke();
    }
    ctx.fillStyle = 'rgba(15,8,3,0.8)';
    ctx.fillRect(x + width - 3, 0, 3, 256);
    ctx.fillStyle = 'rgba(255,220,180,0.10)';
    ctx.fillRect(x, 0, 2, 256);
    x += width;
  }
  return toTexture(THREE, canvas);
}

/** Popcorn ceiling. */
export function ceilingTexture(THREE) {
  const canvas = canvas2d(256, 256);
  const ctx = canvas.getContext('2d');
  ctx.fillStyle = '#d9d0c0';
  ctx.fillRect(0, 0, 256, 256);
  for (let i = 0; i < 2600; i += 1) {
    const r = 1 + random() * 2.2;
    ctx.fillStyle = random() < 0.5 ? 'rgba(120,108,90,0.35)' : 'rgba(255,250,240,0.6)';
    ctx.beginPath();
    ctx.arc(random() * 256, random() * 256, r, 0, Math.PI * 2);
    ctx.fill();
  }
  return toTexture(THREE, canvas);
}

/** Dusty teal plaid for the couch. */
export function plaidTexture(THREE) {
  const canvas = canvas2d(256, 256);
  const ctx = canvas.getContext('2d');
  ctx.fillStyle = RETRO.teal;
  ctx.fillRect(0, 0, 256, 256);
  const bands = [
    [0, 64, RETRO.tealDeep, 0.75],
    [100, 18, RETRO.tealDeep, 0.6],
    [150, 6, RETRO.mustard, 0.55],
    [196, 4, RETRO.cream, 0.4],
    [226, 10, RETRO.burgundy, 0.45],
  ];
  for (const [at, width, color, alpha] of bands) {
    ctx.globalAlpha = alpha;
    ctx.fillStyle = color;
    ctx.fillRect(at, 0, width, 256);
    ctx.globalAlpha = alpha * 0.8;
    ctx.fillRect(0, at, 256, width);
  }
  ctx.globalAlpha = 1;
  // A twill: fine diagonal lines, so it reads as woven cloth up close.
  ctx.strokeStyle = 'rgba(0,0,0,0.12)';
  ctx.lineWidth = 1;
  for (let i = -256; i < 256; i += 4) {
    ctx.beginPath();
    ctx.moveTo(i, 0);
    ctx.lineTo(i + 256, 256);
    ctx.stroke();
  }
  speckle(ctx, 0, 0, 256, 256, 1800, 0.12);
  return toTexture(THREE, canvas);
}

/** Pale wood grain in grey, so vertex colours can make it walnut or oak. */
export function woodTexture(THREE) {
  const canvas = canvas2d(256, 256);
  const ctx = canvas.getContext('2d');
  ctx.fillStyle = '#e6e0da';
  ctx.fillRect(0, 0, 256, 256);
  for (let i = 0; i < 70; i += 1) {
    ctx.strokeStyle = `rgba(70,50,35,${0.05 + random() * 0.16})`;
    ctx.lineWidth = 0.6 + random() * 2.2;
    const y = random() * 256;
    ctx.beginPath();
    ctx.moveTo(0, y);
    ctx.bezierCurveTo(85, y + (random() - 0.5) * 18, 170, y + (random() - 0.5) * 18, 256, y);
    ctx.stroke();
  }
  // Two knots.
  for (let k = 0; k < 2; k += 1) {
    const cx = 40 + random() * 176;
    const cy = 40 + random() * 176;
    for (let r = 2; r < 12; r += 2.5) {
      ctx.strokeStyle = 'rgba(70,45,28,0.22)';
      ctx.beginPath();
      ctx.ellipse(cx, cy, r * 2.2, r * 0.8, 0, 0, Math.PI * 2);
      ctx.stroke();
    }
  }
  return toTexture(THREE, canvas);
}

/** A southwestern-pattern rug in rust, teal, mustard and cream, with a
 *  speckled pile. Also used as its own bump map, which is what makes it
 *  read as shag rather than a print. */
export function rugTexture(THREE) {
  const canvas = canvas2d(512, 384);
  const ctx = canvas.getContext('2d');
  ctx.fillStyle = RETRO.cream;
  ctx.fillRect(0, 0, 512, 384);
  ctx.fillStyle = RETRO.rust;
  ctx.fillRect(14, 14, 484, 356);
  ctx.fillStyle = RETRO.creamDark;
  ctx.fillRect(34, 34, 444, 316);
  ctx.fillStyle = RETRO.tealDeep;
  ctx.fillRect(44, 44, 424, 296);

  // A row of stepped diamonds top and bottom.
  const diamond = (cx, cy, r, color) => {
    ctx.fillStyle = color;
    ctx.beginPath();
    ctx.moveTo(cx, cy - r);
    ctx.lineTo(cx + r, cy);
    ctx.lineTo(cx, cy + r);
    ctx.lineTo(cx - r, cy);
    ctx.closePath();
    ctx.fill();
  };
  for (let x = 70; x < 460; x += 44) {
    for (const y of [72, 312]) {
      diamond(x, y, 17, RETRO.mustard);
      diamond(x, y, 9, RETRO.rust);
      diamond(x, y, 3, RETRO.cream);
    }
  }
  // Zigzag bands.
  const zigzag = (y, color, amp) => {
    ctx.strokeStyle = color;
    ctx.lineWidth = 7;
    ctx.beginPath();
    for (let x = 44; x <= 468; x += 16) {
      ctx.lineTo(x, y + ((x / 16) % 2 ? amp : -amp));
    }
    ctx.stroke();
  };
  zigzag(112, RETRO.cream, 7);
  zigzag(272, RETRO.cream, 7);
  // The centre medallion.
  diamond(256, 192, 70, RETRO.rust);
  diamond(256, 192, 54, RETRO.mustard);
  diamond(256, 192, 38, RETRO.tealDeep);
  diamond(256, 192, 20, RETRO.cream);
  for (const side of [-1, 1]) {
    diamond(256 + side * 130, 192, 30, RETRO.mauve);
    diamond(256 + side * 130, 192, 14, RETRO.cream);
  }
  // Pile: dense short flecks.
  for (let i = 0; i < 16000; i += 1) {
    const x = random() * 512;
    const y = random() * 384;
    ctx.fillStyle = random() < 0.5 ? 'rgba(0,0,0,0.22)' : 'rgba(255,245,220,0.14)';
    ctx.fillRect(x, y, 1, 2 + random() * 2);
  }
  return toTexture(THREE, canvas, { repeat: false });
}

/** The night outside the window: deep blue, stars, a moon, rooftops and a
 *  streetlight's orange pool. Drawn unlit, so it glows a little. */
export function skyTexture(THREE) {
  const canvas = canvas2d(256, 256);
  const ctx = canvas.getContext('2d');
  const gradient = ctx.createLinearGradient(0, 0, 0, 256);
  gradient.addColorStop(0, '#070b1f');
  gradient.addColorStop(0.6, RETRO.sky);
  gradient.addColorStop(1, '#2b2140');
  ctx.fillStyle = gradient;
  ctx.fillRect(0, 0, 256, 256);
  for (let i = 0; i < 70; i += 1) {
    ctx.fillStyle = `rgba(230,235,255,${0.3 + random() * 0.7})`;
    ctx.fillRect(random() * 256, random() * 150, random() < 0.15 ? 2 : 1, random() < 0.15 ? 2 : 1);
  }
  const moon = ctx.createRadialGradient(186, 58, 2, 186, 58, 46);
  moon.addColorStop(0, 'rgba(223,232,255,0.5)');
  moon.addColorStop(1, 'rgba(223,232,255,0)');
  ctx.fillStyle = moon;
  ctx.fillRect(120, 0, 136, 120);
  ctx.fillStyle = RETRO.moon;
  ctx.beginPath();
  ctx.arc(186, 58, 15, 0, Math.PI * 2);
  ctx.fill();
  // Streetlight glow, then the roofs in front of it.
  const lamp = ctx.createRadialGradient(70, 180, 2, 70, 180, 70);
  lamp.addColorStop(0, 'rgba(255,179,90,0.75)');
  lamp.addColorStop(1, 'rgba(255,179,90,0)');
  ctx.fillStyle = lamp;
  ctx.fillRect(0, 100, 160, 156);
  ctx.fillStyle = '#05060c';
  ctx.beginPath();
  ctx.moveTo(0, 256);
  ctx.lineTo(0, 200);
  ctx.lineTo(40, 170);
  ctx.lineTo(95, 205);
  ctx.lineTo(120, 205);
  ctx.lineTo(120, 190);
  ctx.lineTo(160, 160);
  ctx.lineTo(210, 195);
  ctx.lineTo(256, 190);
  ctx.lineTo(256, 256);
  ctx.closePath();
  ctx.fill();
  ctx.fillStyle = '#ffd98a';
  ctx.fillRect(28, 212, 8, 8);
  ctx.fillRect(172, 205, 7, 9);
  ctx.fillStyle = '#0b0c12';
  ctx.fillRect(68, 160, 3, 96);
  ctx.fillStyle = '#ffcf8a';
  ctx.fillRect(64, 157, 11, 4);
  return toTexture(THREE, canvas, { repeat: false });
}

/** Stripes of moonlight through the blinds, for a decal on the floor. */
export function blindLightTexture(THREE) {
  const canvas = canvas2d(128, 128);
  const ctx = canvas.getContext('2d');
  ctx.clearRect(0, 0, 128, 128);
  for (let y = 4; y < 124; y += 12) {
    const gradient = ctx.createLinearGradient(0, 0, 128, 0);
    gradient.addColorStop(0, 'rgba(255,255,255,0)');
    gradient.addColorStop(0.25, 'rgba(255,255,255,0.8)');
    gradient.addColorStop(0.75, 'rgba(255,255,255,0.8)');
    gradient.addColorStop(1, 'rgba(255,255,255,0)');
    ctx.fillStyle = gradient;
    ctx.fillRect(0, y, 128, 6);
  }
  const fade = ctx.createLinearGradient(0, 0, 0, 128);
  fade.addColorStop(0, 'rgba(0,0,0,1)');
  fade.addColorStop(1, 'rgba(0,0,0,0)');
  ctx.globalCompositeOperation = 'destination-in';
  ctx.fillStyle = fade;
  ctx.fillRect(0, 0, 128, 128);
  return toTexture(THREE, canvas, { repeat: false });
}

/** Seven-segment style LED readouts: the VCR's blinking 12:00 on the left,
 *  the TV's channel 03 on the right. */
export function ledTexture(THREE) {
  const canvas = canvas2d(128, 32);
  const ctx = canvas.getContext('2d');
  ctx.fillStyle = '#05080a';
  ctx.fillRect(0, 0, 128, 32);
  ctx.font = 'bold 22px monospace';
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillStyle = RETRO.ledGreen;
  ctx.fillText('12:00', 40, 17);
  ctx.fillStyle = '#1a0605';
  ctx.fillRect(84, 0, 44, 32);
  ctx.fillStyle = RETRO.ledRed;
  ctx.fillText('03', 106, 17);
  const texture = toTexture(THREE, canvas, { repeat: false });
  texture.generateMipmaps = false;
  texture.minFilter = THREE.LinearFilter;
  return texture;
}

// -- the atlas --------------------------------------------------------------

const ATLAS = 512;

/**
 * Everything printed, in one canvas. Returns { texture, uv } where `uv.name`
 * is [u0, v0, u1, v1] for a Batch part. The CanvasTexture flips y, so the
 * canvas top is v = 1.
 */
export function buildAtlas(THREE) {
  const canvas = canvas2d(ATLAS, ATLAS);
  const ctx = canvas.getContext('2d');
  ctx.fillStyle = '#ffffff';
  ctx.fillRect(0, 0, ATLAS, ATLAS);
  const uv = {};
  const region = (name, x, y, w, h, draw) => {
    ctx.save();
    ctx.beginPath();
    ctx.rect(x, y, w, h);
    ctx.clip();
    ctx.translate(x, y);
    draw(ctx, w, h);
    ctx.restore();
    // Pull in half a texel so a neighbour never bleeds in at the edge.
    uv[name] = [(x + 0.5) / ATLAS, 1 - (y + h - 0.5) / ATLAS, (x + w - 0.5) / ATLAS, 1 - (y + 0.5) / ATLAS];
  };
  const text = (c, words, x, y, font, color, align = 'center') => {
    c.font = font;
    c.fillStyle = color;
    c.textAlign = align;
    c.textBaseline = 'middle';
    c.fillText(words, x, y);
  };

  // A rave flyer for a festival that never happened.
  region('posterFest', 0, 0, 160, 224, (c, w, h) => {
    const g = c.createLinearGradient(0, 0, 0, h);
    g.addColorStop(0, '#2a0f45');
    g.addColorStop(0.55, '#7a2a6e');
    g.addColorStop(1, '#f08a3c');
    c.fillStyle = g;
    c.fillRect(0, 0, w, h);
    // A smiling fly: a yellow face with two wings and big eyes.
    c.fillStyle = 'rgba(200,240,255,0.55)';
    c.beginPath();
    c.ellipse(52, 96, 30, 14, -0.5, 0, Math.PI * 2);
    c.ellipse(108, 96, 30, 14, 0.5, 0, Math.PI * 2);
    c.fill();
    c.fillStyle = '#ffd23a';
    c.beginPath();
    c.arc(80, 112, 32, 0, Math.PI * 2);
    c.fill();
    c.fillStyle = '#c0231e';
    c.beginPath();
    c.arc(66, 104, 9, 0, Math.PI * 2);
    c.arc(94, 104, 9, 0, Math.PI * 2);
    c.fill();
    c.strokeStyle = '#2a0f45';
    c.lineWidth = 4;
    c.beginPath();
    c.arc(80, 116, 16, 0.2 * Math.PI, 0.8 * Math.PI);
    c.stroke();
    c.lineWidth = 3;
    c.strokeStyle = '#ffd23a';
    c.beginPath();
    c.moveTo(72, 82);
    c.lineTo(62, 64);
    c.moveTo(88, 82);
    c.lineTo(98, 64);
    c.stroke();
    text(c, 'BUZZ', 80, 26, 'italic 900 34px sans-serif', '#5ff2e0');
    text(c, 'FEST', 80, 54, 'italic 900 26px sans-serif', '#ffd23a');
    text(c, "'97", 128, 150, 'bold 22px sans-serif', '#ffffff');
    text(c, 'THE COMPOUND EYES', 80, 170, 'bold 11px sans-serif', '#fff3d6');
    text(c, 'LARVA LAMP', 80, 186, 'bold 11px sans-serif', '#fff3d6');
    text(c, 'FRUIT PUNCH', 80, 202, 'bold 11px sans-serif', '#fff3d6');
  });

  // The motivational one, with a fly on the branch.
  region('posterHang', 160, 0, 160, 224, (c, w, h) => {
    const g = c.createLinearGradient(0, 0, 0, h);
    g.addColorStop(0, '#7fc4e8');
    g.addColorStop(1, '#d9f0f7');
    c.fillStyle = g;
    c.fillRect(0, 0, w, h);
    c.strokeStyle = '#5a3a22';
    c.lineWidth = 9;
    c.beginPath();
    c.moveTo(0, 40);
    c.quadraticCurveTo(80, 30, 160, 52);
    c.stroke();
    c.fillStyle = '#4f8a3a';
    for (const [lx, ly] of [
      [20, 32],
      [120, 38],
      [140, 48],
    ]) {
      c.beginPath();
      c.ellipse(lx, ly, 12, 5, 0.5, 0, Math.PI * 2);
      c.fill();
    }
    // One leg on the branch, the rest dangling.
    c.strokeStyle = '#3a2a1c';
    c.lineWidth = 2;
    c.beginPath();
    c.moveTo(82, 38);
    c.lineTo(80, 84);
    c.stroke();
    c.fillStyle = '#b9844a';
    c.beginPath();
    c.ellipse(80, 108, 16, 26, 0, 0, Math.PI * 2);
    c.fill();
    c.fillStyle = '#6d4a28';
    for (let i = 0; i < 3; i += 1) c.fillRect(66, 110 + i * 9, 28, 3);
    c.fillStyle = '#e03a2b';
    c.beginPath();
    c.arc(72, 88, 7, 0, Math.PI * 2);
    c.arc(88, 88, 7, 0, Math.PI * 2);
    c.fill();
    c.fillStyle = 'rgba(255,255,255,0.6)';
    c.beginPath();
    c.ellipse(60, 110, 16, 7, 0.8, 0, Math.PI * 2);
    c.ellipse(100, 110, 16, 7, -0.8, 0, Math.PI * 2);
    c.fill();
    c.strokeStyle = '#3a2a1c';
    c.beginPath();
    for (const dx of [-8, 0, 8]) {
      c.moveTo(80 + dx, 128);
      c.lineTo(80 + dx * 1.8, 146);
    }
    c.stroke();
    text(c, 'HANG IN', 80, 178, '900 24px serif', '#16324a');
    text(c, 'THERE', 80, 204, '900 24px serif', '#16324a');
  });

  // A felt pennant, drawn as a triangle pointing right.
  region('pennant', 320, 0, 192, 80, (c, w, h) => {
    c.fillStyle = RETRO.teal;
    c.fillRect(0, 0, w, h);
    c.fillStyle = RETRO.mustard;
    c.fillRect(0, 0, 18, h);
    text(c, 'GO FLIES!', 88, 42, 'italic 900 26px sans-serif', RETRO.mustardLight);
  });

  // September 1998. The 28th is circled.
  region('calendar', 320, 80, 96, 144, (c, w, h) => {
    c.fillStyle = '#f7f1e3';
    c.fillRect(0, 0, w, h);
    const g = c.createLinearGradient(0, 0, 0, 64);
    g.addColorStop(0, '#ff9e5e');
    g.addColorStop(1, '#ffd98a');
    c.fillStyle = g;
    c.fillRect(4, 4, w - 8, 60);
    c.fillStyle = '#e8743a';
    c.beginPath();
    c.arc(48, 52, 16, Math.PI, 0);
    c.fill();
    c.fillStyle = '#2f6f8c';
    c.fillRect(4, 52, w - 8, 12);
    text(c, 'SEPTEMBER 1998', 48, 74, 'bold 9px sans-serif', '#3a2a2a');
    c.fillStyle = '#6a5a5a';
    const first = 2; // the first of September 1998 was a Tuesday
    for (let day = 1; day <= 30; day += 1) {
      const cell = day - 1 + first;
      const cx = 8 + (cell % 7) * 12.5;
      const cy = 88 + Math.floor(cell / 7) * 11;
      text(c, String(day), cx, cy, '8px sans-serif', '#4a3a3a');
      if (day === 28) {
        c.strokeStyle = '#d4202a';
        c.lineWidth = 1.5;
        c.beginPath();
        c.arc(cx, cy, 6, 0, Math.PI * 2);
        c.stroke();
      }
    }
  });

  region('clock', 416, 80, 96, 96, (c, w) => {
    c.fillStyle = RETRO.cream;
    c.fillRect(0, 0, w, w);
    c.fillStyle = '#fbf5e6';
    c.beginPath();
    c.arc(48, 48, 44, 0, Math.PI * 2);
    c.fill();
    c.strokeStyle = '#3a2a2a';
    for (let i = 0; i < 12; i += 1) {
      const a = (i / 12) * Math.PI * 2;
      c.lineWidth = i % 3 === 0 ? 3 : 1.5;
      c.beginPath();
      c.moveTo(48 + Math.sin(a) * 36, 48 - Math.cos(a) * 36);
      c.lineTo(48 + Math.sin(a) * 42, 48 - Math.cos(a) * 42);
      c.stroke();
    }
    text(c, '12', 48, 22, 'bold 12px sans-serif', '#3a2a2a');
    text(c, '3', 74, 49, 'bold 12px sans-serif', '#3a2a2a');
    text(c, '6', 48, 75, 'bold 12px sans-serif', '#3a2a2a');
    text(c, '9', 22, 49, 'bold 12px sans-serif', '#3a2a2a');
  });

  region('cartBug', 416, 176, 48, 48, (c, w, h) => {
    c.fillStyle = '#2e7d4f';
    c.fillRect(0, 0, w, h);
    c.fillStyle = '#ffd23a';
    c.fillRect(0, 30, w, h - 30);
    c.fillStyle = '#e03a2b';
    c.fillRect(20, 12, 8, 8);
    text(c, 'BUG QUEST', 24, 38, 'bold 7px sans-serif', '#1a2a1a');
  });
  region('cartMoth', 464, 176, 48, 48, (c, w, h) => {
    c.fillStyle = '#26345e';
    c.fillRect(0, 0, w, h);
    c.fillStyle = '#ff6a3a';
    for (let i = 0; i < 4; i += 1) c.fillRect(0, 6 + i * 6, w, 2);
    text(c, 'MOTH', 24, 36, 'italic 900 11px sans-serif', '#ffffff');
    text(c, 'RACER', 24, 44, 'italic 900 7px sans-serif', '#ffd23a');
  });

  // Hand-written VHS spine labels, twelve of them, 128x16 each.
  const tapes = [
    'SAT AM CARTOONS',
    "BIRTHDAY '97",
    'DO NOT TAPE OVER!!',
    'MOVIE NIGHT',
    'RECORDED 4/98',
    'FAMILY TRIP',
    'SCI-FI MARATHON',
    'blank?',
    'MUSIC VIDEOS',
    'BUG DOCUMENTARY',
    "SOCCER '96",
    'KARATE CLASS',
  ];
  tapes.forEach((label, i) => {
    const col = i % 2;
    const row = Math.floor(i / 2);
    region(`vhs${i}`, col * 128, 224 + row * 16, 128, 16, (c, w, h) => {
      c.fillStyle = '#f4f0e6';
      c.fillRect(0, 0, w, h);
      c.fillStyle = [RETRO.rust, RETRO.teal, RETRO.mustard, RETRO.mauve][i % 4];
      c.fillRect(0, 0, 10, h);
      text(c, label, 68, 9, 'italic 10px cursive, sans-serif', i % 3 ? '#1b2a6b' : '#222222');
    });
  });

  region('pizzaLid', 256, 224, 128, 128, (c, w, h) => {
    c.fillStyle = '#c9a57a';
    c.fillRect(0, 0, w, h);
    speckle(c, 0, 0, w, h, 900, 0.12);
    c.fillStyle = '#c0231e';
    c.beginPath();
    c.arc(64, 56, 34, 0, Math.PI * 2);
    c.fill();
    c.fillStyle = '#f7f1e3';
    c.beginPath();
    c.arc(64, 56, 27, 0, Math.PI * 2);
    c.fill();
    text(c, 'HOT', 64, 48, '900 18px sans-serif', '#c0231e');
    text(c, 'PIZZA', 64, 66, '900 14px sans-serif', '#2e7d4f');
    text(c, 'FAST & FRESH', 64, 106, 'bold 11px sans-serif', '#7a2a1a');
  });

  region('canFizz', 384, 224, 64, 64, (c, w, h) => {
    c.fillStyle = '#c0231e';
    c.fillRect(0, 0, w, h);
    c.fillStyle = '#f7f1e3';
    c.beginPath();
    c.moveTo(0, 40);
    c.quadraticCurveTo(32, 20, 64, 40);
    c.lineTo(64, 48);
    c.quadraticCurveTo(32, 28, 0, 48);
    c.fill();
    text(c, 'FIZZ', 32, 24, 'italic 900 16px sans-serif', '#ffffff');
  });
  region('canGrape', 448, 224, 64, 64, (c, w, h) => {
    c.fillStyle = '#5a2a78';
    c.fillRect(0, 0, w, h);
    c.fillStyle = '#9adf4a';
    c.fillRect(0, 40, w, 6);
    text(c, 'GRAPE', 32, 26, 'italic 900 13px sans-serif', '#ffd23a');
  });

  region('boombox', 384, 288, 128, 64, (c, w, h) => {
    c.fillStyle = '#35373d';
    c.fillRect(0, 0, w, h);
    c.fillStyle = '#16171a';
    c.fillRect(34, 12, 60, 34);
    c.fillStyle = '#6a6d74';
    c.fillRect(40, 18, 48, 22);
    c.fillStyle = '#1b1c20';
    c.beginPath();
    c.arc(52, 29, 5, 0, Math.PI * 2);
    c.arc(76, 29, 5, 0, Math.PI * 2);
    c.fill();
    c.fillStyle = '#c9ccd2';
    for (let i = 0; i < 6; i += 1) c.fillRect(38 + i * 9, 52, 5, 8);
    text(c, 'STEREO', 64, 6, 'bold 7px sans-serif', '#c9ccd2');
    c.fillStyle = '#ff4a3a';
    c.fillRect(104, 8, 6, 3);
  });

  // The old landscape print, now one more thing in the atlas.
  region('landscape', 0, 352, 160, 120, (c, w, h) => {
    c.fillStyle = '#2b3a4a';
    c.fillRect(0, 0, w, h);
    c.fillStyle = '#e89a5a';
    c.fillRect(0, 50, w, 30);
    c.fillStyle = '#4c6b52';
    c.beginPath();
    c.moveTo(0, 92);
    c.lineTo(50, 50);
    c.lineTo(92, 88);
    c.lineTo(125, 60);
    c.lineTo(160, 94);
    c.lineTo(160, 120);
    c.lineTo(0, 120);
    c.closePath();
    c.fill();
    c.fillStyle = '#f2d98a';
    c.beginPath();
    c.arc(123, 33, 12, 0, Math.PI * 2);
    c.fill();
  });

  // Book spines and game-box spines for the shelf.
  region('books', 160, 352, 160, 64, (c, w, h) => {
    let x = 0;
    const colors = [RETRO.burgundy, RETRO.tealDeep, RETRO.mustard, '#2d3b5e', RETRO.olive, RETRO.rust, RETRO.mauveDeep, RETRO.cream];
    let i = 0;
    while (x < w) {
      const width = 10 + Math.floor(random() * 10);
      c.fillStyle = colors[i % colors.length];
      c.fillRect(x, 0, width, h);
      c.fillStyle = 'rgba(230,200,120,0.8)';
      c.fillRect(x + 2, 8, width - 4, 2);
      c.fillRect(x + 2, h - 12, width - 4, 2);
      c.fillStyle = 'rgba(0,0,0,0.35)';
      c.fillRect(x + width - 1, 0, 1, h);
      x += width;
      i += 1;
    }
  });
  region('games', 160, 416, 160, 48, (c, w, h) => {
    const colors = ['#c0231e', '#2e7d4f', '#26345e', '#e0a020', '#5a2a78', '#1b1c20'];
    for (let i = 0; i < 8; i += 1) {
      c.fillStyle = colors[i % colors.length];
      c.fillRect(i * 20, 0, 20, h);
      c.fillStyle = '#f7f1e3';
      c.fillRect(i * 20 + 4, 6, 12, 22);
      c.fillStyle = 'rgba(0,0,0,0.4)';
      c.fillRect(i * 20 + 19, 0, 1, h);
    }
  });

  region('keypad', 320, 352, 64, 64, (c, w, h) => {
    c.fillStyle = RETRO.tealDeep;
    c.fillRect(0, 0, w, h);
    for (let r = 0; r < 4; r += 1) {
      for (let k = 0; k < 3; k += 1) {
        c.fillStyle = '#e9e4d6';
        c.fillRect(8 + k * 17, 6 + r * 14, 13, 10);
      }
    }
  });

  region('cassette', 320, 416, 64, 48, (c, w, h) => {
    c.fillStyle = '#f4f0e6';
    c.fillRect(0, 0, w, h);
    c.fillStyle = RETRO.rust;
    c.fillRect(0, 0, w, 8);
    c.fillStyle = '#1b1c20';
    c.fillRect(14, 22, 36, 14);
    text(c, "MIX '98", 32, 15, 'italic 9px cursive, sans-serif', '#1b2a6b');
  });

  region('plaque', 384, 352, 128, 40, (c, w, h) => {
    c.fillStyle = '#b3201c';
    c.fillRect(0, 0, w, h);
    c.strokeStyle = '#f7f1e3';
    c.lineWidth = 2;
    c.strokeRect(4, 4, w - 8, h - 8);
    text(c, 'IN CASE OF', 64, 14, 'bold 11px sans-serif', '#f7f1e3');
    text(c, 'EMERGENCY', 64, 28, '900 14px sans-serif', '#f7f1e3');
  });

  // The swatter's head: red plastic with a grid of holes.
  region('swatter', 384, 392, 64, 64, (c, w, h) => {
    c.fillStyle = '#d22a24';
    c.fillRect(0, 0, w, h);
    c.fillStyle = 'rgba(40,10,10,0.75)';
    for (let y = 4; y < h - 2; y += 6) {
      for (let x = 4; x < w - 2; x += 6) c.fillRect(x, y, 3, 3);
    }
  });

  region('rewind', 448, 392, 64, 32, (c, w, h) => {
    c.fillStyle = '#ffd23a';
    c.fillRect(0, 0, w, h);
    text(c, 'BE KIND', 32, 11, '900 10px sans-serif', '#1b2a6b');
    text(c, 'REWIND', 32, 23, '900 10px sans-serif', '#1b2a6b');
  });

  const texture = toTexture(THREE, canvas, { repeat: false, anisotropy: 8 });
  return { texture, uv };
}
