/**
 * The living room: floor, rug, walls, couch, side table, lamp, base lighting.
 *
 * Everything is a three.js primitive. The only textures are drawn into a
 * canvas here in code (floor planks, the rug, a soft wall gradient); nothing
 * is downloaded. The room is deliberately dim, because the TV is the key light
 * and it cannot look like one if the room is already bright.
 *
 * The couch seat top is at y = 0.54 and that is where the fly sits, so if you
 * move the couch, move the fly.
 */

import { ROOM } from './theme.js';

export const SEAT_HEIGHT = 0.54;

function canvas2d(width, height) {
  const canvas = document.createElement('canvas');
  canvas.width = width;
  canvas.height = height;
  return canvas;
}

function canvasTexture(THREE, canvas, repeatX = 1, repeatY = 1) {
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.wrapS = THREE.RepeatWrapping;
  texture.wrapT = THREE.RepeatWrapping;
  texture.repeat.set(repeatX, repeatY);
  texture.anisotropy = 4;
  return texture;
}

function floorTexture(THREE) {
  const canvas = canvas2d(512, 512);
  const ctx = canvas.getContext('2d');
  ctx.fillStyle = '#4a3323';
  ctx.fillRect(0, 0, 512, 512);
  for (let y = 0; y < 512; y += 64) {
    const shade = 28 + Math.floor(Math.random() * 22);
    ctx.fillStyle = `rgb(${58 + shade}, ${38 + Math.floor(shade * 0.6)}, ${24 + Math.floor(shade * 0.4)})`;
    ctx.fillRect(0, y, 512, 62);
    ctx.strokeStyle = 'rgba(0,0,0,0.45)';
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(0, y + 63);
    ctx.lineTo(512, y + 63);
    ctx.stroke();
    // A few grain streaks so the planks are not flat colour.
    for (let i = 0; i < 26; i += 1) {
      ctx.strokeStyle = `rgba(0,0,0,${0.03 + Math.random() * 0.06})`;
      ctx.lineWidth = 1;
      const gy = y + 4 + Math.random() * 54;
      ctx.beginPath();
      ctx.moveTo(Math.random() * 512, gy);
      ctx.lineTo(Math.random() * 512, gy + (Math.random() - 0.5) * 3);
      ctx.stroke();
    }
  }
  return canvasTexture(THREE, canvas, 3, 3);
}

function rugTexture(THREE) {
  const canvas = canvas2d(512, 384);
  const ctx = canvas.getContext('2d');
  ctx.fillStyle = '#7d3439';
  ctx.fillRect(0, 0, 512, 384);
  ctx.fillStyle = '#93414a';
  for (let i = 0; i < 512; i += 26) {
    ctx.globalAlpha = 0.25;
    ctx.fillRect(i, 0, 13, 384);
  }
  ctx.globalAlpha = 1;
  ctx.strokeStyle = '#d8b46a';
  ctx.lineWidth = 10;
  ctx.strokeRect(20, 20, 472, 344);
  ctx.lineWidth = 3;
  ctx.strokeRect(40, 40, 432, 304);
  ctx.fillStyle = 'rgba(216,180,106,0.35)';
  ctx.beginPath();
  ctx.ellipse(256, 192, 110, 78, 0, 0, Math.PI * 2);
  ctx.fill();
  return canvasTexture(THREE, canvas);
}

function wallTexture(THREE) {
  const canvas = canvas2d(16, 256);
  const ctx = canvas.getContext('2d');
  const gradient = ctx.createLinearGradient(0, 0, 0, 256);
  gradient.addColorStop(0, '#221d29');
  gradient.addColorStop(0.55, '#332b3c');
  gradient.addColorStop(1, '#3b3244');
  ctx.fillStyle = gradient;
  ctx.fillRect(0, 0, 16, 256);
  return canvasTexture(THREE, canvas);
}

function cushion(THREE, material, width, height, depth) {
  const mesh = new THREE.Mesh(new THREE.SphereGeometry(1, 22, 16), material);
  mesh.scale.set(width / 2, height / 2, depth / 2);
  mesh.castShadow = true;
  mesh.receiveShadow = true;
  return mesh;
}

function box(THREE, material, width, height, depth) {
  const mesh = new THREE.Mesh(new THREE.BoxGeometry(width, height, depth), material);
  mesh.castShadow = true;
  mesh.receiveShadow = true;
  return mesh;
}

function buildCouch(THREE) {
  const group = new THREE.Group();
  const fabric = new THREE.MeshStandardMaterial({ color: ROOM.couch, roughness: 0.95, metalness: 0.0 });
  const dark = new THREE.MeshStandardMaterial({ color: ROOM.couchDark, roughness: 0.95 });
  const feet = new THREE.MeshStandardMaterial({ color: ROOM.wood, roughness: 0.6 });

  const base = box(THREE, dark, 2.05, 0.34, 0.95);
  base.position.set(0, 0.28, 1.55);
  group.add(base);

  for (const side of [-1, 1]) {
    const arm = box(THREE, fabric, 0.22, 0.42, 0.95);
    arm.position.set(side * 0.915, 0.62, 1.55);
    group.add(arm);
    const top = cushion(THREE, fabric, 0.22, 0.2, 0.95);
    top.position.set(side * 0.915, 0.82, 1.55);
    group.add(top);
    const foot = box(THREE, feet, 0.1, 0.11, 0.1);
    foot.position.set(side * 0.85, 0.055, 1.2);
    group.add(foot);
    const foot2 = foot.clone();
    foot2.position.z = 1.9;
    group.add(foot2);
  }

  // Seat: two pillowy cushions. Their top sits at SEAT_HEIGHT.
  for (const side of [-1, 1]) {
    const seat = cushion(THREE, fabric, 0.95, 0.24, 0.86);
    seat.position.set(side * 0.49, SEAT_HEIGHT - 0.12, 1.53);
    group.add(seat);
  }

  const backRail = box(THREE, dark, 2.05, 0.62, 0.16);
  backRail.position.set(0, 0.73, 1.96);
  group.add(backRail);
  for (const side of [-1, 1]) {
    const back = cushion(THREE, fabric, 0.95, 0.62, 0.3);
    back.position.set(side * 0.49, 0.78, 1.84);
    back.rotation.x = -0.12;
    group.add(back);
  }
  return group;
}

function buildTable(THREE, x, z) {
  const group = new THREE.Group();
  const wood = new THREE.MeshStandardMaterial({ color: ROOM.wood, roughness: 0.55 });
  const top = box(THREE, wood, 0.6, 0.05, 0.5);
  top.position.set(0, 0.52, 0);
  group.add(top);
  for (const sx of [-1, 1]) {
    for (const sz of [-1, 1]) {
      const leg = box(THREE, wood, 0.045, 0.5, 0.045);
      leg.position.set(sx * 0.25, 0.25, sz * 0.2);
      group.add(leg);
    }
  }
  group.position.set(x, 0, z);
  return group;
}

function buildLamp(THREE) {
  const group = new THREE.Group();
  const metal = new THREE.MeshStandardMaterial({ color: ROOM.metal, roughness: 0.35, metalness: 0.8 });
  const base = new THREE.Mesh(new THREE.CylinderGeometry(0.17, 0.2, 0.04, 20), metal);
  base.position.y = 0.02;
  base.receiveShadow = true;
  group.add(base);
  const pole = new THREE.Mesh(new THREE.CylinderGeometry(0.018, 0.018, 1.2, 12), metal);
  pole.position.y = 0.62;
  pole.castShadow = true;
  group.add(pole);

  const shadeMaterial = new THREE.MeshStandardMaterial({
    color: 0xffe0b2,
    emissive: 0xffb066,
    emissiveIntensity: 0.9,
    roughness: 0.9,
    side: THREE.DoubleSide,
  });
  const shade = new THREE.Mesh(new THREE.CylinderGeometry(0.17, 0.24, 0.26, 24, 1, true), shadeMaterial);
  shade.position.y = 1.3;
  group.add(shade);

  const bulb = new THREE.PointLight(0xffb066, 11, 7, 2);
  bulb.position.set(0, 1.26, 0);
  group.add(bulb);
  group.userData.bulb = bulb;
  return group;
}

function buildPicture(THREE) {
  const canvas = canvas2d(192, 144);
  const ctx = canvas.getContext('2d');
  ctx.fillStyle = '#2b3a4a';
  ctx.fillRect(0, 0, 192, 144);
  ctx.fillStyle = '#4c6b52';
  ctx.beginPath();
  ctx.moveTo(0, 110);
  ctx.lineTo(60, 60);
  ctx.lineTo(110, 105);
  ctx.lineTo(150, 72);
  ctx.lineTo(192, 112);
  ctx.lineTo(192, 144);
  ctx.lineTo(0, 144);
  ctx.closePath();
  ctx.fill();
  ctx.fillStyle = '#f2d98a';
  ctx.beginPath();
  ctx.arc(148, 40, 15, 0, Math.PI * 2);
  ctx.fill();
  const group = new THREE.Group();
  const frame = new THREE.Mesh(
    new THREE.BoxGeometry(0.66, 0.52, 0.04),
    new THREE.MeshStandardMaterial({ color: 0x6b4a2c, roughness: 0.6 }),
  );
  group.add(frame);
  const art = new THREE.Mesh(
    new THREE.PlaneGeometry(0.58, 0.44),
    new THREE.MeshStandardMaterial({ map: canvasTexture(THREE, canvas), roughness: 0.95 }),
  );
  art.position.z = 0.021;
  group.add(art);
  return group;
}

/**
 * Builds the room into `scene` and returns the handles the rest of the scene
 * needs: the lamp (so it can flicker with the TV), and the list of materials
 * that shadows are switched on and off with.
 */
export function buildRoom(THREE, scene) {
  const group = new THREE.Group();

  const floor = new THREE.Mesh(
    new THREE.PlaneGeometry(9, 9),
    new THREE.MeshStandardMaterial({ map: floorTexture(THREE), color: ROOM.floor, roughness: 0.85 }),
  );
  floor.rotation.x = -Math.PI / 2;
  floor.receiveShadow = true;
  group.add(floor);

  const rug = new THREE.Mesh(
    new THREE.PlaneGeometry(3.5, 2.6),
    new THREE.MeshStandardMaterial({ map: rugTexture(THREE), color: ROOM.rug, roughness: 1.0 }),
  );
  rug.rotation.x = -Math.PI / 2;
  rug.position.set(0, 0.006, 0.35);
  rug.receiveShadow = true;
  group.add(rug);

  const wallMaterial = new THREE.MeshStandardMaterial({
    map: wallTexture(THREE),
    color: ROOM.wall,
    roughness: 0.95,
  });
  const back = new THREE.Mesh(new THREE.PlaneGeometry(9, 3.4), wallMaterial);
  back.position.set(0, 1.7, -2.45);
  back.receiveShadow = true;
  group.add(back);
  for (const side of [-1, 1]) {
    const wall = new THREE.Mesh(new THREE.PlaneGeometry(6, 3.4), wallMaterial);
    wall.position.set(side * 3.4, 1.7, 0.5);
    wall.rotation.y = -side * (Math.PI / 2);
    wall.receiveShadow = true;
    group.add(wall);
  }

  const skirting = new THREE.Mesh(
    new THREE.BoxGeometry(6.8, 0.12, 0.04),
    new THREE.MeshStandardMaterial({ color: 0x1d1a22, roughness: 0.8 }),
  );
  skirting.position.set(0, 0.06, -2.42);
  group.add(skirting);

  const picture = buildPicture(THREE);
  picture.position.set(-1.85, 1.75, -2.41);
  group.add(picture);

  group.add(buildCouch(THREE));
  group.add(buildTable(THREE, 1.55, 0.75));

  const lamp = buildLamp(THREE);
  lamp.position.set(-2.0, 0, 0.5);
  group.add(lamp);

  scene.add(group);

  // Base light. Low and cool, so the warm lamp and the TV both read as sources.
  const sky = new THREE.HemisphereLight(0x3a3550, 0x140f16, 0.55);
  scene.add(sky);
  const fill = new THREE.DirectionalLight(0xffd9b0, 0.32);
  fill.position.set(2.4, 3.2, 2.6);
  scene.add(fill);

  return { group, lamp, lampBulb: lamp.userData.bulb, sky, fill };
}
