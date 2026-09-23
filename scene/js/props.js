/**
 * The clutter that makes the room a late-1990s living room.
 *
 * Almost everything here is static and goes into the shared batches from
 * room.js (wood, fabric, matte, gloss, metal, art, glow), so it costs a few
 * draw calls in all. The handful of things that move get their own small
 * meshes and are driven by `update(dt, elapsed)`:
 *
 *   lava lamp      five wax blobs rising and sinking (one instanced mesh)
 *   string lights  a slow twinkle on the bulbs and their glow on the wall
 *   fish tank      three goldfish swimming back and forth
 *   wall clock     the real local time
 *   VCR            the 12:00 that nobody ever set, blinking
 *
 * None of it means anything about the brain; it is set dressing. What the fly
 * does stays the only thing in the room that reports on the network.
 *
 * All invented: no real brands, logos or characters. Placement is in metres in
 * the room's frame (room.js has the layout).
 */

import { ledTexture, skyTexture, blindLightTexture } from './textures.js';
import { CABLE_FLOOR, RETRO, hex } from './theme.js';
import { Batch } from './batch.js';

const C = (name) => hex(RETRO[name]);
const BACK = -2.45;
const REAR = 2.6;
const SIDE = 3.4;

// -- the TV cabinet, the VCR, tapes ----------------------------------------

function vhsTape(kit, index, o) {
  // A tape lying flat, its spine label facing +z in its own frame.
  kit.gloss.box(0.19, 0.026, 0.105, { ...o, color: C('black') });
  kit.art.plane(0.18, 0.022, { ...o, z: (o.z || 0) + 0.0535, uv: kit.atlas.uv[`vhs${index % 12}`] });
}

function tvCabinet(kit) {
  const { wood, gloss, matte } = kit;
  const veneer = C('veneer');
  wood.at(0, 0, -2.0);
  wood.box(1.4, 0.035, 0.52, { y: 0.2725, color: veneer });
  wood.box(1.36, 0.03, 0.5, { y: 0.045, color: veneer });
  for (const side of [-1, 1]) {
    wood.box(0.035, 0.225, 0.52, { x: side * 0.6825, y: 0.1425, color: veneer });
    for (const z of [-0.2, 0.2]) {
      wood.cyl(0.025, 0.02, 0.03, 8, { x: side * 0.62, y: 0.015, z, color: C('walnut') });
    }
  }
  wood.box(0.025, 0.195, 0.48, { x: 0.1, y: 0.1575, color: veneer });
  wood.box(1.36, 0.225, 0.015, { y: 0.1425, z: -0.25, color: C('walnut') });
  // A darker lip along the front of the top.
  wood.box(1.4, 0.012, 0.012, { y: 0.255, z: 0.26, color: C('walnut') });
  wood.at();

  // The VCR in the left bay.
  gloss.at(-0.3, 0, -1.94);
  gloss.box(0.48, 0.085, 0.34, { y: 0.1025, color: C('charcoal') });
  gloss.box(0.25, 0.016, 0.004, { x: -0.07, y: 0.115, z: 0.171, color: C('black') });
  for (let i = 0; i < 5; i += 1) {
    gloss.box(0.018, 0.008, 0.006, { x: -0.19 + i * 0.03, y: 0.078, z: 0.171, color: C('greyPlastic') });
  }
  gloss.at();
  matte.box(0.44, 0.004, 0.3, { x: -0.3, y: 0.147, z: -1.94, color: C('black') });
  vhsTape(kit, 3, { x: -0.3, y: 0.16, z: -1.93 });
  kit.art.at(-0.3, 0.1745, -1.93);
  kit.art.plane(0.1, 0.05, { rx: -Math.PI / 2, x: 0.03, uv: kit.atlas.uv.rewind });
  kit.art.at();

  // Tapes stacked in the right bay.
  for (let i = 0; i < 4; i += 1) {
    vhsTape(kit, i + 5, { x: 0.38 + (i % 2) * 0.01, y: 0.073 + i * 0.027, z: -1.84, ry: (i % 3) * 0.03 });
  }
}

/** The VCR clock and the TV's channel readout share one tiny texture. */
function ledDisplays(THREE, group) {
  const material = new THREE.MeshBasicMaterial({ map: ledTexture(THREE), toneMapped: false });
  const vcr = new THREE.PlaneGeometry(0.1, 0.028);
  squeezeUv(vcr, [0, 0, 0.62, 1]);
  const vcrLed = new THREE.Mesh(vcr, material);
  vcrLed.position.set(-0.13, 0.1, -1.768);
  group.add(vcrLed);
  const channel = new THREE.PlaneGeometry(0.05, 0.028);
  squeezeUv(channel, [0.66, 0, 1, 1]);
  const channelLed = new THREE.Mesh(channel, material);
  channelLed.position.set(0.4, 0.35, -1.666);
  group.add(channelLed);
  return vcrLed;
}

function squeezeUv(geometry, [u0, v0, u1, v1]) {
  const uv = geometry.attributes.uv;
  for (let i = 0; i < uv.count; i += 1) {
    uv.setXY(i, u0 + uv.getX(i) * (u1 - u0), v0 + uv.getY(i) * (v1 - v0));
  }
}

// -- the console and its cable ---------------------------------------------

function gameConsole(kit) {
  const { gloss, art, glow } = kit;
  const x = 0.42;
  const z = -1.42;
  gloss.at(x, 0, z, -0.12);
  gloss.box(0.3, 0.06, 0.24, { y: 0.03, color: C('beige') });
  gloss.box(0.24, 0.02, 0.17, { y: 0.07, z: -0.02, color: C('beigeDark') });
  gloss.box(0.14, 0.006, 0.03, { y: 0.082, z: -0.03, color: C('black') });
  gloss.box(0.12, 0.085, 0.022, { y: 0.12, z: -0.03, color: C('greyPlastic') });
  gloss.box(0.03, 0.012, 0.02, { x: -0.08, y: 0.086, z: 0.05, color: C('rust') });
  gloss.box(0.025, 0.012, 0.02, { x: 0.0, y: 0.086, z: 0.05, color: C('greyPlastic') });
  for (const px of [-0.05, 0.05]) gloss.box(0.035, 0.02, 0.004, { x: px, y: 0.03, z: 0.121, color: C('black') });
  // The second cartridge, lying on the floor beside it.
  gloss.box(0.12, 0.022, 0.085, { x: 0.27, y: 0.011, z: 0.05, ry: 0.5, color: C('charcoal') });
  gloss.at();

  art.at(x, 0, z, -0.12);
  art.plane(0.1, 0.06, { y: 0.125, z: -0.018, uv: kit.atlas.uv.cartBug });
  art.plane(0.1, 0.07, { x: 0.27, y: 0.0225, z: 0.05, rx: -Math.PI / 2, rz: 0.5, uv: kit.atlas.uv.cartMoth });
  art.at();
  glow.at(x, 0, z, -0.12);
  glow.box(0.012, 0.004, 0.012, { x: -0.12, y: 0.0835, z: 0.07, color: C('ledRed') });
  glow.at();

  // The controller cable: out of port one, across the rug, a tangle, under
  // the coffee table, to the front of the couch. The fly's controller brings
  // the rest of it down to CABLE_FLOOR (fly.js).
  const y = 0.012;
  kit.gloss.tube(
    [
      [x - 0.05, 0.03, z + 0.125],
      [x - 0.06, y, z + 0.25],
      [0.3, y, -0.95],
      [0.26, y, -0.45],
      [0.3, y, 0.05],
      [0.46, y, 0.3],
      [0.55, 0.018, 0.5],
      [0.4, 0.024, 0.62],
      [0.26, y, 0.48],
      [0.36, y, 0.3],
      [0.3, y, 0.62],
      [0.14, y, 0.78],
      CABLE_FLOOR,
    ],
    0.009,
    { color: C('cable'), segments: 220 },
  );
}

// -- the coffee table ------------------------------------------------------

function coffeeTable(THREE, kit) {
  const { wood, matte, gloss, metal, art } = kit;
  const cx = 0.05;
  const cz = -0.3;
  const top = 0.3625;
  const oak = C('oak');
  wood.at(cx, 0, cz);
  wood.box(1.05, 0.045, 0.52, { y: 0.34, color: oak });
  wood.box(1.09, 0.02, 0.56, { y: 0.31, color: C('walnut') });
  wood.box(0.95, 0.025, 0.44, { y: 0.1, color: C('veneer') });
  for (const sx of [-1, 1]) {
    for (const sz of [-1, 1]) wood.cyl(0.028, 0.02, 0.3, 10, { x: sx * 0.46, y: 0.15, z: sz * 0.21, color: C('walnut') });
  }
  wood.at();

  // Two pizza boxes, one slice left on top.
  matte.at(cx - 0.24, top, cz + 0.02, 0.1);
  matte.box(0.36, 0.045, 0.36, { y: 0.0225, color: 0xb89468 });
  matte.box(0.36, 0.045, 0.36, { y: 0.0675, ry: 0.22, color: 0xc4a07a });
  const slice = new THREE.CylinderGeometry(0.15, 0.15, 0.012, 10, 1, false, 0, 0.62);
  matte.add(slice, { x: -0.05, y: 0.097, z: 0.07, ry: 2.2, color: 0xe8b04a });
  matte.add(new THREE.CylinderGeometry(0.152, 0.152, 0.018, 10, 1, false, 0, 0.62), { x: -0.05, y: 0.093, z: 0.07, ry: 2.2, color: 0xc98b44 });
  // Pepperoni, placed in the slice's own polar frame: radius, angle.
  for (const [r, a] of [
    [0.05, 0.3],
    [0.09, 0.18],
    [0.11, 0.42],
  ]) {
    const lx = r * Math.sin(a);
    const lz = r * Math.cos(a);
    const x = lx * Math.cos(2.2) + lz * Math.sin(2.2);
    const z = -lx * Math.sin(2.2) + lz * Math.cos(2.2);
    matte.cyl(0.013, 0.013, 0.004, 10, { x: x - 0.05, y: 0.104, z: z + 0.07, color: 0xa3261e });
  }
  matte.at();
  art.at(cx - 0.24, top, cz + 0.02, 0.1 + 0.22);
  art.plane(0.33, 0.33, { y: 0.0905, rx: -Math.PI / 2, uv: kit.atlas.uv.pizzaLid });
  art.at();

  // Cans: two standing, one crushed on its side.
  const can = (x, z, name, o = {}) => {
    const body = new THREE.CylinderGeometry(0.033, 0.033, 0.12, 16, 1, true);
    art.add(body, { x, y: top + 0.06, z, uv: kit.atlas.uv[name], ...o });
    if (!o.rz) metal.cyl(0.031, 0.033, 0.006, 16, { x, y: top + 0.123, z, color: C('chrome') });
    if (!o.rz) metal.cyl(0.033, 0.03, 0.006, 16, { x, y: top + 0.003, z, color: C('chrome') });
  };
  can(cx + 0.2, cz + 0.1, 'canFizz');
  can(cx + 0.28, cz - 0.07, 'canGrape', { ry: 1.4 });
  art.add(new THREE.CylinderGeometry(0.033, 0.03, 0.09, 16, 1, false), {
    x: cx + 0.4,
    y: top + 0.031,
    z: cz + 0.14,
    rz: Math.PI / 2,
    ry: 0.6,
    uv: kit.atlas.uv.canFizz,
  });

  // A bowl of cheese puffs.
  const bowl = new THREE.SphereGeometry(0.12, 18, 8, 0, Math.PI * 2, Math.PI / 2, Math.PI / 2);
  gloss.add(bowl, { x: cx + 0.02, y: top + 0.07, z: cz - 0.12, sy: 0.6, color: C('tealLight') });
  matte.cyl(0.115, 0.115, 0.01, 18, { x: cx + 0.02, y: top + 0.068, z: cz - 0.12, color: 0xd9822b });
  for (let i = 0; i < 16; i += 1) {
    const a = i * 2.4;
    const r = 0.025 + (i % 5) * 0.017;
    matte.sphere(0.02, {
      x: cx + 0.02 + Math.cos(a) * r,
      y: top + 0.08 + (i % 3) * 0.008,
      z: cz - 0.12 + Math.sin(a) * r,
      sx: 1.6,
      ry: a,
      color: i % 2 ? 0xf09a2e : 0xe07d1e,
    }, 7, 5);
  }

  // The TV remote.
  gloss.at(cx + 0.12, top, cz + 0.17, 0.5);
  gloss.box(0.05, 0.022, 0.19, { y: 0.011, color: C('black') });
  const buttons = [C('rust'), C('greyPlastic'), C('greyPlastic'), C('tealLight'), C('mustard'), C('greyPlastic')];
  buttons.forEach((color, i) => gloss.box(0.012, 0.006, 0.01, { x: (i % 2) * 0.02 - 0.01, y: 0.024, z: -0.06 + Math.floor(i / 2) * 0.03, color }));
  gloss.at();

  // A rented tape and two magazines on the shelf underneath.
  gloss.box(0.21, 0.035, 0.12, { x: cx - 0.25, y: 0.13, z: cz, ry: 0.1, color: C('black') });
  art.plane(0.1, 0.05, { x: cx - 0.25, y: 0.1485, z: cz, rx: -Math.PI / 2, rz: 0.1, uv: kit.atlas.uv.rewind });
  gloss.box(0.24, 0.008, 0.3, { x: cx + 0.2, y: 0.117, z: cz, ry: -0.2, color: C('mauve') });
  gloss.box(0.24, 0.008, 0.3, { x: cx + 0.23, y: 0.125, z: cz + 0.02, ry: 0.15, color: C('mustardLight') });
}

// -- the bookcase and the fish tank on it ---------------------------------

function bookcase(THREE, group, kit) {
  const { wood, gloss, art, matte } = kit;
  const x = -1.55;
  const z = -2.27;
  const w = 0.86;
  const h = 1.25;
  const d = 0.32;
  wood.at(x, 0, z);
  const oak = C('oak');
  for (const side of [-1, 1]) wood.box(0.03, h, d, { x: (side * (w - 0.03)) / 2, y: h / 2, color: oak });
  for (const y of [0.04, 0.43, 0.83, h - 0.015]) wood.box(w, 0.03, d, { y, color: oak });
  wood.box(w, h, 0.012, { y: h / 2, z: -d / 2 + 0.006, color: C('walnut') });
  wood.at();

  // Bottom shelf: game boxes. Middle: tapes on end. Top: books.
  const spines = (y, height, name, depth) => {
    art.plane(w - 0.08, height, { x, y: y + height / 2, z: z + d / 2 - 0.02, uv: kit.atlas.uv[name] });
    matte.box(w - 0.08, height, depth, { x, y: y + height / 2, z: z + d / 2 - 0.021 - depth / 2, color: C('charcoal') });
  };
  spines(0.055, 0.2, 'games', 0.2);
  spines(0.845, 0.25, 'books', 0.22);
  for (let i = 0; i < 12; i += 1) {
    const tx = x - 0.36 + i * 0.03 + (i > 7 ? 0.1 : 0);
    const tilt = i === 11 ? -0.35 : 0;
    gloss.box(0.026, 0.19, 0.105, { x: tx + (tilt ? 0.03 : 0), y: 0.445 + 0.095, z: z + 0.07, rz: tilt, color: C('black') });
    art.plane(0.19, 0.022, { x: tx + (tilt ? 0.03 : 0), y: 0.445 + 0.095, z: z + 0.1235, rz: Math.PI / 2 + tilt, uv: kit.atlas.uv[`vhs${i}`] });
  }
  // A snow globe on the tape shelf.
  gloss.sphere(0.05, { x: x + 0.3, y: 0.52, z: z + 0.05, color: 0xbfd8e8 });
  gloss.cyl(0.045, 0.05, 0.03, 12, { x: x + 0.3, y: 0.46, z: z + 0.05, color: C('walnut') });

  // The fish tank on top: glass, water, gravel, weeds, a hood.
  const ty = h;
  matte.box(0.53, 0.03, 0.23, { x, y: ty + 0.015, z, color: 0xb59a7a });
  for (let i = 0; i < 4; i += 1) {
    matte.add(new THREE.ConeGeometry(0.015, 0.14 + (i % 2) * 0.06, 5), {
      x: x - 0.18 + i * 0.11,
      y: ty + 0.1 + (i % 2) * 0.03,
      z: z - 0.05 + (i % 2) * 0.06,
      color: C('leafLight'),
    });
  }
  gloss.box(0.58, 0.035, 0.28, { x, y: ty + 0.318, z, color: C('black') });

  const water = new THREE.Mesh(
    new THREE.BoxGeometry(0.53, 0.25, 0.23),
    new THREE.MeshStandardMaterial({
      color: hex(RETRO.water),
      emissive: hex(RETRO.water),
      emissiveIntensity: 0.55,
      transparent: true,
      opacity: 0.45,
      roughness: 0.1,
      depthWrite: false,
    }),
  );
  water.position.set(x, ty + 0.155, z);
  water.renderOrder = 1;
  group.add(water);
  const glass = new THREE.Mesh(
    new THREE.BoxGeometry(0.56, 0.3, 0.26),
    new THREE.MeshStandardMaterial({ color: 0xcfe8f0, transparent: true, opacity: 0.14, roughness: 0.05, metalness: 0.1, depthWrite: false }),
  );
  glass.position.set(x, ty + 0.15, z);
  glass.renderOrder = 2;
  group.add(glass);

  // Three goldfish, one instanced mesh.
  const fishShape = new Batch(THREE);
  fishShape.sphere(1, { sx: 0.03, sy: 0.018, sz: 0.009 }, 8, 6);
  fishShape.add(new THREE.ConeGeometry(0.016, 0.026, 4), { x: -0.036, rz: -Math.PI / 2, sz: 0.4 });
  const fish = new THREE.InstancedMesh(
    fishShape.geometry(),
    new THREE.MeshStandardMaterial({ color: hex(RETRO.goldfish), emissive: hex(RETRO.goldfish), emissiveIntensity: 0.35, roughness: 0.5 }),
    3,
  );
  fish.frustumCulled = false;
  group.add(fish);
  return { fish, x, y: ty + 0.15, z };
}

// -- plants, posters, pennant, calendar, clock -----------------------------

function snakePlant(kit, x, z) {
  const { matte, gloss } = kit;
  gloss.cyl(0.16, 0.12, 0.32, 16, { x, y: 0.16, z, color: C('terracotta') });
  gloss.cyl(0.178, 0.178, 0.05, 16, { x, y: 0.315, z, color: C('terracotta') });
  matte.cyl(0.155, 0.155, 0.01, 12, { x, y: 0.335, z, color: 0x2a1a10 });
  const leaves = [0.62, 0.8, 0.55, 0.9, 0.7, 0.5, 0.78, 0.66, 0.58, 0.84, 0.46];
  leaves.forEach((height, i) => {
    const a = i * 2.39;
    const r = 0.02 + (i % 4) * 0.025;
    matte.sphere(1, {
      x: x + Math.cos(a) * r,
      y: 0.33 + height * 0.48,
      z: z + Math.sin(a) * r,
      sx: 0.045,
      sy: height / 2,
      sz: 0.012,
      rx: Math.sin(a) * 0.14,
      rz: -Math.cos(a) * 0.14,
      ry: a,
      order: 'YXZ',
      color: i % 3 ? C('leaf') : C('leafLight'),
    }, 8, 8);
  });
}

function wallArt(THREE, kit) {
  const { art, gloss, wood } = kit;
  const uv = kit.atlas.uv;
  const tack = (x, y, z, color) => gloss.sphere(0.009, { x, y, z, color }, 6, 4);

  // Back wall, left of the TV: the festival flyer, tacked up.
  art.plane(0.48, 0.67, { x: -2.52, y: 1.62, z: BACK + 0.012, rz: 0.02, uv: uv.posterFest });
  for (const [dx, dy] of [
    [-0.22, 0.31],
    [0.22, 0.31],
    [-0.22, -0.31],
    [0.22, -0.31],
  ]) {
    tack(-2.52 + dx, 1.62 + dy, BACK + 0.016, C('rust'));
  }

  // The pennant, drooping a little.
  const pennant = new THREE.ShapeGeometry(new THREE.Shape([new THREE.Vector2(0, 0), new THREE.Vector2(1, 0.5), new THREE.Vector2(0, 1)]));
  art.add(pennant, { x: -1.3, y: 1.8, z: BACK + 0.014, sx: 0.58, sy: 0.22, rz: -0.1, uv: uv.pennant });
  tack(-1.29, 1.9, BACK + 0.018, C('mustard'));

  // Right of the TV: the clock (hands are separate, they move) and the calendar.
  art.add(new THREE.CircleGeometry(0.14, 28), { x: 0.98, y: 1.78, z: BACK + 0.023, uv: uv.clock });
  gloss.add(new THREE.TorusGeometry(0.145, 0.016, 8, 32), { x: 0.98, y: 1.78, z: BACK + 0.02, color: C('teal') });
  gloss.cyl(0.15, 0.15, 0.02, 28, { x: 0.98, y: 1.78, z: BACK + 0.01, rx: Math.PI / 2, color: C('tealDeep') });
  art.plane(0.3, 0.45, { x: 1.42, y: 1.25, z: BACK + 0.008, uv: uv.calendar });
  tack(1.42, 1.465, BACK + 0.012, C('black'));

  // Right wall: the motivational poster.
  art.at(SIDE, 0, -0.95, -Math.PI / 2);
  art.plane(0.5, 0.7, { y: 1.55, z: 0.012, uv: uv.posterHang });
  art.at();
  gloss.at(SIDE, 0, -0.95, -Math.PI / 2);
  for (const [dx, dy] of [
    [-0.23, 0.33],
    [0.23, 0.33],
  ]) {
    tack(dx, 1.55 + dy, 0.016, C('teal'));
  }
  gloss.at();

  // Rear wall, behind the couch (its frame is turned, so +x here is -x in
  // the room): the old landscape print, framed, and the fly swatter.
  wood.at(0, 0, REAR, Math.PI);
  wood.box(0.66, 0.54, 0.035, { x: -0.55, y: 1.62, z: 0.018, color: C('walnutLight') });
  wood.at();
  art.at(0, 0, REAR, Math.PI);
  art.plane(0.56, 0.44, { x: -0.55, y: 1.62, z: 0.037, uv: uv.landscape });
  art.at();
}

/** A fly swatter hung on the rear wall, over a sign that says what it is for.
 *  Behind the fly, where it cannot see it. */
function swatter(kit) {
  const { art, gloss, metal } = kit;
  // In the rear wall's frame; +x here is -x in the room.
  const x = 1.2;
  gloss.at(0, 0, REAR, Math.PI);
  metal.at(0, 0, REAR, Math.PI);
  art.at(0, 0, REAR, Math.PI);
  metal.cyl(0.006, 0.006, 0.03, 6, { x, y: 1.9, z: 0.015, rx: Math.PI / 2, color: C('chrome') });
  gloss.add(new kit.THREE.TorusGeometry(0.018, 0.004, 6, 12), { x, y: 1.875, z: 0.012, color: C('mustard') });
  gloss.rod([x, 1.862, 0.014], [x + 0.008, 1.47, 0.014], 0.013, 8, { color: C('mustard'), radiusFrom: 0.011 });
  gloss.box(0.21, 0.2, 0.008, { x: x + 0.01, y: 1.37, z: 0.012, rz: -0.025, color: 0xd22a24 });
  art.plane(0.2, 0.19, { x: x + 0.01, y: 1.37, z: 0.0165, rz: -0.025, uv: kit.atlas.uv.swatter });
  gloss.box(0.27, 0.09, 0.012, { x, y: 1.14, z: 0.006, color: C('black') });
  art.plane(0.25, 0.078, { x, y: 1.14, z: 0.0125, uv: kit.atlas.uv.plaque });
  gloss.at();
  metal.at();
  art.at();
}

function wallClock(THREE, group) {
  const pivot = new THREE.Group();
  pivot.position.set(0.98, 1.78, BACK + 0.028);
  group.add(pivot);
  const hand = (length, width, color) => {
    const geometry = new THREE.BoxGeometry(width, length, 0.004);
    geometry.translate(0, length / 2 - 0.015, 0);
    const mesh = new THREE.Mesh(geometry, new THREE.MeshStandardMaterial({ color, roughness: 0.5 }));
    pivot.add(mesh);
    return mesh;
  };
  const hours = hand(0.08, 0.014, 0x2a2020);
  const minutes = hand(0.115, 0.009, 0x2a2020);
  const seconds = hand(0.12, 0.004, 0xc0231e);
  seconds.position.z = 0.004;
  return { hours, minutes, seconds, offset: new Date().getTimezoneOffset() * 60000 };
}

// -- the window --------------------------------------------------------------

function nightWindow(THREE, group, kit) {
  const { matte } = kit;
  const z = -0.75;
  const cy = 1.58;
  const cream = C('cream');
  matte.at(-SIDE, 0, z, Math.PI / 2);
  matte.box(1.14, 0.07, 0.06, { y: cy + 0.56, z: 0.03, color: cream });
  matte.box(1.24, 0.05, 0.16, { y: cy - 0.56, z: 0.07, color: cream });
  matte.box(1.2, 0.06, 0.04, { y: cy - 0.62, z: 0.02, color: cream });
  for (const side of [-1, 1]) matte.box(0.07, 1.14, 0.06, { x: side * 0.535, y: cy, z: 0.03, color: cream });
  matte.box(0.03, 1.06, 0.03, { y: cy, z: 0.015, color: cream });
  matte.box(1.0, 0.03, 0.03, { y: cy + 0.1, z: 0.015, color: cream });
  // Blinds, lowered two thirds of the way and tilted open.
  const beige = C('beige');
  for (let y = cy - 0.5; y < cy + 0.2; y += 0.045) {
    matte.box(1.0, 0.004, 0.045, { y, z: 0.09, rx: 0.55, color: beige });
  }
  matte.box(1.0, 0.1, 0.05, { y: cy + 0.4, z: 0.09, color: beige });
  matte.box(1.04, 0.04, 0.055, { y: cy + 0.49, z: 0.09, color: 0xe6dcc6 });
  for (const lx of [-0.3, 0.3]) matte.box(0.004, 0.95, 0.004, { x: lx, y: cy - 0.03, z: 0.115, color: 0xe6dcc6 });
  matte.box(0.004, 0.6, 0.004, { x: 0.45, y: cy + 0.17, z: 0.12, color: 0xe6dcc6 });
  matte.cyl(0.008, 0.012, 0.04, 6, { x: 0.45, y: cy - 0.15, z: 0.12, color: 0xe6dcc6 });
  // A cactus on the sill.
  matte.cyl(0.04, 0.03, 0.07, 10, { x: -0.3, y: cy - 0.5, z: 0.08, color: C('terracotta') });
  matte.sphere(0.035, { x: -0.3, y: cy - 0.43, z: 0.08, sy: 1.8, color: C('leaf') }, 8, 6);
  matte.at();

  const sky = new THREE.Mesh(
    new THREE.PlaneGeometry(1.0, 1.06),
    new THREE.MeshBasicMaterial({ map: skyTexture(THREE), color: 0xb4bcd8 }),
  );
  sky.position.set(-SIDE + 0.006, cy, z);
  sky.rotation.y = Math.PI / 2;
  group.add(sky);

  // Moonlight through the slats, lying on the floor under the window.
  const stripes = new THREE.PlaneGeometry(1.4, 1.1);
  stripes.rotateZ(Math.PI / 2);
  stripes.rotateX(-Math.PI / 2);
  const light = new THREE.Mesh(
    stripes,
    new THREE.MeshBasicMaterial({
      map: blindLightTexture(THREE),
      color: 0x8fa6ff,
      transparent: true,
      opacity: 0.22,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    }),
  );
  light.position.set(-SIDE + 0.6, 0.009, z);
  group.add(light);
}

// -- the end table: lava lamp and phone -------------------------------------

function endTable(THREE, group, kit) {
  const { wood, gloss, metal, art } = kit;
  const x = -1.42;
  const z = 1.48;
  const top = 0.55;
  wood.at(x, 0, z);
  wood.box(0.46, 0.04, 0.46, { y: 0.53, color: C('oak') });
  wood.box(0.4, 0.02, 0.4, { y: 0.14, color: C('veneer') });
  for (const sx of [-1, 1]) for (const sz of [-1, 1]) wood.box(0.04, 0.51, 0.04, { x: sx * 0.19, y: 0.255, z: sz * 0.19, color: C('oak') });
  wood.at();
  // A stack of comics on the shelf.
  gloss.box(0.2, 0.012, 0.28, { x, y: 0.156, z, ry: 0.2, color: C('rust') });
  gloss.box(0.2, 0.012, 0.28, { x, y: 0.168, z, ry: -0.1, color: C('tealLight') });

  // Lava lamp: a metal cone base, a glowing glass bottle, a cap.
  const lx = x - 0.08;
  const lz = z - 0.1;
  metal.cyl(0.045, 0.08, 0.16, 18, { x: lx, y: top + 0.08, z: lz, color: C('brass') });
  metal.cyl(0.018, 0.034, 0.07, 18, { x: lx, y: top + 0.485, z: lz, color: C('brass') });
  const profile = [
    [0.044, 0],
    [0.056, 0.06],
    [0.06, 0.12],
    [0.05, 0.2],
    [0.034, 0.27],
    [0.02, 0.29],
  ].map(([r, y]) => new THREE.Vector2(r, y));
  const glass = new THREE.Mesh(
    new THREE.LatheGeometry(profile, 20),
    new THREE.MeshStandardMaterial({
      color: hex(RETRO.lavaGlass),
      emissive: hex(RETRO.lavaGlass),
      emissiveIntensity: 0.55,
      transparent: true,
      opacity: 0.62,
      roughness: 0.15,
      depthWrite: false,
    }),
  );
  glass.position.set(lx, top + 0.16, lz);
  glass.renderOrder = 1;
  group.add(glass);
  const blobs = new THREE.InstancedMesh(
    new THREE.SphereGeometry(1, 10, 8),
    new THREE.MeshBasicMaterial({ color: hex(RETRO.lavaWax) }),
    5,
  );
  blobs.frustumCulled = false;
  group.add(blobs);
  const glow = new THREE.PointLight(0xff5a8a, 1.3, 2.4, 2);
  glow.position.set(lx, top + 0.3, lz);
  group.add(glow);

  // A see-through teal phone, the handset on its cradle, its coiled cord.
  const px = x + 0.08;
  const pz = z + 0.09;
  const phoneTurn = 0.9;
  gloss.at(px, top, pz, phoneTurn);
  const teal = C('tealLight');
  gloss.box(0.17, 0.05, 0.2, { y: 0.025, color: teal });
  gloss.box(0.17, 0.03, 0.13, { y: 0.06, z: -0.035, rx: 0.18, color: teal });
  gloss.box(0.2, 0.034, 0.05, { y: 0.1, z: -0.045, color: teal });
  for (const side of [-1, 1]) gloss.box(0.055, 0.04, 0.066, { x: side * 0.085, y: 0.088, z: -0.045, color: teal });
  gloss.at();
  art.at(px, top, pz, phoneTurn);
  art.plane(0.09, 0.08, { y: 0.0505, z: 0.055, rx: -Math.PI / 2 + 0.05, uv: kit.atlas.uv.keypad });
  art.at();
  const coil = [];
  const path = new THREE.CatmullRomCurve3(
    [
      [-0.11, 0.08, -0.05],
      [-0.2, 0.03, -0.03],
      [-0.24, 0.012, 0.06],
      [-0.17, 0.012, 0.12],
      [-0.086, 0.025, 0.06],
    ].map((p) => new THREE.Vector3(...p)),
  );
  const turns = 26;
  const samples = 260;
  const up = new THREE.Vector3(0, 1, 0);
  const side = new THREE.Vector3();
  const lift = new THREE.Vector3();
  for (let i = 0; i <= samples; i += 1) {
    const t = i / samples;
    const point = path.getPointAt(t);
    const tangent = path.getTangentAt(t);
    side.crossVectors(tangent, up).normalize();
    lift.crossVectors(side, tangent).normalize();
    const a = t * turns * Math.PI * 2;
    point.addScaledVector(side, Math.cos(a) * 0.011).addScaledVector(lift, Math.sin(a) * 0.011);
    coil.push([point.x, point.y, point.z]);
  }
  gloss.at(px, top, pz, phoneTurn);
  gloss.tube(coil, 0.0028, { color: teal, segments: samples * 2, radial: 4 });
  gloss.at();

  return { blobs, glass: glass.position.clone() };
}

// -- the corner by the TV: boombox, cassettes, beanbag ------------------------

function boombox(kit) {
  const { gloss, metal, art } = kit;
  const x = 1.05;
  const z = -1.9;
  const turn = -0.35;
  gloss.at(x, 0, z, turn);
  gloss.box(0.52, 0.22, 0.14, { y: 0.115, color: C('charcoal') });
  gloss.box(0.52, 0.012, 0.13, { y: 0.004, color: C('black') });
  for (const side of [-1, 1]) {
    gloss.cyl(0.075, 0.075, 0.012, 18, { x: side * 0.17, y: 0.115, z: 0.07, rx: Math.PI / 2, color: C('black') });
    gloss.cyl(0.03, 0.045, 0.014, 14, { x: side * 0.17, y: 0.115, z: 0.074, rx: Math.PI / 2, color: 0x4a4c52 });
  }
  gloss.at();
  metal.at(x, 0, z, turn);
  for (const side of [-1, 1]) {
    metal.add(new kit.THREE.TorusGeometry(0.076, 0.006, 6, 24), { x: side * 0.17, y: 0.115, z: 0.075, color: C('chrome') });
    metal.rod([side * 0.2, 0.225, 0], [side * 0.17, 0.3, 0], 0.008, 6, { color: C('chrome') });
  }
  metal.rod([-0.17, 0.3, 0], [0.17, 0.3, 0], 0.01, 8, { color: C('chrome') });
  metal.rod([0.24, 0.225, -0.05], [0.4, 0.62, -0.1], 0.004, 5, { color: C('chrome') });
  metal.at();
  art.at(x, 0, z, turn);
  art.plane(0.17, 0.085, { y: 0.14, z: 0.0705, uv: kit.atlas.uv.boombox });
  art.at();

  // Two cassettes on the floor in front of it.
  for (const [cx, cz, turnC] of [
    [1.28, -1.62, 0.4],
    [1.12, -1.55, -0.3],
  ]) {
    gloss.box(0.1, 0.013, 0.064, { x: cx, y: 0.0065, z: cz, ry: turnC, color: C('black') });
    art.plane(0.09, 0.056, { x: cx, y: 0.0135, z: cz, rx: -Math.PI / 2, rz: turnC, uv: kit.atlas.uv.cassette });
  }
}

function beanbag(kit) {
  const { gloss } = kit;
  gloss.sphere(1, { x: 2.45, y: 0.26, z: -1.2, sx: 0.5, sy: 0.3, sz: 0.46, color: C('mauveDeep') }, 20, 14);
  gloss.sphere(1, { x: 2.5, y: 0.47, z: -1.15, sx: 0.32, sy: 0.14, sz: 0.3, rz: 0.2, color: C('mauve') }, 16, 10);
}

// -- the couch dressing: a throw, a pillow, and something for the fly -------

function couchDressing(THREE, kit) {
  const { matte, gloss } = kit;
  // A knitted afghan over the right back cushion, in narrow muted stripes.
  const bands = ['rust', 'mustard', 'tealDeep', 'mauveDeep', 'olive', 'rust', 'mustard'];
  bands.forEach((name, i) => {
    const t0 = 0.03 + i * 0.05;
    const shell = new THREE.SphereGeometry(1, 18, 2, Math.PI + 0.75, Math.PI - 1.5, t0 * Math.PI, 0.05 * Math.PI);
    matte.add(shell, { x: 0.47, y: 0.78, z: 1.84, rx: -0.12, sx: 0.5, sy: 0.335, sz: 0.172, color: C(name) });
  });
  // A pillow wedged in the right corner.
  matte.sphere(1, { x: 0.74, y: 0.72, z: 1.7, sx: 0.19, sy: 0.17, sz: 0.07, rx: -0.25, ry: -0.5, rz: 0.2, color: C('mauve') }, 16, 12);

  // On the left arm: a fly-sized mug of something, and two sugar cubes.
  const ax = -0.915;
  const ay = 0.915;
  gloss.cyl(0.04, 0.036, 0.075, 16, { x: ax, y: ay + 0.0375, z: 1.3, color: C('mustard') });
  gloss.add(new THREE.TorusGeometry(0.022, 0.007, 6, 12), { x: ax + 0.045, y: ay + 0.04, z: 1.3, color: C('mustard') });
  matte.cyl(0.035, 0.035, 0.004, 14, { x: ax, y: ay + 0.068, z: 1.3, color: 0x3a1f10 });
  matte.box(0.04, 0.04, 0.04, { x: ax + 0.005, y: ay + 0.02, z: 1.43, ry: 0.3, color: 0xf4f1ea });
  matte.box(0.04, 0.04, 0.04, { x: ax - 0.01, y: ay + 0.02, z: 1.48, ry: 0.9, rz: 0.1, color: 0xf4f1ea });
}

// -- string lights ----------------------------------------------------------

function glowSprite(THREE) {
  const canvas = document.createElement('canvas');
  canvas.width = 64;
  canvas.height = 64;
  const ctx = canvas.getContext('2d');
  const gradient = ctx.createRadialGradient(32, 32, 1, 32, 32, 32);
  gradient.addColorStop(0, 'rgba(255,255,255,0.9)');
  gradient.addColorStop(0.3, 'rgba(255,255,255,0.25)');
  gradient.addColorStop(1, 'rgba(255,255,255,0)');
  ctx.fillStyle = gradient;
  ctx.fillRect(0, 0, 64, 64);
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  return texture;
}

function stringLights(THREE, group, kit) {
  const runs = [
    { z: BACK + 0.03, face: 0, y: 2.26, from: -3.3, to: 3.3 },
    { z: REAR - 0.03, face: Math.PI, y: 2.2, from: -3.3, to: 3.3 },
    { x: -SIDE + 0.03, face: Math.PI / 2, y: 2.42, from: -2.35, to: 2.5 },
  ];
  const palette = [0xff4a3a, 0xffb238, 0x4ad86a, 0x4a8cff, 0xffe2b0].map((c) => new THREE.Color(c));
  const bulbs = [];
  for (const run of runs) {
    const points = [];
    const span = 1.1;
    const count = Math.round((run.to - run.from) / span);
    for (let s = 0; s < count; s += 1) {
      for (let k = 0; k < 8; k += 1) {
        const f = k / 8;
        const along = run.from + (s + f) * ((run.to - run.from) / count);
        const sag = 0.13 * 4 * f * (1 - f);
        points.push(run.x !== undefined ? [run.x, run.y - sag, along] : [along, run.y - sag, run.z]);
      }
    }
    points.push(run.x !== undefined ? [run.x, run.y, run.to] : [run.to, run.y, run.z]);
    kit.matte.tube(points, 0.004, { color: 0x1f3a22, radial: 3, segments: points.length * 3 });
    const curve = new THREE.CatmullRomCurve3(points.map((p) => new THREE.Vector3(...p)));
    const length = curve.getLength();
    const n = Math.floor(length / 0.2);
    for (let i = 1; i < n; i += 1) {
      const p = curve.getPointAt(i / n);
      p.y -= 0.022;
      bulbs.push({ p, face: run.face, color: palette[bulbs.length % palette.length], phase: bulbs.length * 1.7, speed: 0.6 + (bulbs.length % 5) * 0.23 });
      kit.matte.cyl(0.007, 0.007, 0.018, 6, { x: p.x, y: p.y + 0.014, z: p.z, color: 0x1f3a22 });
    }
  }

  const bulbMesh = new THREE.InstancedMesh(
    new THREE.SphereGeometry(0.016, 8, 6).scale(1, 1.5, 1),
    new THREE.MeshBasicMaterial({ toneMapped: false }),
    bulbs.length,
  );
  const halo = new THREE.InstancedMesh(
    new THREE.PlaneGeometry(0.26, 0.26),
    new THREE.MeshBasicMaterial({
      map: glowSprite(THREE),
      transparent: true,
      opacity: 0.55,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
      toneMapped: false,
    }),
    bulbs.length,
  );
  const matrix = new THREE.Matrix4();
  const q = new THREE.Quaternion();
  const e = new THREE.Euler();
  const one = new THREE.Vector3(1, 1, 1);
  const out = new THREE.Vector3();
  bulbs.forEach((bulb, i) => {
    matrix.makeTranslation(bulb.p.x, bulb.p.y, bulb.p.z);
    bulbMesh.setMatrixAt(i, matrix);
    // The glow lies flat on the wall behind the bulb.
    q.setFromEuler(e.set(0, bulb.face, 0));
    out.set(0, 0, -0.018).applyQuaternion(q).add(bulb.p);
    matrix.compose(out, q, one);
    halo.setMatrixAt(i, matrix);
    bulbMesh.setColorAt(i, bulb.color);
    halo.setColorAt(i, bulb.color);
  });
  halo.renderOrder = 2;
  group.add(bulbMesh);
  group.add(halo);
  return { bulbs, bulbMesh, halo };
}

// -- all of it ---------------------------------------------------------------

/**
 * Adds the props to `group` and to the batches in `kit`. Returns
 * `{ update(dt, elapsed) }` for the things that move. `update` allocates
 * nothing.
 */
export function buildProps(THREE, group, kit) {
  kit.THREE = THREE;
  tvCabinet(kit);
  const vcrLed = ledDisplays(THREE, group);
  gameConsole(kit);
  coffeeTable(THREE, kit);
  const tank = bookcase(THREE, group, kit);
  snakePlant(kit, -2.98, -2.08);
  snakePlant(kit, 2.95, -2.1);
  wallArt(THREE, kit);
  swatter(kit);
  const clock = wallClock(THREE, group);
  nightWindow(THREE, group, kit);
  const lava = endTable(THREE, group, kit);
  boombox(kit);
  beanbag(kit);
  couchDressing(THREE, kit);
  const lights = stringLights(THREE, group, kit);

  const matrix = new THREE.Matrix4();
  const position = new THREE.Vector3();
  const scale = new THREE.Vector3();
  const turn = new THREE.Quaternion();
  const still = new THREE.Quaternion();
  const up = new THREE.Vector3(0, 1, 0);
  const color = new THREE.Color();

  function update(dt, t) {
    // Lava: each blob rises and sinks on its own slow cycle, stretching
    // as it climbs.
    for (let i = 0; i < 5; i += 1) {
      const cycle = 0.5 + 0.5 * Math.sin(t * (0.18 + i * 0.045) + i * 1.9);
      const r = 0.018 + (i % 3) * 0.006;
      position.set(lava.glass.x + Math.sin(t * 0.3 + i) * 0.012, lava.glass.y + 0.035 + cycle * 0.2, lava.glass.z + Math.cos(t * 0.25 + i * 2) * 0.012);
      scale.set(r, r * (1 + 0.5 * Math.abs(Math.cos(t * (0.18 + i * 0.045) + i * 1.9))), r);
      matrix.compose(position, still, scale);
      lava.blobs.setMatrixAt(i, matrix);
    }
    lava.blobs.instanceMatrix.needsUpdate = true;

    // Goldfish: back and forth the length of the tank, turning at the ends.
    for (let i = 0; i < 3; i += 1) {
      const phase = t * (0.35 + i * 0.09) + i * 2.1;
      const along = Math.sin(phase);
      const heading = Math.cos(phase) >= 0 ? 0 : Math.PI;
      position.set(tank.x + along * 0.2, tank.y - 0.05 + i * 0.05 + Math.sin(t * 1.3 + i) * 0.01, tank.z - 0.06 + i * 0.06);
      turn.setFromAxisAngle(up, heading + Math.sin(t * 9 + i) * 0.12);
      scale.set(1, 1, 1);
      matrix.compose(position, turn, scale);
      tank.fish.setMatrixAt(i, matrix);
    }
    tank.fish.instanceMatrix.needsUpdate = true;

    // String lights: a slow, uneven breathing, so they look alive but never
    // compete with the TV.
    for (let i = 0; i < lights.bulbs.length; i += 1) {
      const bulb = lights.bulbs[i];
      const k = 0.55 + 0.45 * Math.max(0, Math.sin(t * bulb.speed + bulb.phase));
      color.copy(bulb.color).multiplyScalar(0.35 + 0.75 * k);
      lights.bulbMesh.setColorAt(i, color);
      color.copy(bulb.color).multiplyScalar(0.2 + 0.5 * k);
      lights.halo.setColorAt(i, color);
    }
    lights.bulbMesh.instanceColor.needsUpdate = true;
    lights.halo.instanceColor.needsUpdate = true;

    // The clock tells the real local time.
    const now = (Date.now() - clock.offset) / 1000;
    const secs = now % 60;
    const mins = (now / 60) % 60;
    const hrs = (now / 3600) % 12;
    clock.seconds.rotation.z = -Math.floor(secs) * (Math.PI / 30);
    clock.minutes.rotation.z = -mins * (Math.PI / 30);
    clock.hours.rotation.z = -hrs * (Math.PI / 6);

    // 12:00, forever.
    vcrLed.visible = t % 1.2 < 0.7;
  }

  return { update };
}
