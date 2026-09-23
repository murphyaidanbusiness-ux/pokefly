/**
 * Merges many small static shapes into one mesh per material.
 *
 * The room has a lot of little things in it (tapes, cans, slats, knobs) and
 * each separate mesh is a draw call, twice over for anything in the shadow
 * pass. A Batch collects primitives placed in world or prop space, bakes the
 * transform and a colour into the vertices, and hands back one Mesh. The
 * material then uses `vertexColors`, so one material can paint a brown leg and
 * a beige console in the same draw.
 *
 * Textured parts use a rectangle of a shared atlas: `uv: [u0, v0, u1, v1]`
 * squeezes the primitive's own 0..1 UVs into it. `uvScale` instead stretches
 * them, for a repeating texture such as the wallpaper.
 *
 * Nothing here runs per frame. Merging happens once, at build time.
 */

export class Batch {
  constructor(THREE) {
    this.THREE = THREE;
    this.parts = [];
    this.base = new THREE.Matrix4();
    this._local = new THREE.Matrix4();
    this._q = new THREE.Quaternion();
    this._e = new THREE.Euler();
    this._p = new THREE.Vector3();
    this._s = new THREE.Vector3();
    this._c = new THREE.Color();
  }

  /** The frame the next parts are placed in: a prop's origin and its turn
   *  about y (then x, z). `at()` with no arguments goes back to world space. */
  at(x = 0, y = 0, z = 0, ry = 0, rx = 0, rz = 0) {
    this._e.set(rx, ry, rz, 'YXZ');
    this._q.setFromEuler(this._e);
    this.base.compose(this._p.set(x, y, z), this._q, this._s.set(1, 1, 1));
    return this;
  }

  /**
   * Adds a geometry (which it takes ownership of and transforms in place).
   * Options: x y z, rx ry rz (radians, XYZ order), sx sy sz or s, color (hex),
   * uv [u0 v0 u1 v1] into an atlas, uvScale [su sv]. `paint(color, x, y, z)`
   * instead of `color` sets each vertex's colour from where it is in the
   * part's own frame, before any of the transform: stripes, bands, a fade.
   */
  add(geometry, o = {}) {
    const THREE = this.THREE;
    const count = geometry.attributes.position.count;
    const colors = new Float32Array(count * 3);
    if (o.paint) {
      const position = geometry.attributes.position;
      for (let i = 0; i < count; i += 1) {
        o.paint(this._c.setHex(0xffffff), position.getX(i), position.getY(i), position.getZ(i));
        colors[i * 3] = this._c.r;
        colors[i * 3 + 1] = this._c.g;
        colors[i * 3 + 2] = this._c.b;
      }
    } else {
      this._c.setHex(o.color ?? 0xffffff);
      for (let i = 0; i < count; i += 1) {
        colors[i * 3] = this._c.r;
        colors[i * 3 + 1] = this._c.g;
        colors[i * 3 + 2] = this._c.b;
      }
    }
    if (o.q) {
      this._q.copy(o.q);
    } else {
      this._e.set(o.rx || 0, o.ry || 0, o.rz || 0, o.order || 'XYZ');
      this._q.setFromEuler(this._e);
    }
    const s = o.s ?? 1;
    this._local.compose(
      this._p.set(o.x || 0, o.y || 0, o.z || 0),
      this._q,
      this._s.set(o.sx ?? s, o.sy ?? s, o.sz ?? s),
    );
    this._local.premultiply(this.base);
    geometry.applyMatrix4(this._local);
    geometry.setAttribute('color', new THREE.BufferAttribute(colors, 3));

    const uv = geometry.attributes.uv;
    if (uv && (o.uv || o.uvScale)) {
      for (let i = 0; i < uv.count; i += 1) {
        let u = uv.getX(i);
        let v = uv.getY(i);
        if (o.uvScale) {
          u *= o.uvScale[0];
          v *= o.uvScale[1];
        }
        if (o.uv) {
          u = o.uv[0] + u * (o.uv[2] - o.uv[0]);
          v = o.uv[1] + v * (o.uv[3] - o.uv[1]);
        }
        uv.setXY(i, u, v);
      }
    }
    this.parts.push(geometry);
    return this;
  }

  box(w, h, d, o) {
    return this.add(new this.THREE.BoxGeometry(w, h, d), o);
  }

  cyl(radiusTop, radiusBottom, height, segments, o) {
    return this.add(new this.THREE.CylinderGeometry(radiusTop, radiusBottom, height, segments), o);
  }

  sphere(radius, o, widthSegments = 12, heightSegments = 8) {
    return this.add(new this.THREE.SphereGeometry(radius, widthSegments, heightSegments), o);
  }

  plane(w, h, o) {
    return this.add(new this.THREE.PlaneGeometry(w, h), o);
  }

  /** A cylinder from one point to another, [x, y, z] each, in the current frame. */
  rod(from, to, radius, segments, o = {}) {
    const THREE = this.THREE;
    const a = new THREE.Vector3(...from);
    const direction = new THREE.Vector3(...to).sub(a);
    const length = direction.length();
    const q = new THREE.Quaternion().setFromUnitVectors(new THREE.Vector3(0, 1, 0), direction.normalize());
    const mid = a.addScaledVector(direction, length / 2);
    return this.add(new THREE.CylinderGeometry(radius, o.radiusFrom ?? radius, length, segments, 1, o.open ?? false), {
      ...o,
      x: mid.x,
      y: mid.y,
      z: mid.z,
      q,
    });
  }

  /** A tube through a list of [x, y, z] points (a cable, a cord, a wire). */
  tube(points, radius, o = {}) {
    const THREE = this.THREE;
    const curve = new THREE.CatmullRomCurve3(points.map((p) => new THREE.Vector3(...p)), false, 'centripetal');
    return this.add(new THREE.TubeGeometry(curve, o.segments ?? points.length * 8, radius, o.radial ?? 5, false), o);
  }

  /** One merged BufferGeometry of everything added so far. */
  geometry() {
    const THREE = this.THREE;
    let vertices = 0;
    let indices = 0;
    for (const part of this.parts) {
      vertices += part.attributes.position.count;
      indices += part.index ? part.index.count : part.attributes.position.count;
    }
    const position = new Float32Array(vertices * 3);
    const normal = new Float32Array(vertices * 3);
    const uv = new Float32Array(vertices * 2);
    const color = new Float32Array(vertices * 3);
    const index = vertices > 65535 ? new Uint32Array(indices) : new Uint16Array(indices);
    let v = 0;
    let k = 0;
    for (const part of this.parts) {
      const n = part.attributes.position.count;
      position.set(part.attributes.position.array, v * 3);
      if (part.attributes.normal) normal.set(part.attributes.normal.array, v * 3);
      if (part.attributes.uv) uv.set(part.attributes.uv.array, v * 2);
      color.set(part.attributes.color.array, v * 3);
      if (part.index) {
        const source = part.index.array;
        for (let i = 0; i < source.length; i += 1) index[k + i] = source[i] + v;
        k += source.length;
      } else {
        for (let i = 0; i < n; i += 1) index[k + i] = v + i;
        k += n;
      }
      v += n;
      part.dispose();
    }
    this.parts = [];
    const merged = new THREE.BufferGeometry();
    merged.setAttribute('position', new THREE.BufferAttribute(position, 3));
    merged.setAttribute('normal', new THREE.BufferAttribute(normal, 3));
    merged.setAttribute('uv', new THREE.BufferAttribute(uv, 2));
    merged.setAttribute('color', new THREE.BufferAttribute(color, 3));
    merged.setIndex(new THREE.BufferAttribute(index, 1));
    merged.computeBoundingSphere();
    merged.computeBoundingBox();
    return merged;
  }

  /** The merged mesh, or null if nothing was added. */
  mesh(material, { cast = true, receive = true } = {}) {
    if (!this.parts.length) return null;
    const mesh = new this.THREE.Mesh(this.geometry(), material);
    mesh.castShadow = cast;
    mesh.receiveShadow = receive;
    return mesh;
  }
}
