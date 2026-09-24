/**
 * A small orbit camera, written here rather than vendored, because it is
 * eighty lines and the scene only needs drag to turn, wheel to zoom, right
 * drag to pan, and a smooth move when a number key picks a view.
 *
 * The camera position is always derived from (target, radius, azimuth, polar),
 * so a view is four numbers and moving between two views is a lerp.
 */

import { approach, clamp } from './theme.js';

export class Orbit {
  constructor(THREE, camera, element) {
    this.THREE = THREE;
    this.camera = camera;
    this.element = element;
    this.target = new THREE.Vector3(0, 0.85, 0.55);
    this.wantTarget = this.target.clone();
    this.radius = 4.2;
    this.theta = 0.55;
    this.phi = 1.18;
    this.wantRadius = this.radius;
    this.wantTheta = this.theta;
    this.wantPhi = this.phi;
    this.shake = 0;
    this.spin = 0; // radians a second of automatic turn (`?orbit=1`); a drag pauses it
    this._drag = null;
    this._pointers = new Map();
    this._pinch = 0;
    this._scratch = new THREE.Vector3();
    this._bind();
  }

  /** @param {{eye:number[], look:number[]}} view from theme.VIEWS */
  setView(view, instant = false) {
    const THREE = this.THREE;
    const look = new THREE.Vector3(view.look[0], view.look[1], view.look[2]);
    const offset = new THREE.Vector3(view.eye[0], view.eye[1], view.eye[2]).sub(look);
    this.wantTarget.copy(look);
    this.wantRadius = Math.max(0.5, offset.length());
    this.wantPhi = Math.acos(clamp(offset.y / this.wantRadius, -1, 1));
    this.wantTheta = Math.atan2(offset.x, offset.z);
    if (instant) {
      this.target.copy(this.wantTarget);
      this.radius = this.wantRadius;
      this.phi = this.wantPhi;
      this.theta = this.wantTheta;
    }
  }

  knock(strength = 1) {
    this.shake = Math.min(1.4, this.shake + strength);
  }

  update(dt) {
    // A positive spin turns the way a drag to the LEFT does (see _turn).
    if (this.spin && !this._drag) this.wantTheta += this.spin * dt;
    const lambda = this._drag ? 30 : 7;
    this.theta = approach(this.theta, this.wantTheta, lambda, dt);
    this.phi = approach(this.phi, this.wantPhi, lambda, dt);
    this.radius = approach(this.radius, this.wantRadius, lambda, dt);
    this.target.lerp(this.wantTarget, 1 - Math.exp(-lambda * dt));

    const sinPhi = Math.sin(this.phi);
    const x = this.target.x + this.radius * sinPhi * Math.sin(this.theta);
    const y = this.target.y + this.radius * Math.cos(this.phi);
    const z = this.target.z + this.radius * sinPhi * Math.cos(this.theta);

    this.shake = Math.max(0, this.shake - dt * 3.2);
    const jolt = this.shake * this.shake * 0.05;
    this.camera.position.set(
      x + (Math.random() - 0.5) * jolt,
      y + (Math.random() - 0.5) * jolt,
      z + (Math.random() - 0.5) * jolt,
    );
    this.camera.lookAt(this.target);
  }

  // -- input -------------------------------------------------------------

  _bind() {
    const el = this.element;
    el.addEventListener('contextmenu', (e) => e.preventDefault());
    el.addEventListener('pointerdown', (e) => {
      el.setPointerCapture?.(e.pointerId);
      this._pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
      this._drag = e.button === 2 || e.shiftKey ? 'pan' : 'turn';
    });
    el.addEventListener('pointermove', (e) => {
      const last = this._pointers.get(e.pointerId);
      if (!last) return;
      const dx = e.clientX - last.x;
      const dy = e.clientY - last.y;
      last.x = e.clientX;
      last.y = e.clientY;
      if (this._pointers.size >= 2) {
        this._pinchZoom();
        return;
      }
      if (this._drag === 'pan') this._pan(dx, dy);
      else this._turn(dx, dy);
    });
    const release = (e) => {
      this._pointers.delete(e.pointerId);
      if (this._pointers.size === 0) this._drag = null;
      this._pinch = 0;
    };
    el.addEventListener('pointerup', release);
    el.addEventListener('pointercancel', release);
    el.addEventListener('pointerleave', release);
    el.addEventListener(
      'wheel',
      (e) => {
        e.preventDefault();
        this.wantRadius = clamp(this.wantRadius * (1 + Math.sign(e.deltaY) * 0.12), 0.55, 9);
      },
      { passive: false },
    );
  }

  _turn(dx, dy) {
    this.wantTheta -= dx * 0.006;
    this.wantPhi = clamp(this.wantPhi - dy * 0.006, 0.12, 1.52);
  }

  _pan(dx, dy) {
    const camera = this.camera;
    const scale = this.radius * 0.0016;
    const right = this._scratch.set(camera.matrix.elements[0], 0, camera.matrix.elements[2]).normalize();
    this.wantTarget.addScaledVector(right, -dx * scale);
    this.wantTarget.y = clamp(this.wantTarget.y + dy * scale, 0.05, 2.6);
  }

  _pinchZoom() {
    const points = [...this._pointers.values()];
    const distance = Math.hypot(points[0].x - points[1].x, points[0].y - points[1].y);
    if (this._pinch > 0) {
      this.wantRadius = clamp(this.wantRadius * (this._pinch / Math.max(1, distance)), 0.55, 9);
    }
    this._pinch = distance;
  }
}
