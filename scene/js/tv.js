/**
 * The CRT, the picture on it, and the light it throws into the room.
 *
 * The picture is a 160x144 canvas turned into a CanvasTexture with
 * nearest-neighbour filtering, so a Game Boy pixel stays a square. Grayscale
 * bytes come off the wire and go through a 256-entry lookup table into either
 * the classic four-shade DMG green or plain gray (`G` toggles).
 *
 * The CRT look is in the screen's shader, not the canvas: each Game Boy row
 * gets a scanline (bright in the middle, darker at its edges), the corners of
 * the tube fall off a little, and there is a faint sheen on the glass. The
 * scanlines fade out when a row is smaller than a few screen pixels, so the
 * wide shot never shimmers with moire.
 *
 * The TV is also the key light: `luminance` is the mean of the frame, and the
 * spot light aimed at the couch follows it, so the room flickers with the
 * game. That is the single most important thing in the scene's look.
 */

import { Batch } from './batch.js';
import { GAMEBOY_SHADES, RETRO, ROOM, approach, clamp, hex } from './theme.js';

export const SCREEN_WIDTH = 160;
export const SCREEN_HEIGHT = 144;

const SCREEN_Z = -1.688;
const PANEL_W = 0.96;
const PANEL_H = 0.864;

/** Where the picture is, for the portrait layout's close-up camera. */
export const SCREEN = { x: 0, y: 0.86, z: SCREEN_Z, width: PANEL_W, height: PANEL_H };

function buildLut(mode) {
  const lut = new Uint8Array(256 * 3);
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
    lut[value * 3] = r;
    lut[value * 3 + 1] = g;
    lut[value * 3 + 2] = b;
  }
  return lut;
}

const GLOW_W = 1.9;
const GLOW_H = 1.7;

/** The halo round the tube: bright at the edge of the picture and falling
 *  off outward, almost nothing over the picture itself, so the glow reads
 *  from across the room without washing out the game. */
function glowTexture(THREE) {
  const W = 256;
  const H = 232;
  const canvas = document.createElement('canvas');
  canvas.width = W;
  canvas.height = H;
  const ctx = canvas.getContext('2d');
  const rw = (PANEL_W / GLOW_W) * W;
  const rh = (PANEL_H / GLOW_H) * H;
  const x0 = (W - rw) / 2;
  const y0 = (H - rh) / 2;
  // Wide soft strokes centred on the picture's edge stack into a falloff.
  ctx.strokeStyle = 'rgba(255,255,255,0.075)';
  for (let i = 0; i < 14; i += 1) {
    ctx.lineWidth = 4 + i * 7;
    ctx.strokeRect(x0, y0, rw, rh);
  }
  // Keep the picture clear, bar a whisper.
  ctx.clearRect(x0 + 2, y0 + 2, rw - 4, rh - 4);
  ctx.fillStyle = 'rgba(255,255,255,0.04)';
  ctx.fillRect(x0 + 2, y0 + 2, rw - 4, rh - 4);
  // Fade the square corners of the stroke stack to a round glow.
  const fade = ctx.createRadialGradient(W / 2, H / 2, rw * 0.45, W / 2, H / 2, W * 0.55);
  fade.addColorStop(0, 'rgba(0,0,0,1)');
  fade.addColorStop(1, 'rgba(0,0,0,0)');
  ctx.globalCompositeOperation = 'destination-in';
  ctx.fillStyle = fade;
  ctx.fillRect(0, 0, W, H);
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  return texture;
}

/** Scanlines, a vignette and a faint sheen, added to a MeshBasicMaterial. */
function crtShader(shader) {
  shader.fragmentShader = shader.fragmentShader.replace(
    '#include <map_fragment>',
    `#include <map_fragment>
    #ifdef USE_MAP
      float row = vMapUv.y * ${SCREEN_HEIGHT.toFixed(1)};
      // Rows per screen pixel: above about 0.3 the lines would alias, so
      // they fade out and the picture is left plain.
      float perPixel = fwidth(row);
      float strength = clamp((0.42 - perPixel) / 0.2, 0.0, 1.0);
      float line = 0.5 - 0.5 * cos(6.2831853 * row);
      float scan = mix(1.0, 0.66 + 0.44 * line, strength);
      vec2 q = vMapUv - 0.5;
      float vignette = 1.0 - 0.42 * pow(length(q * vec2(1.0, 1.08)) * 1.42, 3.0);
      diffuseColor.rgb *= scan * vignette * 1.06;
      diffuseColor.rgb += 0.035 * smoothstep(0.42, 0.0, length(vMapUv - vec2(0.28, 0.8)));
    #endif`,
  );
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
    // Every static part of the set is merged: the plastic in one mesh, the
    // chrome (knobs, badge, rabbit ears) in another. The cabinet it stands
    // on is room furniture, in props.js.
    const shell = new Batch(THREE);
    const chrome = new Batch(THREE);
    const body = ROOM.tv;
    const bezel = hex(RETRO.charcoal);
    const black = hex(RETRO.black);
    const cy = SCREEN.y;

    // The cabinet: 1.24 wide, standing on the stand top at y = 0.29, with
    // the tube's hump at the back.
    shell.box(1.24, 1.14, 0.6, { y: cy, z: -2.0, color: body });
    shell.box(0.84, 0.76, 0.2, { y: cy, z: -2.33, color: body });
    shell.box(0.5, 0.4, 0.06, { y: cy, z: -2.42, color: body });

    // Bezel: four bars round the picture, so the opening reads as glass,
    // and a recessed lip just inside them.
    const opening = { w: 1.0, h: 0.9 };
    const bars = [
      [opening.w + 0.24, 0.12, 0, (opening.h + 0.12) / 2],
      [opening.w + 0.24, 0.12, 0, -(opening.h + 0.12) / 2],
      [0.12, opening.h + 0.12, (opening.w + 0.12) / 2, 0],
      [0.12, opening.h + 0.12, -(opening.w + 0.12) / 2, 0],
    ];
    for (const [w, h, x, y] of bars) shell.box(w, h, 0.08, { x, y: cy + y, z: SCREEN_Z - 0.02, color: bezel });
    const lip = [
      [opening.w, 0.02, 0, opening.h / 2 - 0.01],
      [opening.w, 0.02, 0, -opening.h / 2 + 0.01],
      [0.02, opening.h, opening.w / 2 - 0.01, 0],
      [0.02, opening.h, -opening.w / 2 + 0.01, 0],
    ];
    for (const [w, h, x, y] of lip) shell.box(w, h, 0.05, { x, y: cy + y, z: SCREEN_Z - 0.025, color: black });

    // A speaker grille down the left of the bezel, air vents on the side.
    for (let i = 0; i < 11; i += 1) {
      shell.box(0.075, 0.012, 0.004, { x: -0.56, y: cy - 0.26 + i * 0.05, z: SCREEN_Z + 0.021, color: black });
    }
    for (let i = 0; i < 6; i += 1) {
      shell.box(0.004, 0.014, 0.3, { x: 0.621, y: cy + 0.2 + i * 0.04, z: -2.05, color: black });
    }
    // A row of front buttons on the bottom bar, and the power button.
    for (let i = 0; i < 4; i += 1) {
      shell.box(0.03, 0.018, 0.012, { x: 0.12 + i * 0.045, y: cy - 0.51, z: SCREEN_Z + 0.024, color: hex(RETRO.greyPlastic) });
    }
    shell.box(0.05, 0.03, 0.014, { x: -0.44, y: cy - 0.51, z: SCREEN_Z + 0.024, color: hex(RETRO.greyPlastic) });

    // Knobs, a nameless badge, and rabbit ears on a little dome.
    const steel = hex(RETRO.chrome);
    for (let i = 0; i < 2; i += 1) {
      chrome.cyl(0.035, 0.04, 0.03, 16, { x: 0.56, y: cy - 0.24 + i * 0.13, z: SCREEN_Z + 0.03, rx: Math.PI / 2, color: 0x7a7d84 });
    }
    chrome.box(0.12, 0.022, 0.006, { y: cy - 0.51, z: SCREEN_Z + 0.022, color: steel });
    const top = cy + 0.57;
    shell.sphere(0.075, { x: 0.12, y: top, z: -2.05, sy: 0.55, color: black }, 16, 8);
    chrome.rod([0.1, top + 0.03, -2.05], [-0.25, top + 0.52, -2.18], 0.006, 6, { color: steel, radiusFrom: 0.009 });
    chrome.rod([0.14, top + 0.03, -2.05], [0.52, top + 0.46, -2.15], 0.006, 6, { color: steel, radiusFrom: 0.009 });
    chrome.sphere(0.011, { x: -0.25, y: top + 0.52, z: -2.18, color: steel }, 8, 6);
    chrome.sphere(0.011, { x: 0.52, y: top + 0.46, z: -2.15, color: steel }, 8, 6);

    const shellMesh = shell.mesh(new THREE.MeshStandardMaterial({ vertexColors: true, roughness: 0.5, metalness: 0.12 }));
    this.group.add(shellMesh);
    const chromeMesh = chrome.mesh(new THREE.MeshStandardMaterial({ vertexColors: true, roughness: 0.25, metalness: 0.9 }));
    this.group.add(chromeMesh);

    const backing = new THREE.Mesh(
      new THREE.PlaneGeometry(opening.w, opening.h),
      new THREE.MeshStandardMaterial({ color: 0x141418, roughness: 0.7 }),
    );
    backing.position.set(0, cy, SCREEN_Z - 0.03);
    this.group.add(backing);

    const screen = new THREE.MeshBasicMaterial({ map: this.texture, toneMapped: false });
    screen.onBeforeCompile = crtShader;
    const panel = new THREE.Mesh(curvedPanel(THREE), screen);
    panel.position.set(0, cy, SCREEN_Z);
    this.group.add(panel);
    this.panel = panel;

    this.glow = new THREE.Mesh(
      new THREE.PlaneGeometry(GLOW_W, GLOW_H),
      new THREE.MeshBasicMaterial({
        map: glowTexture(THREE),
        transparent: true,
        blending: THREE.AdditiveBlending,
        depthWrite: false,
        toneMapped: false,
      }),
    );
    this.glow.position.set(0, cy, SCREEN_Z + 0.06);
    this.group.add(this.glow);

    const led = new THREE.Mesh(
      new THREE.SphereGeometry(0.014, 10, 8),
      new THREE.MeshBasicMaterial({ color: 0xff5544, toneMapped: false }),
    );
    led.position.set(-0.36, cy - 0.51, SCREEN_Z + 0.03);
    this.group.add(led);
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
    const lut = this._lut;
    let sum = 0;
    let p = 0;
    for (let y = 0; y < SCREEN_HEIGHT; y += 1) {
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
