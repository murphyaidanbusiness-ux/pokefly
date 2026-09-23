/**
 * The CRT, the picture on it, and the light it throws into the room.
 *
 * The picture is a 160x144 canvas turned into a CanvasTexture with
 * nearest-neighbour filtering, so a Game Boy pixel stays a square. Grayscale
 * bytes come off the wire and go through a 256-entry lookup table into either
 * the classic four-shade DMG green or plain gray (`G` toggles). Every other
 * scanline is darkened in the same pass, which is the whole scanline effect
 * and costs nothing extra.
 *
 * The TV is also the key light: `luminance` is the mean of the frame, and the
 * spot light aimed at the couch follows it, so the room flickers with the
 * game. That is the single most important thing in the scene's look.
 */

import { GAMEBOY_SHADES, ROOM, approach, clamp } from './theme.js';

export const SCREEN_WIDTH = 160;
export const SCREEN_HEIGHT = 144;

const SCREEN_Z = -1.688;
const PANEL_W = 0.96;
const PANEL_H = 0.864;

function buildLut(mode) {
  // Two tables: ordinary rows and the darker scanline rows.
  const bright = new Uint8Array(256 * 3);
  const dim = new Uint8Array(256 * 3);
  for (let value = 0; value < 256; value += 1) {
    let r;
    let g;
    let b;
    if (mode === 'gray') {
      r = value;
      g = value;
      b = value;
    } else {
      const shade = GAMEBOY_SHADES[value >> 6];
      r = shade[0];
      g = shade[1];
      b = shade[2];
    }
    bright[value * 3] = r;
    bright[value * 3 + 1] = g;
    bright[value * 3 + 2] = b;
    dim[value * 3] = r * 0.76;
    dim[value * 3 + 1] = g * 0.76;
    dim[value * 3 + 2] = b * 0.76;
  }
  return { bright, dim };
}

function glowTexture(THREE) {
  const canvas = document.createElement('canvas');
  canvas.width = 128;
  canvas.height = 128;
  const ctx = canvas.getContext('2d');
  const gradient = ctx.createRadialGradient(64, 64, 4, 64, 64, 64);
  gradient.addColorStop(0, 'rgba(255,255,255,0.55)');
  gradient.addColorStop(0.45, 'rgba(255,255,255,0.16)');
  gradient.addColorStop(1, 'rgba(255,255,255,0)');
  ctx.fillStyle = gradient;
  ctx.fillRect(0, 0, 128, 128);
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  return texture;
}

function curvedPanel(THREE) {
  const geometry = new THREE.PlaneGeometry(PANEL_W, PANEL_H, 20, 20);
  const position = geometry.attributes.position;
  for (let i = 0; i < position.count; i += 1) {
    const u = position.getX(i) / (PANEL_W / 2);
    const v = position.getY(i) / (PANEL_H / 2);
    position.setZ(i, 0.042 * (1 - u * u * 0.92) * (1 - v * v * 0.92));
  }
  position.needsUpdate = true;
  geometry.computeVertexNormals();
  return geometry;
}

export class Television {
  constructor(THREE, scene) {
    this.THREE = THREE;
    this.mode = 'green';
    this.luminance = 0.35;
    this.smoothLuminance = 0.35;
    this.connected = false;
    this._lut = buildLut(this.mode);
    this._tint = new THREE.Color(0xbfe6c0);
    this._white = new THREE.Color(0xffffff);
    this._target = new THREE.Color();

    const canvas = document.createElement('canvas');
    canvas.width = SCREEN_WIDTH;
    canvas.height = SCREEN_HEIGHT;
    this.canvas = canvas;
    this.ctx = canvas.getContext('2d', { willReadFrequently: false });
    this.image = this.ctx.createImageData(SCREEN_WIDTH, SCREEN_HEIGHT);
    for (let i = 3; i < this.image.data.length; i += 4) this.image.data[i] = 255;
    this.showStatic();

    this.texture = new THREE.CanvasTexture(canvas);
    this.texture.magFilter = THREE.NearestFilter;
    this.texture.minFilter = THREE.NearestFilter;
    this.texture.generateMipmaps = false;
    this.texture.colorSpace = THREE.SRGBColorSpace;

    this.group = new THREE.Group();
    this._build(THREE);
    scene.add(this.group);
    this._buildLights(THREE, scene);
  }

  // -- geometry ---------------------------------------------------------

  _build(THREE) {
    const shell = new THREE.MeshStandardMaterial({ color: ROOM.tv, roughness: 0.55, metalness: 0.15 });
    const dark = new THREE.MeshStandardMaterial({ color: 0x141418, roughness: 0.7 });

    const body = new THREE.Mesh(new THREE.BoxGeometry(1.24, 1.02, 0.6), shell);
    body.position.set(0, 0.86, -2.0);
    body.castShadow = true;
    body.receiveShadow = true;
    this.group.add(body);

    const hump = new THREE.Mesh(new THREE.BoxGeometry(0.82, 0.68, 0.22), shell);
    hump.position.set(0, 0.86, -2.36);
    this.group.add(hump);

    // Bezel: four bars round the picture, so the opening reads as glass.
    const opening = { w: 1.0, h: 0.9 };
    const bezel = [
      [opening.w + 0.2, 0.12, 0, (opening.h + 0.12) / 2],
      [opening.w + 0.2, 0.12, 0, -(opening.h + 0.12) / 2],
      [0.12, opening.h + 0.12, (opening.w + 0.12) / 2, 0],
      [0.12, opening.h + 0.12, -(opening.w + 0.12) / 2, 0],
    ];
    for (const [w, h, x, y] of bezel) {
      const bar = new THREE.Mesh(new THREE.BoxGeometry(w, h, 0.08), shell);
      bar.position.set(x, 0.86 + y, SCREEN_Z - 0.02);
      bar.castShadow = true;
      this.group.add(bar);
    }

    const backing = new THREE.Mesh(new THREE.PlaneGeometry(opening.w, opening.h), dark);
    backing.position.set(0, 0.86, SCREEN_Z - 0.03);
    this.group.add(backing);

    const panel = new THREE.Mesh(
      curvedPanel(THREE),
      new THREE.MeshBasicMaterial({ map: this.texture, toneMapped: false }),
    );
    panel.position.set(0, 0.86, SCREEN_Z);
    this.group.add(panel);
    this.panel = panel;

    this.glow = new THREE.Mesh(
      new THREE.PlaneGeometry(1.9, 1.7),
      new THREE.MeshBasicMaterial({
        map: glowTexture(THREE),
        transparent: true,
        blending: THREE.AdditiveBlending,
        depthWrite: false,
        toneMapped: false,
      }),
    );
    this.glow.position.set(0, 0.86, SCREEN_Z + 0.06);
    this.group.add(this.glow);

    // Knobs and a power light, so the front is not a blank slab.
    for (let i = 0; i < 2; i += 1) {
      const knob = new THREE.Mesh(
        new THREE.CylinderGeometry(0.035, 0.04, 0.03, 16),
        new THREE.MeshStandardMaterial({ color: 0x55585f, roughness: 0.4, metalness: 0.6 }),
      );
      knob.rotation.x = Math.PI / 2;
      knob.position.set(0.55, 0.62 - i * 0.12, SCREEN_Z + 0.01);
      this.group.add(knob);
    }
    const led = new THREE.Mesh(
      new THREE.SphereGeometry(0.016, 10, 8),
      new THREE.MeshBasicMaterial({ color: 0xff5544, toneMapped: false }),
    );
    led.position.set(-0.55, 0.42, SCREEN_Z + 0.01);
    this.group.add(led);

    // Stand.
    const stand = new THREE.Mesh(
      new THREE.BoxGeometry(1.3, 0.36, 0.5),
      new THREE.MeshStandardMaterial({ color: ROOM.wood, roughness: 0.6 }),
    );
    stand.position.set(0, 0.18, -2.0);
    stand.castShadow = true;
    stand.receiveShadow = true;
    this.group.add(stand);
  }

  _buildLights(THREE, scene) {
    this.spot = new THREE.SpotLight(0xbfe6c0, 16, 9, 1.05, 0.9, 1.4);
    this.spot.position.set(0, 0.95, SCREEN_Z + 0.1);
    this.spot.target.position.set(0, 0.35, 1.5);
    this.spot.castShadow = true;
    this.spot.shadow.mapSize.set(1024, 1024);
    this.spot.shadow.bias = -0.0015;
    this.spot.shadow.camera.near = 0.4;
    this.spot.shadow.camera.far = 9;
    scene.add(this.spot);
    scene.add(this.spot.target);

    // A second, shadowless light so the TV also lights its own surroundings.
    this.fill = new THREE.PointLight(0xbfe6c0, 5, 4.5, 2);
    this.fill.position.set(0, 0.86, SCREEN_Z + 0.25);
    scene.add(this.fill);
  }

  // -- picture ----------------------------------------------------------

  setMode(mode) {
    this.mode = mode === 'gray' ? 'gray' : 'green';
    this._lut = buildLut(this.mode);
  }

  toggleMode() {
    this.setMode(this.mode === 'green' ? 'gray' : 'green');
    return this.mode;
  }

  /** @param {Uint8Array} pixels 160*144 grayscale bytes, row major. */
  draw(pixels) {
    if (!pixels || pixels.length < SCREEN_WIDTH * SCREEN_HEIGHT) return;
    const data = this.image.data;
    const { bright, dim } = this._lut;
    let sum = 0;
    let p = 0;
    for (let y = 0; y < SCREEN_HEIGHT; y += 1) {
      const lut = y & 1 ? dim : bright;
      for (let x = 0; x < SCREEN_WIDTH; x += 1) {
        const value = pixels[p];
        sum += value;
        const k = value * 3;
        const o = p * 4;
        data[o] = lut[k];
        data[o + 1] = lut[k + 1];
        data[o + 2] = lut[k + 2];
        p += 1;
      }
    }
    this.luminance = sum / (SCREEN_WIDTH * SCREEN_HEIGHT * 255);
    this.connected = true;
    this.ctx.putImageData(this.image, 0, 0);
    this.texture.needsUpdate = true;
  }

  /** No feed: analogue snow, so a dead socket is obvious from across the room. */
  showStatic() {
    const data = this.image.data;
    for (let i = 0; i < data.length; i += 4) {
      const value = Math.random() < 0.5 ? 28 : 40 + Math.floor(Math.random() * 190);
      data[i] = value;
      data[i + 1] = value;
      data[i + 2] = value;
    }
    this.luminance = 0.3;
    this.connected = false;
    this.ctx.putImageData(this.image, 0, 0);
    if (this.texture) this.texture.needsUpdate = true;
  }

  /** Follows the picture. Call once a frame with the frame time in seconds. */
  update(dt) {
    this.smoothLuminance = approach(this.smoothLuminance, this.luminance, 11, dt);
    const level = clamp(this.smoothLuminance, 0, 1);
    const base = this.mode === 'gray' ? this._white : this._tint;
    this._target.copy(base).lerp(this._white, 0.25 + 0.4 * level);
    this.spot.color.copy(this._target);
    this.fill.color.copy(this._target);
    this.spot.intensity = 5 + 30 * level;
    this.fill.intensity = 1.6 + 9 * level;
    this.glow.material.opacity = this.connected ? 0.25 + 0.55 * level : 0.22;
    this.glow.material.color.copy(this._target);
  }

  setShadows(on) {
    this.spot.castShadow = on;
  }
}
