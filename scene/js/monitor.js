/**
 * The brain monitor: an oscilloscope-shaped box on the side table showing a
 * scrolling spike raster, with seven bars for the learned MBON biases.
 *
 * Each column of the raster is one state message. The top block is the seven
 * motor pools, eight neurons each, in their own colours and labelled down the
 * left. The speckled band underneath is 200 neurons drawn from the sensory and
 * hidden population, so the pools are visibly sitting inside a network rather
 * than floating on their own.
 *
 * The bars on the ledge are the mushroom body's learned bias per pool: up is a
 * pool this screen has paid off for before, down is one it has not.
 */

import { POOLS, POOL_COLOR, POOL_HEX, clamp } from './theme.js';

const RASTER_W = 300;
const RASTER_H = 240;
const LABEL_W = 60;
const PER_POOL = 8;
const ROW_PITCH = 2;
const POOL_PITCH = 19;
const MOTOR_TOP = 4;
const HIDDEN_TOP = 144;
const HIDDEN_HEIGHT = 94;
const BACKGROUND = '#080b0e';

function newCanvas(width, height) {
  const canvas = document.createElement('canvas');
  canvas.width = width;
  canvas.height = height;
  return canvas;
}

export class Monitor {
  constructor(THREE, scene) {
    this.THREE = THREE;
    this.labels = [];
    this.poolRows = new Map();
    this.hiddenRows = [];
    this.lastUpload = 0;
    this.dirty = true;

    this.raster = newCanvas(RASTER_W, RASTER_H);
    this.rasterCtx = this.raster.getContext('2d');
    this.rasterCtx.fillStyle = BACKGROUND;
    this.rasterCtx.fillRect(0, 0, RASTER_W, RASTER_H);

    this.display = newCanvas(LABEL_W + RASTER_W, RASTER_H);
    this.displayCtx = this.display.getContext('2d');

    this.texture = new THREE.CanvasTexture(this.display);
    this.texture.colorSpace = THREE.SRGBColorSpace;
    this.texture.generateMipmaps = false;
    this.texture.minFilter = THREE.LinearFilter;
    this.texture.magFilter = THREE.LinearFilter;

    this.group = new THREE.Group();
    this.group.position.set(1.55, 0.545, 0.75);
    this.group.rotation.y = 0.3;
    this._build(THREE);
    scene.add(this.group);
    this._composite();
  }

  _build(THREE) {
    const shell = new THREE.MeshStandardMaterial({ color: 0x252a31, roughness: 0.6, metalness: 0.25 });
    const trim = new THREE.MeshStandardMaterial({ color: 0x3c434d, roughness: 0.4, metalness: 0.5 });

    const body = new THREE.Mesh(new THREE.BoxGeometry(0.52, 0.4, 0.34), shell);
    body.position.y = 0.2;
    body.castShadow = true;
    body.receiveShadow = true;
    this.group.add(body);

    const frame = new THREE.Mesh(new THREE.BoxGeometry(0.44, 0.3, 0.02), trim);
    frame.position.set(0, 0.22, 0.171);
    this.group.add(frame);

    const screen = new THREE.Mesh(
      new THREE.PlaneGeometry(0.4, 0.26),
      new THREE.MeshBasicMaterial({ map: this.texture, toneMapped: false }),
    );
    screen.position.set(0, 0.22, 0.183);
    this.group.add(screen);

    const screenLight = new THREE.PointLight(0x7fe8c8, 0.5, 0.9, 2);
    screenLight.position.set(0, 0.22, 0.28);
    this.group.add(screenLight);

    // Two knobs and a carry handle, so it reads as a bench instrument.
    for (let i = 0; i < 2; i += 1) {
      const knob = new THREE.Mesh(new THREE.CylinderGeometry(0.022, 0.026, 0.02, 14), trim);
      knob.rotation.x = Math.PI / 2;
      knob.position.set(-0.13 + i * 0.26, 0.05, 0.175);
      this.group.add(knob);
    }
    const handle = new THREE.Mesh(new THREE.TorusGeometry(0.07, 0.008, 8, 20, Math.PI), trim);
    handle.position.set(0, 0.4, 0);
    handle.rotation.z = 0;
    this.group.add(handle);

    // The ledge the MBON bars stand on.
    const ledge = new THREE.Mesh(new THREE.BoxGeometry(0.48, 0.012, 0.08), trim);
    ledge.position.set(0, 0.405, 0.16);
    this.group.add(ledge);

    this.bars = [];
    POOLS.forEach((name, index) => {
      const pivot = new THREE.Group();
      pivot.position.set(-0.18 + index * 0.06, 0.411, 0.16);
      const material = new THREE.MeshStandardMaterial({
        color: POOL_HEX[name],
        emissive: POOL_HEX[name],
        emissiveIntensity: 0.5,
        roughness: 0.4,
      });
      const bar = new THREE.Mesh(new THREE.BoxGeometry(0.028, 1, 0.028), material);
      bar.position.y = 0;
      pivot.add(bar);
      const cap = new THREE.Mesh(
        new THREE.BoxGeometry(0.034, 0.006, 0.034),
        new THREE.MeshBasicMaterial({ color: POOL_HEX[name], toneMapped: false }),
      );
      cap.position.y = -0.004;
      pivot.add(cap);
      this.group.add(pivot);
      this.bars.push({ pivot, bar, material });
    });
  }

  /** Called when the hello arrives: which sampled neuron belongs to which pool. */
  setLabels(labels) {
    this.labels = labels || [];
    this.poolRows = new Map();
    this.hiddenRows = [];
    const seen = Object.fromEntries(POOLS.map((name) => [name, 0]));
    this.labels.forEach((label, index) => {
      if (label && seen[label] !== undefined) {
        const slot = seen[label];
        seen[label] += 1;
        if (slot < PER_POOL) {
          this.poolRows.set(index, {
            y: MOTOR_TOP + POOLS.indexOf(label) * POOL_PITCH + slot * ROW_PITCH,
            color: POOL_COLOR[label],
          });
        }
      } else {
        this.hiddenRows.push(index);
      }
    });
    this.dirty = true;
  }

  /** One column: the spike bits of the sampled neurons this tick. */
  pushColumn(bits) {
    const ctx = this.rasterCtx;
    ctx.globalCompositeOperation = 'copy';
    ctx.drawImage(this.raster, -1, 0);
    ctx.globalCompositeOperation = 'source-over';
    ctx.fillStyle = BACKGROUND;
    ctx.fillRect(RASTER_W - 1, 0, 1, RASTER_H);

    if (bits) {
      for (const [index, row] of this.poolRows) {
        if (bits[index]) {
          ctx.fillStyle = row.color;
          ctx.fillRect(RASTER_W - 1, row.y, 1, ROW_PITCH);
        }
      }
      ctx.fillStyle = 'rgba(190,205,225,0.85)';
      const total = Math.max(1, this.hiddenRows.length);
      this.hiddenRows.forEach((index, i) => {
        if (bits[index]) {
          ctx.fillRect(RASTER_W - 1, HIDDEN_TOP + Math.floor((i / total) * HIDDEN_HEIGHT), 1, 1);
        }
      });
    }
    this.dirty = true;
  }

  setMbon(values) {
    if (!values) return;
    this.bars.forEach((entry, index) => {
      const value = Number(values[index]) || 0;
      const height = clamp(Math.abs(value) / 3, 0.02, 1) * 0.11;
      entry.bar.scale.y = height;
      entry.bar.position.y = value >= 0 ? height / 2 : -height / 2;
      entry.material.emissiveIntensity = 0.25 + 1.1 * clamp(Math.abs(value) / 3, 0, 1);
      entry.material.color.setHex(value >= 0 ? POOL_HEX[POOLS[index]] : 0x5a6474);
    });
  }

  _composite() {
    const ctx = this.displayCtx;
    ctx.fillStyle = BACKGROUND;
    ctx.fillRect(0, 0, LABEL_W + RASTER_W, RASTER_H);
    ctx.drawImage(this.raster, LABEL_W, 0);

    ctx.font = 'bold 12px ui-monospace, Consolas, monospace';
    ctx.textBaseline = 'middle';
    ctx.textAlign = 'left';
    POOLS.forEach((name, index) => {
      const y = MOTOR_TOP + index * POOL_PITCH + (PER_POOL * ROW_PITCH) / 2;
      ctx.fillStyle = POOL_COLOR[name];
      ctx.fillText(name, 6, y);
      ctx.fillStyle = 'rgba(255,255,255,0.08)';
      ctx.fillRect(LABEL_W, MOTOR_TOP + index * POOL_PITCH + PER_POOL * ROW_PITCH + 2, RASTER_W, 1);
    });
    ctx.fillStyle = 'rgba(255,255,255,0.28)';
    ctx.fillRect(0, HIDDEN_TOP - 6, LABEL_W + RASTER_W, 1);
    ctx.fillStyle = 'rgba(190,205,225,0.8)';
    ctx.font = '11px ui-monospace, Consolas, monospace';
    ctx.fillText('rest of', 6, HIDDEN_TOP + 14);
    ctx.fillText('the net', 6, HIDDEN_TOP + 28);
    this.texture.needsUpdate = true;
  }

  /** Redraw the prop's screen at most 30 times a second, whatever the feed does. */
  update(now) {
    if (!this.dirty || now - this.lastUpload < 0.033) return;
    this.lastUpload = now;
    this.dirty = false;
    this._composite();
  }
}
