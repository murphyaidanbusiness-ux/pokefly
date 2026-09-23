/**
 * The living room: floor, walls, ceiling, couch, lamp, base lighting, and the
 * 1990s clutter from props.js.
 *
 * Everything is a three.js primitive; the only textures are canvases drawn in
 * code (textures.js). Static shapes are merged by material into a handful of
 * meshes (batch.js), so a room full of tapes and cans costs a few draw calls.
 * The room is deliberately dim, because the TV is the key light and it cannot
 * look like one if the room is already bright.
 *
 * Layout, in metres: the TV stands against the back wall (z = -2.45), the
 * couch faces it with its back toward the rear wall (z = 2.6), the side walls
 * are at x = +-3.4 and the ceiling at y = 3.0.
 *
 * The couch seat top is at y = 0.54 and that is where the fly sits, so if you
 * move the couch, move the fly.
 */

import { Batch } from './batch.js';
import { buildProps } from './props.js';
import {
  buildAtlas,
  ceilingTexture,
  floorTexture,
  panellingTexture,
  plaidTexture,
  rugTexture,
  wallpaperTexture,
  woodTexture,
} from './textures.js';
import { RETRO, ROOM, hex } from './theme.js';

export const SEAT_HEIGHT = 0.54;

const BACK_Z = -2.45;
const REAR_Z = 2.6;
const SIDE_X = 3.4;
const CEILING = 3.0;
const PANEL_TOP = 0.95;

/** The four walls: wallpaper above a chair rail, panelling below it, trim at
 *  the floor and the rail. Two draw calls for the surfaces, trim goes in the
 *  wood batch. */
function buildWalls(THREE, group, wood) {
  const paper = new Batch(THREE);
  const panel = new Batch(THREE);
  const width = SIDE_X * 2;
  const depth = REAR_Z - BACK_Z;
  const midZ = (REAR_Z + BACK_Z) / 2;
  const upper = CEILING - PANEL_TOP;
  const walls = [
    // [length, x, z, turn so the face points into the room]
    [width, 0, BACK_Z, 0],
    [width, 0, REAR_Z, Math.PI],
    [depth, -SIDE_X, midZ, Math.PI / 2],
    [depth, SIDE_X, midZ, -Math.PI / 2],
  ];
  for (const [length, x, z, turn] of walls) {
    paper.at(x, 0, z, turn);
    paper.plane(length, upper, { y: PANEL_TOP + upper / 2, uvScale: [length / 0.6, upper / 0.6] });
    panel.at(x, 0, z, turn);
    panel.plane(length, PANEL_TOP, { y: PANEL_TOP / 2, uvScale: [length / 1.2, 1] });
    wood.at(x, 0, z, turn);
    const walnut = hex(RETRO.walnut);
    wood.box(length, 0.11, 0.025, { y: 0.055, z: 0.012, color: walnut });
    wood.box(length, 0.045, 0.035, { y: PANEL_TOP, z: 0.017, color: hex(RETRO.walnutLight) });
    wood.box(length, 0.07, 0.03, { y: CEILING - 0.035, z: 0.015, color: hex(RETRO.cream) });
  }
  wood.at();

  const paperMaterial = new THREE.MeshStandardMaterial({
    map: wallpaperTexture(THREE),
    color: ROOM.wall,
    roughness: 0.95,
  });
  const panelMaterial = new THREE.MeshStandardMaterial({
    map: panellingTexture(THREE),
    roughness: 0.6,
    metalness: 0.0,
  });
  group.add(paper.mesh(paperMaterial, { cast: false }));
  group.add(panel.mesh(panelMaterial, { cast: false }));

  const ceiling = new THREE.Mesh(
    new THREE.PlaneGeometry(width, depth),
    new THREE.MeshStandardMaterial({ map: ceilingTexture(THREE), roughness: 1.0 }),
  );
  ceiling.material.map.repeat.set(width / 1.2, depth / 1.2);
  ceiling.rotation.x = Math.PI / 2;
  ceiling.position.set(0, CEILING, midZ);
  group.add(ceiling);
}

/** The couch, all one mesh in the plaid, with its feet in the wood batch.
 *  Seat cushion tops sit at SEAT_HEIGHT. */
function buildCouch(THREE, fabric, wood) {
  const dark = ROOM.couchDark;
  const round = (width, height, depth, o) => fabric.sphere(1, { ...o, sx: width / 2, sy: height / 2, sz: depth / 2 }, 22, 16);

  fabric.box(2.05, 0.34, 0.95, { x: 0, y: 0.28, z: 1.55, color: dark });
  for (const side of [-1, 1]) {
    fabric.box(0.22, 0.42, 0.95, { x: side * 0.915, y: 0.62, z: 1.55 });
    round(0.22, 0.2, 0.95, { x: side * 0.915, y: 0.82, z: 1.55 });
    for (const z of [1.2, 1.9]) {
      wood.cyl(0.04, 0.03, 0.11, 10, { x: side * 0.85, y: 0.055, z, color: hex(RETRO.walnut) });
    }
  }
  for (const side of [-1, 1]) {
    round(0.95, 0.24, 0.86, { x: side * 0.49, y: SEAT_HEIGHT - 0.12, z: 1.53 });
  }
  fabric.box(2.05, 0.62, 0.16, { x: 0, y: 0.73, z: 1.96, color: dark });
  for (const side of [-1, 1]) {
    round(0.95, 0.62, 0.3, { x: side * 0.49, y: 0.78, z: 1.84, rx: -0.12 });
  }
  // Piping along the front of the base: a thin darker roll.
  fabric.cyl(0.018, 0.018, 1.62, 8, { x: 0, y: 0.44, z: 1.075, rz: Math.PI / 2, color: dark });
}

function buildTable(wood, x, z) {
  const oak = hex(RETRO.oak);
  wood.at(x, 0, z);
  wood.box(0.6, 0.05, 0.5, { y: 0.52, color: oak });
  wood.box(0.52, 0.025, 0.42, { y: 0.16, color: hex(RETRO.veneer) });
  for (const sx of [-1, 1]) {
    for (const sz of [-1, 1]) {
      wood.box(0.045, 0.5, 0.045, { x: sx * 0.25, y: 0.25, z: sz * 0.2, color: oak });
    }
  }
  wood.at();
}

function buildLamp(THREE, metal, x, z) {
  metal.at(x, 0, z);
  const brass = hex(RETRO.brass);
  metal.cyl(0.17, 0.2, 0.04, 20, { y: 0.02, color: brass });
  metal.cyl(0.018, 0.018, 1.2, 12, { y: 0.62, color: brass });
  metal.sphere(0.03, { y: 1.18, color: brass });
  metal.at();

  const group = new THREE.Group();
  const shadeMaterial = new THREE.MeshStandardMaterial({
    color: 0xffe0b2,
    emissive: 0xffb066,
    emissiveIntensity: 0.9,
    roughness: 0.9,
    side: THREE.DoubleSide,
  });
  const shade = new THREE.Mesh(new THREE.CylinderGeometry(0.17, 0.26, 0.28, 24, 1, true), shadeMaterial);
  shade.position.y = 1.3;
  group.add(shade);

  const bulb = new THREE.PointLight(0xffb066, 9, 7, 2);
  bulb.position.set(0, 1.26, 0);
  group.add(bulb);
  group.userData.bulb = bulb;
  group.position.set(x, 0, z);
  return group;
}

/**
 * Builds the room into `scene` and returns the handles the rest of the scene
 * needs: the lamp, the base lights, and `update(dt, elapsed)` for the few
 * props that move (lava lamp, string lights, the clock, the VCR's 12:00).
 */
export function buildRoom(THREE, scene) {
  const group = new THREE.Group();
  const atlas = buildAtlas(THREE);

  // One batch per material. Props add to these; each becomes one mesh.
  const kit = {
    atlas,
    wood: new Batch(THREE),
    fabric: new Batch(THREE),
    matte: new Batch(THREE),
    gloss: new Batch(THREE),
    metal: new Batch(THREE),
    art: new Batch(THREE),
    glow: new Batch(THREE),
  };

  const floor = new THREE.Mesh(
    new THREE.PlaneGeometry(SIDE_X * 2, REAR_Z - BACK_Z),
    new THREE.MeshStandardMaterial({ map: floorTexture(THREE), color: ROOM.floor, roughness: 0.55 }),
  );
  floor.material.map.repeat.set(2.2, 1.7);
  floor.rotation.x = -Math.PI / 2;
  floor.position.z = (REAR_Z + BACK_Z) / 2;
  floor.receiveShadow = true;
  group.add(floor);

  const rugMap = rugTexture(THREE);
  const rug = new THREE.Mesh(
    new THREE.PlaneGeometry(3.5, 2.6),
    new THREE.MeshStandardMaterial({ map: rugMap, bumpMap: rugMap, bumpScale: 2.5, color: ROOM.rug, roughness: 1.0 }),
  );
  rug.rotation.x = -Math.PI / 2;
  rug.position.set(0, 0.006, 0.35);
  rug.receiveShadow = true;
  group.add(rug);

  buildWalls(THREE, group, kit.wood);
  buildCouch(THREE, kit.fabric, kit.wood);
  buildTable(kit.wood, 1.55, 0.75);
  const lamp = buildLamp(THREE, kit.metal, -2.0, 0.5);
  group.add(lamp);

  const props = buildProps(THREE, group, kit);

  const woodMaterial = new THREE.MeshStandardMaterial({ map: woodTexture(THREE), vertexColors: true, roughness: 0.55 });
  const fabricMaterial = new THREE.MeshStandardMaterial({ map: plaidTexture(THREE), color: ROOM.couch, vertexColors: true, roughness: 0.95 });
  const matteMaterial = new THREE.MeshStandardMaterial({ vertexColors: true, roughness: 0.85 });
  const glossMaterial = new THREE.MeshStandardMaterial({ vertexColors: true, roughness: 0.32, metalness: 0.05 });
  const metalMaterial = new THREE.MeshStandardMaterial({ vertexColors: true, roughness: 0.3, metalness: 0.85 });
  const artMaterial = new THREE.MeshStandardMaterial({ map: atlas.texture, vertexColors: true, roughness: 0.75 });
  const glowMaterial = new THREE.MeshBasicMaterial({ vertexColors: true, toneMapped: false });
  for (const [batch, material, cast] of [
    [kit.wood, woodMaterial, true],
    [kit.fabric, fabricMaterial, true],
    [kit.matte, matteMaterial, true],
    [kit.gloss, glossMaterial, true],
    [kit.metal, metalMaterial, true],
    [kit.art, artMaterial, false],
    [kit.glow, glowMaterial, false],
  ]) {
    const mesh = batch.mesh(material, { cast });
    if (mesh) group.add(mesh);
  }

  scene.add(group);

  // Base light. Low and cool, so the warm lamps and the TV all read as sources.
  const sky = new THREE.HemisphereLight(0x3d3656, 0x1a1210, 0.5);
  scene.add(sky);
  const fill = new THREE.DirectionalLight(0xffd9b0, 0.22);
  fill.position.set(2.4, 2.8, 2.6);
  scene.add(fill);

  return { group, lamp, lampBulb: lamp.userData.bulb, sky, fill, update: props.update };
}
