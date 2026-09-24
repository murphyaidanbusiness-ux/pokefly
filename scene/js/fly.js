/**
 * The fly, and everything its body says about the brain.
 *
 * A Drosophila caricature sitting on the cushion facing the TV: big faceted
 * red compound eyes, a golden thorax with dark stripes down its back and
 * bristles, a banded abdomen that breathes, two veined wings folded over it,
 * halteres behind them, six legs with coxa, femur, tibia, five tarsal
 * segments, claws and pale pulvilli, feathered antennae, a proboscis, and a
 * controller held in the two front legs.
 *
 * What each part means, in one line each, because this is the whole point of
 * the scene:
 *
 *   controller     the button the brain is pressing right now: the control
 *                  goes down, lights up in that pool's colour, and the front
 *                  leg on that side reaches over and pokes that very control.
 *                  The d-pad tilts the way the fly is walking.
 *   head glow      the firing rate of the whole spiking network: the crown
 *                  of the head and the three ocelli on top light up, and a
 *                  small light in front of the face warms the pad.
 *   glow colour    dopamine: gold when the last thing that happened was
 *                  better than expected, cold blue when it was worse.
 *   antennae       the same signal again, as posture: perked up and spread,
 *                  or drooping.
 *   wings          buzzing means the anti-stuck reflex just fired.
 *   a hop          the same reflex: the fly startles off the cushion.
 *   leaning in     the game is in a battle: the fly scoots forward, tips
 *                  toward the TV, lifts its abdomen and keeps its eyes up.
 *   grooming       START was pressed: the right leg taps START, then both
 *                  front legs come off the pad, rub together, and wipe the
 *                  eyes. Flies groom.
 *   a gold pulse in the head      a milestone just landed (three beats).
 *
 * And some that mean nothing, so it looks alive between presses: the
 * abdomen pumps as it breathes, an antenna twitches now and then, the wings
 * shiver, and every few seconds it shifts its weight and cocks its head.
 *
 * Nothing here is downloaded. Every shape is a three.js primitive, a lathe,
 * or a hand-drawn `Shape`; every texture is drawn in code (`flyskin.js`).
 * Static parts are merged by material (`batch.js`): the whole body is five
 * meshes, each front leg two, each wing one.
 */

import { Batch } from './batch.js';
import { chitinBump, eyeTextures, headGlowMask, roomReflection, wingTexture, WING } from './flyskin.js';
import { CABLE_FLOOR, FLY, POOL_HEX, POOLS, RETRO, approach, clamp, hex } from './theme.js';

const PRESS_SECONDS = 0.17;
const GOLD_SECONDS = 1.6; // the milestone pulse: three beats, then gone
const GROOM_SECONDS = 1.8; // a grooming bout: tap START, rub, wipe, back
const GOLD = { r: 1.0, g: 0.78, b: 0.22 };
const PAD_W = 0.3;
const PAD_D = 0.16;

const BUTTON_AT = {
  dpad: [-0.085, 0.0],
  B: [0.052, 0.012],
  A: [0.102, -0.016],
  START: [0.005, 0.05],
};
const DPAD_ARMS = ['UP', 'DOWN', 'LEFT', 'RIGHT'];
const ARM_AT = { UP: [0, -0.028], DOWN: [0, 0.028], LEFT: [-0.028, 0], RIGHT: [0.028, 0] };
const BUTTON_TOP = { dpad: 0.04, A: 0.041, B: 0.041, START: 0.036 };

// The front legs: hip (end of the coxa) in the body frame, and the two
// lengths the reach is solved with.
const FEMUR = 0.15;
const SHANK = 0.175; // tibia and tarsus together
const TIBIA = 0.105;

// Wings at rest: how far apart, how far down, how much the leading edge
// rolls down over the abdomen. And the buzz.
const WING_SPLAY = 0.17;
const WING_DROP = 0.2;
const WING_ROLL = -0.32;
const BUZZ_SPLAY = 1.05;
const BUZZ_LOW = -1.5;
const BUZZ_HIGH = 0.2;

// Parts of the head that must not glow sample the bottom of the glow mask.
const DARK = [0, 0, 1, 0.02];
const LIT = [0, 0.97, 1, 1];

const smooth = (a, b, x) => {
  const t = clamp((x - a) / (b - a), 0, 1);
  return t * t * (3 - 2 * t);
};

function padLabelTexture(THREE) {
  const canvas = document.createElement('canvas');
  canvas.width = 300;
  canvas.height = 160;
  const ctx = canvas.getContext('2d');
  ctx.clearRect(0, 0, 300, 160);
  const toCanvas = (x, z) => [((x + PAD_W / 2) / PAD_W) * 300, ((z + PAD_D / 2) / PAD_D) * 160];

  // A dark recess under the d-pad, so the cross reads even when it is level.
  const [dx, dz] = toCanvas(BUTTON_AT.dpad[0], BUTTON_AT.dpad[1]);
  ctx.fillStyle = 'rgba(0,0,0,0.30)';
  ctx.beginPath();
  ctx.arc(dx, dz, 40, 0, Math.PI * 2);
  ctx.fill();

  ctx.fillStyle = 'rgba(40,40,48,0.9)';
  ctx.font = 'bold 26px system-ui, sans-serif';
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  const [ax, az] = toCanvas(BUTTON_AT.A[0], BUTTON_AT.A[1] + 0.04);
  ctx.fillText('A', ax, az);
  const [bx, bz] = toCanvas(BUTTON_AT.B[0], BUTTON_AT.B[1] + 0.04);
  ctx.fillText('B', bx, bz);
  ctx.font = 'bold 15px system-ui, sans-serif';
  const [sx, sz] = toCanvas(BUTTON_AT.START[0], BUTTON_AT.START[1] - 0.026);
  ctx.fillText('START', sx, sz);

  // Speaker grille on the right, purely so the pad is not a blank slab.
  ctx.fillStyle = 'rgba(40,40,48,0.35)';
  for (let i = 0; i < 6; i += 1) {
    ctx.fillRect(238 + i * 8, 18, 4, 26);
  }

  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.anisotropy = 4;
  return texture;
}

// -- build-time shape helpers (none of these run per frame) --------------------

/** A rounded, tapering, slightly swollen tube from `a` to `b`: one leg
 *  segment, a neck, a stalk. `paint(color, t)` gets 0 at `a` and 1 at `b`. */
function segment(THREE, batch, a, b, r0, r1, o = {}) {
  const dir = new THREE.Vector3().subVectors(b, a);
  const length = dir.length();
  const bulge = o.bulge ?? 0;
  const rows = o.rows ?? 5;
  const profile = [new THREE.Vector2(0, -r0 * 0.5), new THREE.Vector2(r0 * 0.78, -r0 * 0.32)];
  for (let i = 0; i <= rows; i += 1) {
    const t = i / rows;
    profile.push(new THREE.Vector2((r0 + (r1 - r0) * t) * (1 + bulge * Math.sin(Math.PI * t)), t * length));
  }
  profile.push(new THREE.Vector2(r1 * 0.78, length + r1 * 0.32), new THREE.Vector2(0, length + r1 * 0.5));
  const q = new THREE.Quaternion().setFromUnitVectors(new THREE.Vector3(0, 1, 0), dir.normalize());
  const paint = o.paint ? (c, x, y) => o.paint(c, clamp(y / length, 0, 1)) : undefined;
  batch.add(new THREE.LatheGeometry(profile, o.radial ?? 8), {
    x: a.x,
    y: a.y,
    z: a.z,
    q,
    color: o.color,
    paint,
    uv: o.uv,
  });
}

/** A bristle: a thin dark open cone from `base` along `dir`. */
function bristle(THREE, batch, base, dir, length, radius, uv) {
  const tip = [base.x + dir.x * length, base.y + dir.y * length, base.z + dir.z * length];
  batch.rod([base.x, base.y, base.z], tip, radius * 0.15, 3, { radiusFrom: radius, open: true, color: FLY.bristle, uv });
}

/** The end of a leg: five tarsal beads from `ankle` to `toe`, two claws and
 *  two pale pulvilli. `down` is the side the sole faces. */
function foot(THREE, batch, ankle, toe, down) {
  const dir = new THREE.Vector3().subVectors(toe, ankle);
  const length = dir.length();
  dir.normalize();
  const across = new THREE.Vector3().crossVectors(dir, down).normalize();
  const shares = [0.34, 0.2, 0.16, 0.14, 0.16];
  const dark = new THREE.Color(FLY.leg);
  const mid = new THREE.Color(FLY.leg).lerp(new THREE.Color(FLY.legBase), 0.35);
  let at = 0;
  shares.forEach((share, i) => {
    const a = new THREE.Vector3().copy(ankle).addScaledVector(dir, at * length);
    at += share;
    const b = new THREE.Vector3().copy(ankle).addScaledVector(dir, (at - 0.015) * length);
    const r = 0.0088 - i * 0.0006;
    segment(THREE, batch, a, b, r, r * 0.9, {
      bulge: 0.12,
      rows: 2,
      radial: 6,
      paint: (c) => c.copy(i === 0 ? mid : dark),
    });
  });
  for (const k of [-1, 1]) {
    const root = new THREE.Vector3().copy(toe).addScaledVector(across, k * 0.004);
    const tip = new THREE.Vector3()
      .copy(root)
      .addScaledVector(dir, 0.01)
      .addScaledVector(down, 0.008)
      .addScaledVector(across, k * 0.004);
    batch.rod([root.x, root.y, root.z], [tip.x, tip.y, tip.z], 0.0006, 4, { radiusFrom: 0.0026, color: FLY.bristle });
    const pad = new THREE.Vector3()
      .copy(toe)
      .addScaledVector(down, 0.004)
      .addScaledVector(across, k * 0.0045)
      .addScaledVector(dir, 0.002);
    const q = new THREE.Quaternion().setFromUnitVectors(new THREE.Vector3(0, 0, 1), dir);
    batch.sphere(0.0048, { x: pad.x, y: pad.y, z: pad.z, q, sx: 1, sy: 0.7, sz: 1.35, color: FLY.pulvillus }, 6, 4);
  }
}

// -- the fly -------------------------------------------------------------------

export class FlyActor {
  constructor(THREE, scene, seatHeight) {
    this.THREE = THREE;
    this.time = 0;
    this.pressTimer = Object.fromEntries(POOLS.map((name) => [name, 0]));
    this.pressLevel = Object.fromEntries(POOLS.map((name) => [name, 0]));
    this.held = new Set();
    this.firing = 0;
    this.glow = 0;
    this.dope = 0;
    this.flash = 0;
    this.panic = 0;
    this.battle = 0;
    this.groom = 0;
    this.hopTimer = 0;
    this.gold = 0;
    this.twitch = 0;
    this.nextTwitch = 3 + Math.random() * 5;
    this.headYaw = 0;
    this.headPitch = 0;
    this.headRoll = 0;
    this.screen = 0.35;
    // Idle life: a weight shift with a head tilt, and an antenna twitch.
    this.shift = 0;
    this.shiftTarget = 0;
    this.nextShift = 4 + Math.random() * 4;
    this.antennaTwitch = [0, 0];
    this.nextAntennaTwitch = 2 + Math.random() * 3;

    this.group = new THREE.Group();
    this.group.position.set(0, seatHeight, 1.42);
    this.bob = new THREE.Group();
    this.lean = new THREE.Group();
    this.group.add(this.bob);
    this.bob.add(this.lean);

    // Scratch space for update, so a frame allocates nothing.
    this._v = new THREE.Vector3();
    this._d = new THREE.Vector3();
    this._perp = new THREE.Vector3();
    this._knee = new THREE.Vector3();
    this._tip = new THREE.Vector3();
    this._x = new THREE.Vector3();
    this._y = new THREE.Vector3();
    this._z = new THREE.Vector3();
    this._m = new THREE.Matrix4();

    this._materials(THREE);
    this._body(THREE);
    this._abdomen(THREE);
    this._head(THREE);
    this._wings(THREE);
    this._legs(THREE);
    this._controller(THREE);
    this._frontLegs(THREE);
    this._cable(THREE);
    scene.add(this.group);
  }

  // -- construction -----------------------------------------------------

  _materials(THREE) {
    const env = roomReflection(THREE);
    const bump = chitinBump(THREE);
    const eye = eyeTextures(THREE);
    const glowMask = headGlowMask(THREE);

    // Linear colours for the vertex painters.
    const C = (value) => new THREE.Color(value);
    this.paint = {
      thorax: C(FLY.thorax),
      thoraxDark: C(FLY.thoraxDark),
      pleura: C(FLY.pleura),
      belly: C(FLY.belly),
      head: C(FLY.head),
      crown: C(FLY.crown),
      vitta: C(FLY.vitta),
      light: C(FLY.stripeLight),
      dark: C(FLY.stripeDark),
      sternite: C(FLY.sternite),
      leg: C(FLY.leg),
      legBase: C(FLY.legBase),
    };

    // One cuticle for the whole body: vertex colours for the pattern, a
    // fine bump, a clear coat, a faintly teal specular and a thin-film layer
    // that between them throw the teal and bronze glints a real fly has on
    // its back.
    const chitin = new THREE.MeshPhysicalMaterial({
      vertexColors: true,
      roughness: 0.5,
      metalness: 0.0,
      bumpMap: bump,
      bumpScale: 0.8,
      specularColor: new THREE.Color(0x8fe6d0),
      clearcoat: 0.7,
      clearcoatRoughness: 0.22,
      iridescence: 0.9,
      iridescenceIOR: 1.4,
      iridescenceThicknessRange: [320, 500],
      envMap: env,
      envMapIntensity: 0.6,
    });
    // The head is the same cuticle, plus the glow on its crown.
    const head = chitin.clone();
    head.emissiveMap = glowMask;
    head.emissive = new THREE.Color(0xffd27a);
    head.emissiveIntensity = 0.4;

    // The compound eyes. The dark pseudopupil, the patch of facets that
    // look straight at the viewer, is worked out per pixel from the camera,
    // so it follows whichever camera is drawing and costs nothing per frame.
    const eyes = new THREE.MeshPhysicalMaterial({
      map: eye.map,
      bumpMap: eye.bump,
      bumpScale: 2.2,
      roughness: 0.34,
      metalness: 0.0,
      clearcoat: 1.0,
      clearcoatRoughness: 0.06,
      iridescence: 0.35,
      iridescenceIOR: 1.8,
      iridescenceThicknessRange: [320, 520],
      emissive: 0xff5030,
      emissiveMap: eye.map,
      emissiveIntensity: 0.12,
      envMap: env,
      envMapIntensity: 1.2,
    });
    eyes.onBeforeCompile = (shader) => {
      shader.fragmentShader = shader.fragmentShader
        .replace(
          '#include <color_fragment>',
          `#include <color_fragment>
          float pupil = smoothstep(0.955, 0.992, dot(normalize(vNormal), normalize(vViewPosition)));
          diffuseColor.rgb *= 1.0 - 0.82 * pupil;`,
        )
        .replace(
          '#include <emissivemap_fragment>',
          `#include <emissivemap_fragment>
          totalEmissiveRadiance *= 1.0 - 0.9 * pupil;`,
        );
    };
    eyes.customProgramCacheKey = () => 'fly-eye-pseudopupil';

    const wingMap = wingTexture(THREE);
    const wing = new THREE.MeshPhysicalMaterial({
      map: wingMap,
      emissive: 0x8fa4bb,
      emissiveMap: wingMap,
      emissiveIntensity: 0.35,
      transparent: true,
      side: THREE.DoubleSide,
      forceSinglePass: true, // a flat membrane: one pass, not back then front
      depthWrite: false,
      roughness: 0.18,
      metalness: 0.0,
      iridescence: 1.0,
      iridescenceIOR: 1.35,
      iridescenceThicknessRange: [260, 720],
      envMap: env,
      envMapIntensity: 1.0,
    });

    this.mat = {
      chitin,
      head,
      eyes,
      wing,
      blur: new THREE.MeshBasicMaterial({
        color: FLY.wing,
        vertexColors: true,
        transparent: true,
        opacity: 0,
        depthWrite: false,
        side: THREE.DoubleSide,
        forceSinglePass: true,
      }),
      pad: new THREE.MeshStandardMaterial({ color: FLY.pad, roughness: 0.55, vertexColors: true }),
      padDark: new THREE.MeshStandardMaterial({ color: FLY.padDark, roughness: 0.5 }),
    };
  }

  /** Thorax, scutellum, neck, halteres, the four standing legs and the
   *  front coxae, and the bristles: one mesh. */
  _body(THREE) {
    const P = this.paint;
    const V = THREE.Vector3;
    const batch = new Batch(THREE);
    this._bodyBatch = batch;

    // Thorax: a dome, golden on top with four dark stripes down the back,
    // paler on the sides, brown underneath.
    const T = { x: 0, y: 0.215, z: 0.0, a: 0.135, b: 0.128, c: 0.158 };
    batch.sphere(
      1,
      {
        x: T.x,
        y: T.y,
        z: T.z,
        sx: T.a,
        sy: T.b,
        sz: T.c,
        paint: (c, x, y, z) => {
          const top = smooth(-0.15, 0.55, y);
          c.copy(P.pleura).lerp(P.thorax, top);
          c.lerp(P.belly, smooth(-0.35, -0.85, y));
          const ax = Math.abs(x);
          const stripe = Math.exp(-(((ax - 0.14) / 0.075) ** 2)) + 0.9 * Math.exp(-(((ax - 0.42) / 0.085) ** 2));
          const along = smooth(-0.95, -0.55, z) * smooth(0.97, 0.6, z);
          c.lerp(P.thoraxDark, Math.min(1, stripe) * 0.85 * top * along);
        },
      },
      40,
      30,
    );
    // Scutellum: the little shield at the back of the thorax.
    batch.sphere(
      1,
      {
        x: 0,
        y: 0.318,
        z: 0.122,
        sx: 0.072,
        sy: 0.042,
        sz: 0.058,
        paint: (c, x, y) => c.copy(P.thorax).lerp(P.thoraxDark, 0.55 * smooth(0.4, -0.4, y)),
      },
      18,
      10,
    );
    // Neck.
    segment(THREE, batch, new V(0, 0.255, -0.12), new V(0, 0.285, -0.18), 0.042, 0.037, {
      radial: 12,
      color: 0xcfa878,
    });

    // Halteres: the little drumsticks behind the wings.
    for (const s of [-1, 1]) {
      const a = new V(s * 0.08, 0.29, 0.1);
      const b = new V(s * 0.108, 0.29, 0.128);
      segment(THREE, batch, a, b, 0.005, 0.004, { radial: 5, rows: 1, color: 0xd9bf92 });
      batch.sphere(0.012, { x: b.x + s * 0.004, y: b.y, z: b.z + 0.004, sx: 1, sy: 0.85, sz: 1.2, color: 0xeedcb6 }, 10, 8);
    }

    // Bristles on the thorax: two rows down the back, a finer row between
    // them, a few on the shoulders and sides, four long ones on the
    // scutellum, all raked backward.
    const onThorax = (ux, uy, uz, length, radius) => {
      const l = Math.hypot(ux, uy, uz);
      const u = [ux / l, uy / l, uz / l];
      const base = new V(T.x + T.a * u[0], T.y + T.b * u[1], T.z + T.c * u[2]);
      const normal = new V(u[0] / T.a, u[1] / T.b, u[2] / T.c).normalize();
      const dir = normal.multiplyScalar(0.55).add(new V(0, 0.05, 0.85)).normalize();
      bristle(THREE, batch, base, dir, length, radius);
    };
    for (const s of [-1, 1]) {
      for (const z of [-0.5, -0.1, 0.3, 0.6]) onThorax(s * 0.27, 0.9, z, 0.046, 0.003);
      for (const z of [-0.55, -0.15, 0.25]) onThorax(s * 0.08, 0.95, z, 0.02, 0.002);
      onThorax(s * 0.62, 0.45, -0.62, 0.04, 0.003); // humeral
      onThorax(s * 0.78, 0.5, -0.2, 0.04, 0.003); // notopleural
      onThorax(s * 0.72, 0.62, 0.3, 0.044, 0.003); // supra-alar
      for (const [bx, bz, spread] of [
        [0.035, 0.16, 0.3],
        [0.06, 0.13, 0.7],
      ]) {
        const base = new V(s * bx, 0.33, bz);
        const dir = new V(s * spread * 0.4, 0.28, 1).normalize();
        bristle(THREE, batch, base, dir, 0.062, 0.0032);
      }
    }
  }

  /** The abdomen: one lathe with six plates, each overlapping the next,
   *  painted golden with a dark band at its back edge, a pale notch down
   *  the middle and pale plates underneath. It pivots at its waist, so it
   *  can pump and lift. */
  _abdomen(THREE) {
    const P = this.paint;
    const L = 0.37;
    const edges = [0, 0.13, 0.29, 0.44, 0.58, 0.71, 0.83, 1.0];
    const envelope = (t) => {
      if (t < 0.35) return 0.076 + 0.049 * Math.sin((Math.PI / 2) * (t / 0.35));
      return 0.125 * Math.pow(Math.max(0, 1 - Math.pow((t - 0.35) / 0.65, 2.2)), 0.55);
    };
    const profile = [new THREE.Vector2(0, -0.01)];
    for (let k = 0; k < edges.length - 1; k += 1) {
      const a = edges[k];
      const b = edges[k + 1];
      const rows = k === edges.length - 2 ? 8 : 6;
      for (let i = 0; i <= rows; i += 1) {
        const s = i / rows;
        const t = a + (b - a) * s + (i === 0 && k > 0 ? 0.004 : 0);
        const r = envelope(Math.min(t, 0.999)) * (0.95 + 0.06 * s);
        profile.push(new THREE.Vector2(r, t * L));
      }
    }
    profile.push(new THREE.Vector2(0, L + 0.004));
    const geometry = new THREE.LatheGeometry(profile, 32);

    // Flatten a little top to bottom and curl the tip down. In the lathe's
    // frame y runs down the abdomen and -z will be the back.
    const position = geometry.attributes.position;
    for (let i = 0; i < position.count; i += 1) {
      const t = position.getY(i) / L;
      position.setZ(i, position.getZ(i) * 0.86 + 0.05 * t * t);
    }
    geometry.computeVertexNormals();

    const batch = new Batch(THREE);
    batch.add(geometry, {
      rx: Math.PI / 2,
      paint: (c, x, y, z) => {
        const t = clamp(y / L, 0, 1);
        let k = 0;
        while (k < edges.length - 2 && t >= edges[k + 1]) k += 1;
        const s = (t - edges[k]) / (edges[k + 1] - edges[k]);
        const r = Math.hypot(x, z - 0.05 * t * t) || 1;
        const back = -(z - 0.05 * t * t) / r; // 1 on the midline of the back
        const side = Math.abs(x) / r;
        c.copy(P.light);
        let band = smooth(0.5, 0.68, s) * smooth(-0.45, 0.2, back);
        if (back > 0.8 && side < 0.2) band *= 0.35; // the pale notch
        if (k >= 5) band = Math.max(band, 0.55 * smooth(-0.3, 0.3, back));
        if (k === 0) band *= 0.3;
        c.lerp(P.dark, band);
        c.lerp(P.sternite, smooth(-0.35, -0.8, back));
      },
    });

    this.abdomen = new THREE.Group();
    this.abdomen.position.set(0, 0.2, 0.09);
    const mesh = batch.mesh(this.mat.chitin);
    this.abdomen.add(mesh);
    this.lean.add(this.abdomen);
  }

  _head(THREE) {
    const P = this.paint;
    const V = THREE.Vector3;
    this.head = new THREE.Group();
    this.head.position.set(0, 0.3, -0.235);
    this.lean.add(this.head);

    const batch = new Batch(THREE);
    // The capsule: tan, the orange-red stripe up the face between the eyes,
    // darker behind, paler under. Its crown carries the glow (headGlowMask).
    batch.sphere(
      1,
      {
        sx: 0.1,
        sy: 0.098,
        sz: 0.082,
        paint: (c, x, y, z) => {
          c.copy(P.head);
          c.lerp(P.crown, 0.7 * smooth(0.45, 0.85, y) * smooth(-0.6, -0.2, z));
          const front = smooth(-0.2, -0.75, z);
          const middle = smooth(0.45, 0.12, Math.abs(x));
          c.lerp(P.vitta, 0.75 * front * middle * smooth(-0.5, 0.2, y));
          c.lerp(P.belly, 0.45 * smooth(0.1, 0.85, z));
          c.lerp(P.pleura, 0.4 * smooth(-0.3, -0.9, y));
        },
      },
      36,
      26,
    );
    // Ocelli: three simple eyes in a triangle on the crown. They light up
    // with the head.
    batch.sphere(0.009, { x: 0, y: 0.098, z: 0.0, color: FLY.ocellus, uv: LIT }, 10, 8);
    for (const s of [-1, 1]) {
      batch.sphere(0.008, { x: s * 0.016, y: 0.093, z: 0.02, color: FLY.ocellus, uv: LIT }, 10, 8);
    }
    // Face, and the proboscis under it ending in the labellum.
    batch.sphere(1, { x: 0, y: -0.035, z: -0.068, sx: 0.034, sy: 0.048, sz: 0.02, color: 0xb98449, uv: DARK }, 16, 12);
    segment(THREE, batch, new V(0, -0.06, -0.045), new V(0, -0.1, -0.078), 0.021, 0.017, {
      radial: 10,
      color: 0x9a6a3a,
      uv: DARK,
    });
    segment(THREE, batch, new V(0, -0.1, -0.078), new V(0, -0.122, -0.1), 0.015, 0.013, {
      radial: 10,
      color: 0xb8865a,
      uv: DARK,
    });
    for (const s of [-1, 1]) {
      batch.sphere(
        1,
        { x: s * 0.009, y: -0.128, z: -0.106, sx: 0.013, sy: 0.01, sz: 0.017, rz: s * 0.3, color: FLY.labellum, uv: DARK },
        12,
        8,
      );
    }
    // Head bristles: verticals and ocellars on the crown, orbitals along
    // the eyes, a short row behind.
    const hb = (x, y, z, dx, dy, dz, length, radius = 0.0028) =>
      bristle(THREE, batch, new V(x, y, z), new V(dx, dy, dz).normalize(), length, radius, DARK);
    for (const s of [-1, 1]) {
      hb(s * 0.038, 0.088, 0.035, s * 0.3, 0.7, 0.6, 0.048, 0.0032);
      hb(s * 0.022, 0.094, 0.045, s * -0.2, 0.8, 0.5, 0.04);
      hb(s * 0.008, 0.099, 0.012, s * 0.5, 0.7, -0.4, 0.03, 0.0024);
      hb(s * 0.03, 0.09, -0.035, s * 0.1, 0.8, -0.6, 0.034);
      hb(s * 0.034, 0.082, -0.058, s * 0.1, 0.7, -0.8, 0.028, 0.0024);
      for (let i = 0; i < 4; i += 1) {
        const a = -0.2 + i * 0.35;
        hb(s * 0.085 * Math.cos(a), 0.05 * Math.sin(a) + 0.02, 0.055, s * 0.3, 0.2, 1, 0.022, 0.002);
      }
    }
    this.headShell = batch.mesh(this.mat.head);
    this.head.add(this.headShell);

    // The compound eyes, both in one mesh. The left one reads the texture
    // mirrored, so both bulge the same way.
    const eyes = new Batch(THREE);
    for (const s of [-1, 1]) {
      const geometry = new THREE.SphereGeometry(1, 48, 36);
      if (s < 0) {
        const uv = geometry.attributes.uv;
        for (let i = 0; i < uv.count; i += 1) uv.setX(i, 0.5 - uv.getX(i));
      }
      eyes.add(geometry, { x: s * 0.074, y: 0.006, z: -0.02, sx: 0.09, sy: 0.114, sz: 0.104 });
    }
    this.eyes = eyes.mesh(this.mat.eyes);
    this.head.add(this.eyes);

    // The glow: the crown (above) and the ocelli light up with the firing
    // rate, and a small light warms whatever is near. There is no aura round
    // the head: a rim-lit shell was tried and it read as a helmet.
    this.glowColor = new THREE.Color(0xffd27a);
    this.brainLight = new THREE.PointLight(0xffd27a, 0.6, 1.2, 2);
    this.brainLight.position.set(0, 0.17, -0.17);
    this.head.add(this.brainLight);

    // Antennae: each on its own pivot, so one can twitch alone. Scape,
    // pedicel, the big oval third segment, and the feathered arista.
    this.antennae = [];
    for (const s of [-1, 1]) {
      const pivot = new THREE.Group();
      pivot.position.set(s * 0.019, 0.05, -0.085);
      pivot.userData.side = s;
      const a = new Batch(THREE);
      a.sphere(0.011, { color: 0xb07a40 }, 10, 8);
      segment(THREE, a, new V(0, 0, 0), new V(s * 0.008, 0.014, -0.016), 0.011, 0.012, { radial: 8, color: 0xa87038 });
      a.sphere(1, { x: s * 0.012, y: 0.03, z: -0.026, sx: 0.0145, sy: 0.024, sz: 0.0145, rx: -0.45, rz: -s * 0.2, color: 0x9c5a2c }, 14, 10);
      const arista = [new V(s * 0.02, 0.036, -0.03), new V(s * 0.03, 0.058, -0.038), new V(s * 0.046, 0.084, -0.042), new V(s * 0.064, 0.104, -0.036)];
      for (let i = 0; i < arista.length - 1; i += 1) {
        const p = arista[i];
        const q = arista[i + 1];
        a.rod([p.x, p.y, p.z], [q.x, q.y, q.z], 0.0016 - i * 0.0003, 4, { radiusFrom: 0.0024 - i * 0.0003, color: FLY.bristle });
        // Side branches, the feathering.
        for (const k of [-1, 1]) {
          const m = new V().lerpVectors(p, q, 0.5);
          const branch = new V().subVectors(q, p).normalize().multiplyScalar(0.5).add(new V(k * 0.5, 0, k * -0.6)).normalize();
          bristle(THREE, a, m, branch, 0.014 - i * 0.003, 0.0012);
        }
      }
      pivot.add(a.mesh(this.mat.chitin, { cast: false, receive: false }));
      this.head.add(pivot);
      this.antennae.push(pivot);
    }
  }

  _wings(THREE) {
    const shape = new THREE.Shape();
    shape.moveTo(0, 0);
    for (const [a, b, c, d, e, f] of WING.outline) shape.bezierCurveTo(a, b, c, d, e, f);
    const geometry = new THREE.ShapeGeometry(shape, 24);
    const position = geometry.attributes.position;
    const uv = geometry.attributes.uv;
    for (let i = 0; i < uv.count; i += 1) {
      uv.setXY(i, position.getX(i) / WING.length, (position.getY(i) - WING.yMin) / (WING.yMax - WING.yMin));
    }

    // The blur of a buzzing wing: the fan it sweeps, clear at the hinge,
    // denser at the tip and at the two ends of the stroke where it lingers.
    const steps = 20;
    const fan = new Float32Array((steps + 1) * 2 * 3);
    const colours = new Float32Array((steps + 1) * 2 * 4);
    const index = [];
    for (let i = 0; i <= steps; i += 1) {
      const e = BUZZ_LOW + ((BUZZ_HIGH - BUZZ_LOW) * i) / steps;
      const end = Math.pow(Math.abs((2 * i) / steps - 1), 3);
      for (let j = 0; j < 2; j += 1) {
        const r = j === 0 ? 0.05 : WING.length * 0.97;
        const o = (i * 2 + j) * 3;
        fan[o] = 0;
        fan[o + 1] = -Math.sin(e) * r;
        fan[o + 2] = Math.cos(e) * r;
        const c = (i * 2 + j) * 4;
        colours[c] = 1;
        colours[c + 1] = 1;
        colours[c + 2] = 1;
        colours[c + 3] = j === 0 ? 0.0 : 0.3 + 0.55 * end;
      }
      if (i < steps) {
        const a = i * 2;
        index.push(a, a + 1, a + 3, a, a + 3, a + 2);
      }
    }
    const blurGeometry = new THREE.BufferGeometry();
    blurGeometry.setAttribute('position', new THREE.BufferAttribute(fan, 3));
    blurGeometry.setAttribute('color', new THREE.BufferAttribute(colours, 4));
    blurGeometry.setIndex(index);

    this.wings = [];
    for (const s of [-1, 1]) {
      // hinge (splay, about y) > stroke (up and down) > the membrane, which
      // lies along +z with its leading edge rolled outward.
      const hinge = new THREE.Group();
      hinge.position.set(s * 0.066, 0.322, 0.058);
      const stroke = new THREE.Group();
      hinge.add(stroke);
      const mesh = new THREE.Mesh(geometry, this.mat.wing);
      mesh.rotation.set(0, -Math.PI / 2, s * (-Math.PI / 2 + WING_ROLL), 'ZYX');
      mesh.renderOrder = 2;
      stroke.add(mesh);
      const blur = new THREE.Mesh(blurGeometry, this.mat.blur);
      blur.visible = false;
      blur.renderOrder = 3;
      hinge.add(blur);
      hinge.userData = { side: s, stroke, blur, phase: s > 0 ? 0 : 0.4 };
      this.lean.add(hinge);
      this.wings.push(hinge);
    }
  }

  /** The four standing legs, added to the body batch: coxa, trochanter,
   *  femur, tibia with a spur, a five-part tarsus, claws and pulvilli, and
   *  a few spines. Then the body batch becomes its mesh. */
  _legs(THREE) {
    const V = THREE.Vector3;
    const P = this.paint;
    const batch = this._bodyBatch;
    const femurPaint = (c, t) => c.copy(P.legBase).lerp(P.leg, 0.15 + 0.55 * t);
    const tibiaPaint = (c, t) => c.copy(P.legBase).lerp(P.leg, 0.7 + 0.3 * t);
    const down = new V(0, -1, 0);

    const legs = [];
    for (const s of [-1, 1]) {
      // middle
      legs.push([s, [new V(s * 0.06, 0.13, -0.02), new V(s * 0.115, 0.112, -0.03), new V(s * 0.3, 0.25, -0.06), new V(s * 0.37, 0.02, -0.12), new V(s * 0.415, -0.012, -0.2)]]);
      // hind
      legs.push([s, [new V(s * 0.058, 0.13, 0.055), new V(s * 0.108, 0.112, 0.075), new V(s * 0.28, 0.24, 0.19), new V(s * 0.33, 0.02, 0.29), new V(s * 0.36, -0.012, 0.385)]]);
    }
    for (const [s, p] of legs) {
      segment(THREE, batch, p[0], p[1], 0.026, 0.02, { bulge: 0.1, radial: 10, color: FLY.legBase });
      batch.sphere(0.017, { x: p[1].x, y: p[1].y, z: p[1].z, color: FLY.legBase }, 8, 6);
      segment(THREE, batch, p[1], p[2], 0.017, 0.014, { bulge: 0.22, radial: 10, rows: 6, paint: femurPaint });
      batch.sphere(0.0135, { x: p[2].x, y: p[2].y, z: p[2].z, color: FLY.leg }, 8, 6);
      segment(THREE, batch, p[2], p[3], 0.012, 0.0105, { bulge: 0.08, radial: 9, rows: 6, paint: tibiaPaint });
      foot(THREE, batch, p[3], p[4], down);
      // Spines: on the femur's underside and down the tibia, pointing
      // toward the foot.
      for (const [a, b, n, length] of [
        [p[1], p[2], 3, 0.024],
        [p[2], p[3], 4, 0.02],
      ]) {
        const along = new V().subVectors(b, a).normalize();
        const out = new V(s, 0.2, 0).normalize();
        for (let i = 1; i <= n; i += 1) {
          const at = new V().lerpVectors(a, b, i / (n + 1)).addScaledVector(out, 0.012);
          bristle(THREE, batch, at, new V().copy(along).multiplyScalar(0.8).addScaledVector(out, 0.6).normalize(), length, 0.0022);
        }
      }
    }
    // The front legs' coxae, fixed to the body; the rest of each front leg
    // moves (_frontLegs).
    this.hips = [];
    for (const s of [-1, 1]) {
      const hip = new V(s * 0.085, 0.125, -0.15);
      segment(THREE, batch, new V(s * 0.045, 0.145, -0.095), hip, 0.026, 0.02, { bulge: 0.1, radial: 10, color: FLY.legBase });
      batch.sphere(0.017, { x: hip.x, y: hip.y, z: hip.z, color: FLY.legBase }, 8, 6);
      this.hips.push(hip);
    }

    this.body = batch.mesh(this.mat.chitin);
    this._bodyBatch = null;
    this.lean.add(this.body);
  }

  /** Each front leg is two meshes, the femur and the rest, posed every
   *  frame by a two-bone reach toward wherever the tip should be: a
   *  control on the pad, the other foot, an eye. */
  _frontLegs(THREE) {
    const V = THREE.Vector3;
    const P = this.paint;
    this.frontLegs = [];
    for (const s of [-1, 1]) {
      // Built along +y, the knee out along +x.
      const f = new Batch(THREE);
      segment(THREE, f, new V(0, 0, 0), new V(0, FEMUR, 0), 0.017, 0.0145, {
        bulge: 0.22,
        radial: 10,
        rows: 6,
        paint: (c, t) => c.copy(P.legBase).lerp(P.leg, 0.15 + 0.5 * t),
      });
      f.sphere(0.0138, { y: FEMUR, color: FLY.leg }, 10, 8);
      for (let i = 1; i <= 3; i += 1) {
        bristle(THREE, f, new V(0.012, (FEMUR * i) / 4, 0), new V(0.6, 0.8, 0).normalize(), 0.024, 0.0022);
        bristle(THREE, f, new V(-0.004, (FEMUR * i) / 4 + 0.01, 0.011), new V(0, 0.8, 0.6).normalize(), 0.018, 0.002);
      }
      const femur = f.mesh(this.mat.chitin);

      const l = new Batch(THREE);
      segment(THREE, l, new V(0, 0, 0), new V(0, TIBIA, 0), 0.0125, 0.0105, {
        bulge: 0.08,
        radial: 9,
        rows: 6,
        paint: (c, t) => c.copy(P.legBase).lerp(P.leg, 0.7 + 0.3 * t),
      });
      for (let i = 1; i <= 4; i += 1) {
        bristle(THREE, l, new V(0.01, (TIBIA * i) / 5, 0), new V(0.5, 0.86, 0).normalize(), 0.02, 0.002);
      }
      // The grooming comb on the inside of the tibia: a row of short stiff
      // bristles, the brush flies clean themselves with.
      for (let i = 0; i < 5; i += 1) {
        bristle(THREE, l, new V(0, TIBIA * (0.7 + i * 0.06), -s * 0.01), new V(0, 0.4, -s).normalize(), 0.011, 0.0016);
      }
      foot(THREE, l, new V(0, TIBIA, 0), new V(0, SHANK, 0), new V(-1, 0, 0));
      const lower = l.mesh(this.mat.chitin);

      this.lean.add(femur);
      this.lean.add(lower);
      const index = s < 0 ? 0 : 1;
      this.frontLegs.push({
        side: s,
        hip: this.hips[index],
        femur,
        lower,
        aim: new V(s * 0.08, 0.14, -0.38),
        pole: new V(s * 0.7, 0.7, 0.15).normalize(),
        target: new V(),
      });
    }
    this._padToLean = new THREE.Matrix4().copy(this.pad.matrix);
    this._update(0);
  }

  _controller(THREE) {
    this.pad = new THREE.Group();
    this.pad.position.set(0, 0.1, -0.38);
    this.pad.rotation.x = -0.38;
    this.pad.updateMatrix();
    this.lean.add(this.pad);

    const shell = new Batch(THREE);
    shell.box(PAD_W - 0.08, 0.045, PAD_D);
    for (const side of [-1, 1]) {
      shell.cyl(PAD_D / 2, PAD_D / 2, 0.045, 20, { x: side * (PAD_W / 2 - 0.04) });
    }
    this.pad.add(shell.mesh(this.mat.pad, { cast: true, receive: true }));

    const labels = new THREE.Mesh(
      new THREE.PlaneGeometry(PAD_W, PAD_D),
      new THREE.MeshStandardMaterial({
        map: padLabelTexture(THREE),
        transparent: true,
        roughness: 0.6,
      }),
    );
    labels.rotation.x = -Math.PI / 2;
    labels.position.y = 0.0235;
    this.pad.add(labels);

    // D-pad: a cross on a pivot, so it can tilt toward whichever way the fly
    // is walking.
    this.dpad = new THREE.Group();
    this.dpad.position.set(BUTTON_AT.dpad[0], 0.031, BUTTON_AT.dpad[1]);
    this.pad.add(this.dpad);
    this.dpadArms = {};
    const armMaterials = {};
    for (const name of DPAD_ARMS) {
      armMaterials[name] = new THREE.MeshStandardMaterial({
        color: FLY.padDark,
        roughness: 0.5,
        emissive: POOL_HEX[name],
        emissiveIntensity: 0.0,
      });
    }
    const arms = {
      UP: [0, -0.028, 0.03, 0.055],
      DOWN: [0, 0.028, 0.03, 0.055],
      LEFT: [-0.028, 0, 0.055, 0.03],
      RIGHT: [0.028, 0, 0.055, 0.03],
    };
    for (const [name, [x, z, w, d]] of Object.entries(arms)) {
      const arm = new THREE.Mesh(new THREE.BoxGeometry(w, 0.018, d), armMaterials[name]);
      arm.position.set(x, 0, z);
      arm.castShadow = true;
      this.dpad.add(arm);
      this.dpadArms[name] = arm;
    }
    const hub = new THREE.Mesh(new THREE.CylinderGeometry(0.016, 0.016, 0.019, 14), this.mat.padDark);
    this.dpad.add(hub);
    this.dpadMaterials = armMaterials;

    // A, B, START.
    this.buttons = {};
    const round = (name, color, radius) => {
      const material = new THREE.MeshStandardMaterial({
        color,
        roughness: 0.45,
        emissive: POOL_HEX[name],
        emissiveIntensity: 0.0,
      });
      const mesh = new THREE.Mesh(new THREE.CylinderGeometry(radius, radius, 0.02, 18), material);
      mesh.position.set(BUTTON_AT[name][0], 0.031, BUTTON_AT[name][1]);
      mesh.castShadow = true;
      this.pad.add(mesh);
      this.buttons[name] = mesh;
    };
    round('A', 0xc0394b, 0.023);
    round('B', 0xd99a2b, 0.023);

    const startMaterial = new THREE.MeshStandardMaterial({
      color: 0x6f7480,
      roughness: 0.5,
      emissive: POOL_HEX.START,
      emissiveIntensity: 0.0,
    });
    const start = new THREE.Mesh(new THREE.BoxGeometry(0.05, 0.014, 0.017), startMaterial);
    start.position.set(BUTTON_AT.START[0], 0.029, BUTTON_AT.START[1]);
    start.rotation.y = -0.35;
    start.castShadow = true;
    this.pad.add(start);
    this.buttons.START = start;
  }

  /** The controller's cable, from the top edge of the pad down to the rug
   *  at CABLE_FLOOR, where the room's half of it (props.js) carries on to
   *  the console. It hangs from the pad, so it moves when the fly does. */
  _cable(THREE) {
    this.group.updateMatrixWorld(true);
    const local = (x, y, z) => this.pad.worldToLocal(new THREE.Vector3(x, y, z));
    const [fx, fy, fz] = CABLE_FLOOR;
    const curve = new THREE.CatmullRomCurve3(
      [
        new THREE.Vector3(0.0, 0.0, -PAD_D / 2 + 0.005),
        new THREE.Vector3(0.0, -0.01, -PAD_D / 2 - 0.04),
        local(0.02, 0.4, 0.9),
        local(fx - 0.02, 0.1, fz + 0.03),
        local(fx, fy, fz),
      ],
      false,
      'centripetal',
    );
    const cable = new THREE.Mesh(
      new THREE.TubeGeometry(curve, 40, 0.009, 5, false),
      new THREE.MeshStandardMaterial({ color: hex(RETRO.cable), roughness: 0.45 }),
    );
    cable.castShadow = true;
    this.pad.add(cable);
  }

  // -- driving ----------------------------------------------------------

  /** One press event from the feed. `panic` presses look the same but are
   *  reported separately in the overlay, because the fly did not choose them. */
  press(pool) {
    if (this.pressTimer[pool] !== undefined) this.pressTimer[pool] = PRESS_SECONDS;
    if (pool === 'START') this.groom = 1.0;
  }

  setHeld(pressed) {
    this.held = new Set(pressed || []);
  }

  startle() {
    this.panic = 1.0;
    this.hopTimer = 0.46;
  }

  /** A milestone landed: a short gold pulse in the head. */
  milestonePulse() {
    this.gold = GOLD_SECONDS;
  }

  update(dt, signals) {
    this.time += dt;

    for (const name of POOLS) {
      this.pressTimer[name] = Math.max(0, this.pressTimer[name] - dt);
      const wanted = this.held.has(name) || this.pressTimer[name] > 0 ? 1 : 0;
      this.pressLevel[name] = approach(this.pressLevel[name], wanted, wanted ? 42 : 13, dt);
    }

    this.firing = approach(this.firing, signals.firing, 7, dt);
    this.dope = approach(this.dope, clamp(signals.dopamine / 2.0, -1, 1), 5, dt);
    this.flash = Math.max(0, this.flash - dt * 2.2);
    if (Math.abs(signals.dopamine) > 0.8) this.flash = 1;
    this.panic = Math.max(0, this.panic - dt * 1.4);
    this.battle = approach(this.battle, signals.inBattle ? 1 : 0, 3.5, dt);
    this.groom = Math.max(0, this.groom - dt / GROOM_SECONDS);
    this.gold = Math.max(0, this.gold - dt);
    this.screen = approach(this.screen, signals.screen ?? 0.35, 6, dt);

    this._update(dt);
  }

  _update(dt) {
    const t = this.time;
    this._idle(dt);
    this._pose(dt, t);
    this._controls();
    this._reach(dt, t);
    this._glow();
  }

  /** The little things that mean nothing: when to shift weight, when an
   *  antenna twitches, when the wings shiver. */
  _idle(dt) {
    this.nextShift -= dt;
    if (this.nextShift <= 0) {
      this.nextShift = 5 + Math.random() * 6;
      this.shiftTarget = Math.random() < 0.3 ? 0 : (Math.random() < 0.5 ? -1 : 1) * (0.5 + 0.5 * Math.random());
    }
    this.shift = approach(this.shift, this.shiftTarget, 1.6, dt);

    this.nextAntennaTwitch -= dt;
    if (this.nextAntennaTwitch <= 0) {
      this.nextAntennaTwitch = 2.5 + Math.random() * 4;
      this.antennaTwitch[Math.random() < 0.5 ? 0 : 1] = 0.35;
    }
    this.antennaTwitch[0] = Math.max(0, this.antennaTwitch[0] - dt);
    this.antennaTwitch[1] = Math.max(0, this.antennaTwitch[1] - dt);

    this.twitch = Math.max(0, this.twitch - dt);
    this.nextTwitch -= dt;
    if (this.nextTwitch <= 0) {
      this.nextTwitch = 4 + Math.random() * 6;
      this.twitch = 0.3;
    }
  }

  _pose(dt, t) {
    const battle = this.battle;
    const groomPhase = this.groom > 0 ? 1 - this.groom : 1;
    const grooming = this.groom > 0 ? smooth(0.06, 0.14, groomPhase) * (1 - smooth(0.86, 0.97, groomPhase)) : 0;

    // Breathing: the abdomen pumps from its waist. A battle lifts it.
    const breath = Math.sin(t * 2.6);
    this.abdomen.scale.set(1 + 0.022 * breath, 1 + 0.035 * breath, 1 + 0.012 * breath);
    this.abdomen.rotation.x = approach(this.abdomen.rotation.x, -0.12 * battle + 0.012 * breath, 5, dt);

    // The startle hop: up and back down over less than half a second.
    if (this.hopTimer > 0) {
      this.hopTimer = Math.max(0, this.hopTimer - dt);
      const phase = 1 - this.hopTimer / 0.46;
      this.bob.position.y = 0.16 * Math.sin(phase * Math.PI);
      this.bob.rotation.z = 0.08 * Math.sin(phase * Math.PI * 2);
    } else {
      this.bob.position.y = approach(this.bob.position.y, 0, 12, dt);
      this.bob.rotation.z = approach(this.bob.rotation.z, 0, 12, dt);
    }

    // Leaning in during a battle: scoot forward and tip toward the TV. At
    // rest, a small sway and the occasional shift of weight to one side.
    this.lean.rotation.x = approach(this.lean.rotation.x, -0.17 * battle, 4, dt);
    this.lean.position.z = approach(this.lean.position.z, -0.035 * battle, 4, dt);
    this.lean.rotation.y = 0.03 * Math.sin(t * 0.7);
    this.lean.rotation.z = 0.035 * this.shift;
    this.lean.position.x = 0.012 * this.shift;

    // The head follows what is happening on screen: sideways with the turning
    // pools, up and down with the walking pair, plus a slow wander. In a
    // battle it tips back up to keep its eyes on the TV; grooming tips it
    // down toward the legs; a weight shift cocks it the other way.
    const wipe = this.groom > 0 ? smooth(0.55, 0.62, groomPhase) * grooming : 0;
    const yaw = (this.pressLevel.RIGHT - this.pressLevel.LEFT) * 0.28 + 0.07 * Math.sin(t * 0.43);
    const pitch =
      (this.pressLevel.DOWN - this.pressLevel.UP) * 0.14 +
      0.03 * Math.sin(t * 0.31) +
      0.14 * battle -
      0.12 * grooming;
    const roll = -0.1 * this.shift + wipe * 0.12 * Math.sin(t * 9);
    this.headYaw = approach(this.headYaw, yaw * (1 - grooming), 6, dt);
    this.headPitch = approach(this.headPitch, pitch, 6, dt);
    this.headRoll = approach(this.headRoll, roll, 5, dt);
    this.head.rotation.set(this.headPitch, this.headYaw, this.headRoll);
    this.head.updateMatrix();

    // Antennae: perked up and spread on good news, drooping on bad, and
    // swept back in a panic. One twitches now and then.
    const perk = this.dope > 0 ? this.dope : 0;
    const droop = this.dope < 0 ? -this.dope : 0;
    for (let i = 0; i < 2; i += 1) {
      const pivot = this.antennae[i];
      const s = pivot.userData.side;
      const twitch = this.antennaTwitch[i] > 0 ? Math.sin(this.antennaTwitch[i] * 60) * 0.12 : 0;
      pivot.rotation.x = 0.5 * perk - 0.7 * droop - 0.05 + 0.4 * this.panic + twitch + 0.05 * battle;
      pivot.rotation.z = -s * (0.25 * perk + 0.45 * droop) + s * 0.08;
      pivot.rotation.y = s * 0.05 * Math.sin(t * 1.3 + s);
    }

    // Wings. At rest they lie folded over the abdomen and shiver now and
    // then; a panic spreads them and buzzes them to a blur.
    const buzz = this.panic;
    const open = smooth(0, 0.25, buzz);
    const twitch = this.twitch > 0 ? 1 : 0;
    const speed = 11 + 95 * buzz + 24 * twitch;
    const amplitude = 0.02 + 0.85 * open + 0.12 * twitch;
    const centre = WING_DROP + (0.5 * (BUZZ_LOW + BUZZ_HIGH) - WING_DROP) * open - 0.06 * battle;
    for (const hinge of this.wings) {
      const { side, stroke, blur, phase } = hinge.userData;
      hinge.rotation.y = side * (WING_SPLAY + (BUZZ_SPLAY - WING_SPLAY) * open + 0.1 * twitch);
      stroke.rotation.x = centre + amplitude * Math.sin(t * speed + phase * buzz);
      blur.visible = buzz > 0.04;
      this.mat.blur.opacity = 0.9 * open * buzz;
    }
    this.mat.wing.opacity = 1 - 0.45 * open;
  }

  _controls() {
    const level = this.pressLevel;
    const vertical = Math.max(level.UP, level.DOWN);
    const horizontal = Math.max(level.LEFT, level.RIGHT);
    const anyDirection = Math.max(vertical, horizontal);

    this.dpad.rotation.x = -0.3 * level.UP + 0.3 * level.DOWN;
    this.dpad.rotation.z = 0.3 * level.LEFT - 0.3 * level.RIGHT;
    this.dpad.position.y = 0.031 - 0.006 * anyDirection;
    for (const name of DPAD_ARMS) {
      this.dpadMaterials[name].emissiveIntensity = 0.05 + 2.4 * level[name];
    }

    for (const name of ['A', 'B', 'START']) {
      const mesh = this.buttons[name];
      const base = name === 'START' ? 0.029 : 0.031;
      mesh.position.y = base - 0.013 * level[name];
      mesh.material.emissiveIntensity = 0.05 + 2.4 * level[name];
    }
  }

  /** Where each front foot should be, and the two-bone reach that gets it
   *  there. The left foot works the d-pad, the right one A, B and START:
   *  each hovers over its side of the pad and, on a press, goes to that
   *  very control and pushes it down. A grooming bout takes both. */
  _reach(dt, t) {
    const level = this.pressLevel;
    const groomPhase = this.groom > 0 ? 1 - this.groom : 1;
    const grooming = this.groom > 0 ? smooth(0.06, 0.14, groomPhase) * (1 - smooth(0.86, 0.97, groomPhase)) : 0;
    const wiping = this.groom > 0 ? smooth(0.55, 0.62, groomPhase) : 0;

    for (const leg of this.frontLegs) {
      const s = leg.side;
      const target = leg.target;

      // On the pad, in the pad's own frame.
      if (s < 0) {
        let best = 'UP';
        for (const name of DPAD_ARMS) if (level[name] > level[best]) best = name;
        const l = level[best];
        const reach = clamp(l * 2.5, 0, 1);
        target.set(
          BUTTON_AT.dpad[0] + ARM_AT[best][0] * 0.85 * reach,
          BUTTON_TOP.dpad + 0.03 - 0.042 * l,
          BUTTON_AT.dpad[1] + ARM_AT[best][1] * 0.85 * reach,
        );
      } else {
        let best = 'A';
        if (level.B > level[best]) best = 'B';
        if (level.START > level[best]) best = 'START';
        const l = level[best];
        const reach = clamp(l * 2.5, 0, 1);
        const restX = 0.5 * (BUTTON_AT.A[0] + BUTTON_AT.B[0]);
        const restZ = 0.5 * (BUTTON_AT.A[1] + BUTTON_AT.B[1]);
        target.set(
          restX + (BUTTON_AT[best][0] - restX) * reach,
          BUTTON_TOP[best] + 0.03 - 0.042 * l,
          restZ + (BUTTON_AT[best][1] - restZ) * reach,
        );
      }
      target.applyMatrix4(this._padToLean);

      // Grooming: rub the feet together in front of the face, then wipe
      // them down over the eyes, twice.
      if (grooming > 0) {
        const rub = Math.sin(t * 24);
        this._v.set(s * 0.013, 0.2 + 0.008 * rub * s, -0.372 + s * 0.028 * rub);
        if (wiping > 0) {
          const stroke = ((groomPhase - 0.58) / 0.3) * 2;
          const f = stroke - Math.floor(stroke);
          const el = 0.75 - 1.35 * f;
          this._d.set(s * 0.5 * Math.cos(el), Math.sin(el), -0.86 * Math.cos(el));
          this._d.normalize();
          this._perp.set(s * 0.074 + this._d.x * 0.1, 0.006 + this._d.y * 0.124, -0.02 + this._d.z * 0.114);
          this._perp.applyMatrix4(this.head.matrix);
          this._v.lerp(this._perp, wiping);
        }
        target.lerp(this._v, grooming);
      }

      leg.aim.x = approach(leg.aim.x, target.x, 30, dt);
      leg.aim.y = approach(leg.aim.y, target.y, 30, dt);
      leg.aim.z = approach(leg.aim.z, target.z, 30, dt);
      if (dt === 0) leg.aim.copy(target);

      // Elbows up and out on the pad, further out when grooming.
      leg.pole.set(s * (0.7 + 0.25 * grooming), 0.7 - 0.35 * grooming, 0.15 + 0.1 * grooming).normalize();
      this._solve(leg);
    }
  }

  /** Two-bone reach: hip to knee is the femur, knee to toe the rest. The
   *  knee goes toward the pole side. */
  _solve(leg) {
    const d = this._d.subVectors(leg.aim, leg.hip);
    const dist = clamp(d.length(), 0.08, (FEMUR + SHANK) * 0.995);
    d.normalize();
    const a = (FEMUR * FEMUR - SHANK * SHANK + dist * dist) / (2 * dist);
    const h = Math.sqrt(Math.max(0, FEMUR * FEMUR - a * a));
    const perp = this._perp.copy(leg.pole).addScaledVector(d, -leg.pole.dot(d)).normalize();
    const knee = this._knee.copy(leg.hip).addScaledVector(d, a).addScaledVector(perp, h);
    const tip = this._tip.copy(leg.hip).addScaledVector(d, dist);
    this._orient(leg.femur, leg.hip, knee, leg.pole);
    this._orient(leg.lower, knee, tip, leg.pole);
  }

  _orient(mesh, from, to, pole) {
    const y = this._y.subVectors(to, from).normalize();
    const x = this._x.copy(pole).addScaledVector(y, -pole.dot(y)).normalize();
    const z = this._z.crossVectors(x, y);
    this._m.makeBasis(x, y, z);
    mesh.quaternion.setFromRotationMatrix(this._m);
    mesh.position.copy(from);
  }

  _glow() {
    // Firing rate lives around 8 to 10 percent, so 0.20 is a full head.
    const level = clamp(this.firing / 0.2, 0, 1.4);
    const pulse = 1 + 0.12 * Math.sin(this.time * 9) * level + 0.35 * this.flash;

    // Gold when the last thing that happened beat the estimate, cold blue when
    // it fell short, warm amber in between.
    const warm = this.dope >= 0 ? this.dope : 0;
    const cold = this.dope < 0 ? -this.dope : 0;
    const r = 1.0 - 0.68 * cold;
    const g = 0.82 - 0.2 * cold + 0.1 * warm;
    const b = 0.48 - 0.4 * warm + 0.55 * cold;
    const color = this.glowColor;
    color.setRGB(clamp(r, 0.2, 1), clamp(g, 0.2, 1), clamp(b, 0.1, 1.4));

    let light = 0.03 + 0.18 * level + 0.7 * this.flash;
    let crown = 0.03 + 0.4 * level * pulse + 0.9 * this.flash;

    // The milestone pulse wins over everything above while it lasts: three
    // gold beats that fade out, in the crown and its light.
    if (this.gold > 0) {
      const phase = GOLD_SECONDS - this.gold;
      const beat = 0.5 + 0.5 * Math.cos((phase * 3 * Math.PI * 2) / GOLD_SECONDS);
      const k = (this.gold / GOLD_SECONDS) * (0.55 + 0.45 * beat);
      color.setRGB(color.r + (GOLD.r - color.r) * k, color.g + (GOLD.g - color.g) * k, color.b + (GOLD.b - color.b) * k);
      light += 2.0 * k;
      crown += 2.0 * k;
    }

    this.brainLight.color.copy(color);
    this.brainLight.intensity = light;
    this.mat.head.emissive.copy(color);
    this.mat.head.emissiveIntensity = crown;
    // The eyes are lit by the room and the TV only: no light of their own.
    this.mat.eyes.emissiveIntensity = 0;

    // The TV lights the room, so it lights the reflections too.
    const screen = clamp(this.screen, 0, 1);
    this.mat.chitin.envMapIntensity = 0.3 + 1.0 * screen;
    this.mat.head.envMapIntensity = 0.3 + 1.0 * screen;
    this.mat.eyes.envMapIntensity = 0.6 + 1.8 * screen;
    this.mat.wing.envMapIntensity = 0.5 + 1.4 * screen;
  }
}
