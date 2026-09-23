/**
 * The fly, and everything its body says about the brain.
 *
 * A Drosophila caricature sitting upright on the cushion facing the TV: big
 * red compound eyes, tan thorax, a striped abdomen, two translucent wings, six
 * segmented legs, antennae, a proboscis, and a controller held in the two
 * front legs.
 *
 * What each part means, in one line each, because this is the whole point of
 * the scene:
 *
 *   controller     the button the brain is pressing right now: the control
 *                  goes down, lights up in that pool's colour, and the front
 *                  leg on that side pokes it. The d-pad tilts the way the
 *                  fly is walking.
 *   head glow      the firing rate of the whole spiking network.
 *   glow colour    dopamine: gold when the last thing that happened was
 *                  better than expected, cold blue when it was worse.
 *   antennae       the same signal again, as posture: perked up or drooping.
 *   wings          buzzing means the anti-stuck reflex just fired.
 *   a hop          the same reflex: the fly startles off the cushion.
 *   leaning in     the game is in a battle.
 *   front legs rubbing together   START was pressed. Flies groom.
 *
 * Nothing here is downloaded. Every shape is a three.js primitive, a lathe, or
 * a hand-drawn `Shape` for the wings.
 */

import { FLY, POOL_HEX, POOLS, approach, clamp } from './theme.js';

const PRESS_SECONDS = 0.17;
const PAD_W = 0.3;
const PAD_D = 0.16;

const BUTTON_AT = {
  dpad: [-0.085, 0.0],
  B: [0.052, 0.012],
  A: [0.102, -0.016],
  START: [0.005, 0.05],
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

function limb(THREE, material, from, to, radiusFrom, radiusTo) {
  const direction = new THREE.Vector3().subVectors(to, from);
  const length = direction.length();
  const mesh = new THREE.Mesh(new THREE.CylinderGeometry(radiusTo, radiusFrom, length, 8), material);
  mesh.position.copy(from).addScaledVector(direction, 0.5);
  mesh.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), direction.normalize());
  mesh.castShadow = true;
  return mesh;
}

function leg(THREE, material, points, radii) {
  const group = new THREE.Group();
  for (let i = 0; i < points.length - 1; i += 1) {
    group.add(limb(THREE, material, points[i], points[i + 1], radii[i], radii[i + 1]));
    const joint = new THREE.Mesh(new THREE.SphereGeometry(radii[i + 1] * 1.5, 8, 6), material);
    joint.position.copy(points[i + 1]);
    group.add(joint);
  }
  return group;
}

function wingGeometry(THREE) {
  const shape = new THREE.Shape();
  shape.moveTo(0, 0);
  shape.bezierCurveTo(0.09, 0.075, 0.3, 0.085, 0.46, 0.02);
  shape.bezierCurveTo(0.33, -0.05, 0.13, -0.055, 0, 0);
  return new THREE.ShapeGeometry(shape, 18);
}

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
    this.twitch = 0;
    this.nextTwitch = 3 + Math.random() * 5;
    this.headYaw = 0;
    this.headPitch = 0;
    this.targetYaw = 0;
    this.targetPitch = 0;

    this.group = new THREE.Group();
    this.group.position.set(0, seatHeight, 1.42);
    this.bob = new THREE.Group();
    this.lean = new THREE.Group();
    this.group.add(this.bob);
    this.bob.add(this.lean);

    this._materials(THREE);
    this._body(THREE);
    this._head(THREE);
    this._wings(THREE);
    this._legs(THREE);
    this._controller(THREE);
    scene.add(this.group);
  }

  // -- construction -----------------------------------------------------

  _materials(THREE) {
    this.mat = {
      thorax: new THREE.MeshStandardMaterial({ color: FLY.thorax, roughness: 0.85 }),
      thoraxDark: new THREE.MeshStandardMaterial({ color: FLY.thoraxDark, roughness: 0.8 }),
      head: new THREE.MeshStandardMaterial({
        color: FLY.head,
        roughness: 0.8,
        emissive: 0x120a04,
        emissiveIntensity: 1,
      }),
      eye: new THREE.MeshStandardMaterial({
        color: FLY.eye,
        roughness: 0.35,
        metalness: 0.1,
        emissive: 0x4a0d08,
        emissiveIntensity: 0.55,
        flatShading: true,
      }),
      stripeLight: new THREE.MeshStandardMaterial({ color: FLY.stripeLight, roughness: 0.85 }),
      stripeDark: new THREE.MeshStandardMaterial({ color: FLY.stripeDark, roughness: 0.85 }),
      leg: new THREE.MeshStandardMaterial({ color: FLY.leg, roughness: 0.7 }),
      wing: new THREE.MeshStandardMaterial({
        color: FLY.wing,
        roughness: 0.15,
        metalness: 0.0,
        transparent: true,
        opacity: 0.3,
        side: THREE.DoubleSide,
        emissive: 0x9fd4ff,
        emissiveIntensity: 0.12,
      }),
      pad: new THREE.MeshStandardMaterial({ color: FLY.pad, roughness: 0.55 }),
      padDark: new THREE.MeshStandardMaterial({ color: FLY.padDark, roughness: 0.5 }),
    };
  }

  _body(THREE) {
    this.torso = new THREE.Group();
    this.lean.add(this.torso);

    const thorax = new THREE.Mesh(new THREE.SphereGeometry(0.17, 26, 20), this.mat.thorax);
    thorax.scale.set(1.0, 0.95, 1.12);
    thorax.position.set(0, 0.22, -0.02);
    thorax.castShadow = true;
    thorax.receiveShadow = true;
    this.torso.add(thorax);

    const scutellum = new THREE.Mesh(new THREE.SphereGeometry(0.115, 18, 14), this.mat.thoraxDark);
    scutellum.scale.set(1.0, 0.6, 0.8);
    scutellum.position.set(0, 0.29, 0.06);
    this.torso.add(scutellum);

    // Abdomen: four tapering segments, alternating light and dark. That is
    // what the stripes are; a band wrapped round an ellipsoid would fight the
    // taper at every joint.
    const segments = [
      [0.1, 0.16, 0.155, this.mat.stripeLight],
      [0.2, 0.152, 0.145, this.mat.stripeDark],
      [0.3, 0.14, 0.12, this.mat.stripeLight],
      [0.385, 0.128, 0.085, this.mat.stripeDark],
    ];
    this.abdomen = new THREE.Group();
    for (const [z, y, radius, material] of segments) {
      const part = new THREE.Mesh(new THREE.SphereGeometry(radius, 22, 16), material);
      part.scale.set(1.0, 0.92, 0.78);
      part.position.set(0, y, z);
      part.castShadow = true;
      part.receiveShadow = true;
      this.abdomen.add(part);
    }
    this.lean.add(this.abdomen);
  }

  _head(THREE) {
    this.head = new THREE.Group();
    this.head.position.set(0, 0.325, -0.14);
    this.lean.add(this.head);

    const skull = new THREE.Mesh(new THREE.SphereGeometry(0.135, 24, 18), this.mat.head);
    skull.scale.set(1.0, 0.95, 0.85);
    skull.castShadow = true;
    this.head.add(skull);

    for (const side of [-1, 1]) {
      const eye = new THREE.Mesh(new THREE.SphereGeometry(0.095, 12, 9), this.mat.eye);
      eye.scale.set(0.92, 1.15, 1.0);
      eye.position.set(side * 0.085, 0.015, -0.055);
      eye.castShadow = true;
      this.head.add(eye);
      const highlight = new THREE.Mesh(
        new THREE.SphereGeometry(0.02, 8, 6),
        new THREE.MeshBasicMaterial({ color: 0xffd9d0, toneMapped: false }),
      );
      highlight.position.set(side * 0.105, 0.06, -0.105);
      this.head.add(highlight);
    }

    // The brain: an emissive core inside the head. Brightness is the firing
    // rate, colour is dopamine.
    this.brain = new THREE.Mesh(
      new THREE.SphereGeometry(0.085, 18, 14),
      new THREE.MeshBasicMaterial({
        color: 0xffd27a,
        transparent: true,
        opacity: 0.35,
        blending: THREE.AdditiveBlending,
        depthWrite: false,
        toneMapped: false,
      }),
    );
    this.brain.position.set(0, 0.03, 0.01);
    this.head.add(this.brain);
    this.brainLight = new THREE.PointLight(0xffd27a, 0.6, 1.2, 2);
    this.brainLight.position.copy(this.brain.position);
    this.head.add(this.brainLight);

    this.antennae = new THREE.Group();
    this.antennae.position.set(0, 0.06, -0.08);
    this.head.add(this.antennae);
    for (const side of [-1, 1]) {
      const stalk = limb(
        THREE,
        this.mat.leg,
        new THREE.Vector3(side * 0.03, 0, 0),
        new THREE.Vector3(side * 0.07, 0.075, -0.05),
        0.011,
        0.009,
      );
      this.antennae.add(stalk);
      const club = new THREE.Mesh(new THREE.SphereGeometry(0.028, 12, 9), this.mat.thoraxDark);
      club.scale.set(0.8, 1.2, 0.8);
      club.position.set(side * 0.075, 0.09, -0.06);
      this.antennae.add(club);
    }

    const proboscis = new THREE.Mesh(new THREE.ConeGeometry(0.038, 0.09, 12), this.mat.thoraxDark);
    proboscis.position.set(0, -0.1, -0.06);
    proboscis.rotation.x = -2.5;
    this.head.add(proboscis);
  }

  _wings(THREE) {
    const geometry = wingGeometry(THREE);
    this.wings = [];
    for (const side of [-1, 1]) {
      const pivot = new THREE.Group();
      pivot.position.set(side * 0.07, 0.33, 0.03);
      pivot.rotation.y = -Math.PI / 2 + side * 0.34;
      const mesh = new THREE.Mesh(geometry, this.mat.wing);
      mesh.rotation.x = -Math.PI / 2;
      pivot.add(mesh);
      pivot.userData.tilt = -0.2;
      this.lean.add(pivot);
      this.wings.push(pivot);
    }
  }

  _legs(THREE) {
    const V = this.THREE.Vector3;
    this.frontLegs = [];
    for (const side of [-1, 1]) {
      const hind = leg(
        THREE,
        this.mat.leg,
        [
          new V(side * 0.12, 0.18, 0.12),
          new V(side * 0.31, 0.06, 0.2),
          new V(side * 0.27, -0.01, 0.0),
          new V(side * 0.24, -0.02, -0.08),
        ],
        [0.022, 0.018, 0.013, 0.009],
      );
      this.lean.add(hind);

      const middle = leg(
        THREE,
        this.mat.leg,
        [
          new V(side * 0.14, 0.19, 0.0),
          new V(side * 0.34, 0.09, 0.02),
          new V(side * 0.31, -0.02, -0.14),
          new V(side * 0.28, -0.02, -0.24),
        ],
        [0.022, 0.018, 0.013, 0.009],
      );
      this.lean.add(middle);

      const front = leg(
        THREE,
        this.mat.leg,
        [
          new V(side * 0.12, 0.25, -0.09),
          new V(side * 0.24, 0.15, -0.2),
          new V(side * 0.15, 0.11, -0.31),
          new V(side * 0.075, 0.1, -0.37),
        ],
        [0.021, 0.017, 0.012, 0.008],
      );
      const pivot = new THREE.Group();
      pivot.add(front);
      pivot.userData.side = side;
      this.lean.add(pivot);
      this.frontLegs.push(pivot);
    }
  }

  _controller(THREE) {
    this.pad = new THREE.Group();
    this.pad.position.set(0, 0.1, -0.38);
    this.pad.rotation.x = -0.38;
    this.lean.add(this.pad);

    const body = new THREE.Mesh(new THREE.BoxGeometry(PAD_W - 0.08, 0.045, PAD_D), this.mat.pad);
    body.castShadow = true;
    this.pad.add(body);
    for (const side of [-1, 1]) {
      const end = new THREE.Mesh(new THREE.CylinderGeometry(PAD_D / 2, PAD_D / 2, 0.045, 20), this.mat.pad);
      end.position.set(side * (PAD_W / 2 - 0.04), 0, 0);
      end.castShadow = true;
      this.pad.add(end);
    }

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
    for (const name of ['UP', 'DOWN', 'LEFT', 'RIGHT']) {
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

  update(dt, signals) {
    this.time += dt;
    const t = this.time;

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
    this.groom = Math.max(0, this.groom - dt * 1.1);

    this._pose(dt, t);
    this._controls(dt);
    this._glow(dt);
  }

  _pose(dt, t) {
    // Breathing.
    const breath = 1 + 0.02 * Math.sin(t * 2.6);
    this.torso.scale.set(1, breath, 1);
    this.abdomen.scale.set(1, 2 - breath, 1);

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

    // Leaning in during a battle, plus a small idle sway.
    this.lean.rotation.x = approach(this.lean.rotation.x, -0.17 * this.battle, 4, dt);
    this.lean.rotation.y = 0.03 * Math.sin(t * 0.7);

    // The head follows what is happening on screen: sideways with the turning
    // pools, up and down with the walking pair, plus a slow wander.
    const yaw = (this.pressLevel.RIGHT - this.pressLevel.LEFT) * 0.28 + 0.07 * Math.sin(t * 0.43);
    const pitch = (this.pressLevel.DOWN - this.pressLevel.UP) * 0.14 + 0.03 * Math.sin(t * 0.31);
    this.headYaw = approach(this.headYaw, yaw, 6, dt);
    this.headPitch = approach(this.headPitch, pitch, 6, dt);
    this.head.rotation.set(this.headPitch, this.headYaw, 0);

    // Antennae: perked on good news, drooping on bad.
    this.antennae.rotation.x = 0.45 * this.dope - 0.05;

    // Wings. Idle is a twitch every few seconds; a panic is a real buzz.
    this.twitch = Math.max(0, this.twitch - dt);
    this.nextTwitch -= dt;
    if (this.nextTwitch <= 0) {
      this.nextTwitch = 4 + Math.random() * 6;
      this.twitch = 0.3;
    }
    const buzz = this.panic > 0 ? this.panic : 0;
    const amplitude = 0.03 + 0.55 * buzz + 0.16 * (this.twitch > 0 ? 1 : 0);
    const speed = 9 + 95 * buzz + 24 * (this.twitch > 0 ? 1 : 0);
    for (const wing of this.wings) {
      wing.rotation.x = wing.userData.tilt + amplitude * Math.sin(t * speed);
    }
    this.mat.wing.opacity = 0.3 - 0.12 * buzz;
  }

  _controls(dt) {
    const level = this.pressLevel;
    const vertical = Math.max(level.UP, level.DOWN);
    const horizontal = Math.max(level.LEFT, level.RIGHT);
    const anyDirection = Math.max(vertical, horizontal);

    this.dpad.rotation.x = -0.3 * level.UP + 0.3 * level.DOWN;
    this.dpad.rotation.z = 0.3 * level.LEFT - 0.3 * level.RIGHT;
    this.dpad.position.y = 0.031 - 0.006 * anyDirection;
    for (const name of ['UP', 'DOWN', 'LEFT', 'RIGHT']) {
      this.dpadMaterials[name].emissiveIntensity = 0.05 + 2.4 * level[name];
    }

    for (const name of ['A', 'B', 'START']) {
      const mesh = this.buttons[name];
      const base = name === 'START' ? 0.029 : 0.031;
      mesh.position.y = base - 0.013 * level[name];
      mesh.material.emissiveIntensity = 0.05 + 2.4 * level[name];
    }

    // The front legs. Left one works the d-pad, right one works A, B and
    // START, and on a press its tip pokes the control. When START fires the
    // fly stops holding the pad and rubs its front legs together instead.
    const groom = this.groom;
    for (const pivot of this.frontLegs) {
      const side = pivot.userData.side;
      const poke = side < 0 ? anyDirection : Math.max(level.A, level.B, level.START);
      const wobble = groom > 0 ? Math.sin(this.time * 26) * 0.035 : 0;
      const targetX = groom > 0 ? side * (-0.05 + wobble) : 0;
      const targetY = groom > 0 ? 0.075 : 0;
      const targetZ = groom > 0 ? 0.055 : -0.024 * poke;
      pivot.position.x = approach(pivot.position.x, targetX, 9, dt);
      pivot.position.y = approach(pivot.position.y, targetY, 9, dt);
      pivot.position.z = approach(pivot.position.z, targetZ, 22, dt);
    }
  }

  _glow(dt) {
    // Firing rate lives around 8 to 10 percent, so 0.20 is a full head.
    const level = clamp(this.firing / 0.2, 0, 1.4);
    const pulse = 1 + 0.12 * Math.sin(this.time * 9) * level + 0.35 * this.flash;
    this.brain.scale.setScalar(0.85 + 0.35 * level * pulse);
    this.brain.material.opacity = clamp(0.16 + 0.5 * level + 0.35 * this.flash, 0, 0.95);

    // Gold when the last thing that happened beat the estimate, cold blue when
    // it fell short, warm amber in between.
    const warm = this.dope >= 0 ? this.dope : 0;
    const cold = this.dope < 0 ? -this.dope : 0;
    const r = 1.0;
    const g = 0.82 - 0.35 * cold + 0.1 * warm;
    const b = 0.48 - 0.4 * warm + 0.5 * cold;
    this.brain.material.color.setRGB(clamp(r - 0.5 * cold, 0.2, 1), clamp(g, 0.2, 1), clamp(b, 0.1, 1.4));
    this.brainLight.color.copy(this.brain.material.color);
    this.brainLight.intensity = 0.25 + 1.6 * level + 2.2 * this.flash;
    this.mat.eye.emissiveIntensity = 0.45 + 0.5 * level;
    this.mat.head.emissiveIntensity = 1 + 2.5 * this.flash;
  }
}
