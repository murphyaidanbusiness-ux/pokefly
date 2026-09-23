/**
 * Puts the scene together and drives it from the feed.
 *
 * Every number the browser draws comes from a message; nothing here simulates
 * anything. The render loop runs at the display's rate and the feed arrives at
 * about 45 state messages and 30 video frames a second, so everything the fly
 * does is smoothed toward the last message rather than snapped to it.
 *
 * Two layouts. Landscape is the room through one orbit camera. Portrait
 * (`?portrait=1`, or `run.py --portrait`) is 9:16 for Reels: view 1 there is a
 * composition of two cameras drawn into two bands of one canvas, the TV
 * close-up in the top 45 percent and the fly with its controller below it,
 * with the milestone strip (DOM) in the band at the bottom. Views 2 to 4 are
 * the ordinary orbit views, full frame, in either layout.
 */

import * as THREE from '../vendor/three.module.js';

import { FlyActor } from './fly.js';
import { JourneyPanel } from './journey.js';
import { Monitor } from './monitor.js';
import { Feed, PROTOCOL_VERSION, unpackBits } from './net.js';
import { Orbit } from './orbit.js';
import { Overlay } from './overlay.js';
import { SEAT_HEIGHT, buildRoom } from './room.js';
import { PORTRAIT_FLY, PORTRAIT_TV_SHARE, VIEWS, clamp } from './theme.js';
import { SCREEN, Television } from './tv.js';

const PORTRAIT = new URLSearchParams(window.location.search).get('portrait') === '1';

function boot() {
  const stage = document.getElementById('stage');
  const overlay = new Overlay(document.getElementById('overlay'));
  if (PORTRAIT) document.body.classList.add('portrait');

  const renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: 'high-performance' });
  // Portrait is for recording, so it draws at the full device pixel ratio
  // and never trades resolution for frame rate; landscape caps it at 2.
  const fullRatio = window.devicePixelRatio || 1;
  renderer.setPixelRatio(PORTRAIT ? fullRatio : Math.min(fullRatio, 2));
  renderer.setSize(window.innerWidth, window.innerHeight);
  renderer.setClearColor(0x0b0910, 1);
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.15;
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFShadowMap;
  stage.appendChild(renderer.domElement);

  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x0b0910);
  scene.fog = new THREE.Fog(0x0b0910, 7, 17);

  const camera = new THREE.PerspectiveCamera(42, window.innerWidth / window.innerHeight, 0.05, 60);
  const orbit = new Orbit(THREE, camera, renderer.domElement);
  orbit.setView(VIEWS[1], true);

  // The portrait composition's two cameras. Neither orbits.
  const tvCamera = new THREE.PerspectiveCamera(30, 1, 0.05, 60);
  const flyCamera = new THREE.PerspectiveCamera(PORTRAIT_FLY.fov, 1, 0.05, 60);
  const flyEye = new THREE.Vector3(...PORTRAIT_FLY.eye);
  const flyLook = new THREE.Vector3(...PORTRAIT_FLY.look);
  let viewKey = '1';
  const composed = () => PORTRAIT && viewKey === '1';
  const viewName = () => (composed() ? 'portrait: the TV above the fly' : VIEWS[viewKey].name);
  overlay.setView(viewName());

  /** Back the TV camera off just far enough that the whole picture, with a
   *  sliver of bezel, fits a band of this aspect. */
  function frameTelevision(aspect) {
    const half = Math.tan(THREE.MathUtils.degToRad(tvCamera.fov / 2));
    const needH = SCREEN.height * 1.07;
    const needW = SCREEN.width * 1.07;
    const distance = Math.max(needH / (2 * half), needW / (2 * half * aspect));
    tvCamera.aspect = aspect;
    tvCamera.position.set(SCREEN.x, SCREEN.y, SCREEN.z + distance);
    tvCamera.lookAt(SCREEN.x, SCREEN.y, SCREEN.z);
    tvCamera.updateProjectionMatrix();
  }

  const room = buildRoom(THREE, scene);
  const television = new Television(THREE, scene);
  const fly = new FlyActor(THREE, scene, SEAT_HEIGHT);
  const monitor = new Monitor(THREE, scene);
  const strip = document.getElementById('strip');
  let feed = null;
  const journey = new JourneyPanel(strip, document.getElementById('flash'), {
    save: () => feed.command('save'),
    pause: () => feed.command('pause'),
  });
  journey.onFlash = () => fly.milestonePulse();

  const signals = { firing: 0.08, dopamine: 0, inBattle: false };
  let hello = null;
  let lastStaticAt = 0;
  let shadowsOn = true;
  let lowFor = 0;
  let fps = 60;
  let note = '';

  // -- the feed ---------------------------------------------------------

  feed = new Feed({
    onHello(message) {
      hello = message;
      if (message.protocol !== PROTOCOL_VERSION) {
        note = `the server speaks protocol ${message.protocol}, this page speaks ${PROTOCOL_VERSION}`;
      }
      monitor.setLabels(message.spike_labels);
      overlay.setHello(message);
      journey.setHello(message);
    },
    onState(state) {
      fly.setHeld(state.pressed);
      for (const event of state.events || []) fly.press(event.pool);
      if (state.panic) {
        fly.startle();
        orbit.knock(1);
      }
      signals.firing = state.firing_rate;
      signals.dopamine = state.dopamine;
      signals.inBattle = state.in_battle;
      if (hello && hello.spike_bits) {
        monitor.pushColumn(unpackBits(state.spikes, hello.spike_bits));
      }
      monitor.setMbon(state.mbon);
      overlay.setState(state);
      journey.setState(state);
    },
    onRunStatus(status) {
      journey.setRunStatus(status);
    },
    onVideo(pixels) {
      television.draw(pixels);
    },
    onStatus(status, detail) {
      overlay.setStatus(status, detail);
      journey.setFeed(status);
    },
  });
  feed.start();

  // -- keys -------------------------------------------------------------

  window.addEventListener('keydown', (event) => {
    if (event.target && event.target.tagName === 'BUTTON' && (event.key === ' ' || event.key === 'Enter')) return;
    const key = event.key.toLowerCase();
    if (VIEWS[key]) {
      viewKey = key;
      orbit.setView(VIEWS[key]);
      overlay.setView(viewName());
    } else if (key === 'p' || key === ' ') {
      event.preventDefault();
      journey.pause();
    } else if (key === 's') {
      journey.save();
    } else if (key === 'g') {
      const mode = television.toggleMode();
      note = mode === 'green' ? 'Game Boy green' : 'plain gray';
    } else if (key === 'h') {
      overlay.toggle();
    } else if (key === 'r') {
      viewKey = '1';
      orbit.setView(VIEWS[1]);
      overlay.setView(viewName());
    }
  });

  window.addEventListener('resize', () => {
    camera.aspect = window.innerWidth / window.innerHeight;
    camera.updateProjectionMatrix();
    renderer.setSize(window.innerWidth, window.innerHeight);
  });

  // -- the loop ---------------------------------------------------------

  function dropShadows() {
    shadowsOn = false;
    renderer.shadowMap.enabled = false;
    television.setShadows(false);
    scene.traverse((object) => {
      if (object.material) {
        const materials = Array.isArray(object.material) ? object.material : [object.material];
        for (const material of materials) material.needsUpdate = true;
      }
    });
    note = 'shadows off to hold the frame rate';
  }

  function guardFrameRate(dt) {
    fps = fps + (1 / Math.max(dt, 1e-4) - fps) * 0.05;
    if (fps < 48) {
      lowFor += dt;
    } else {
      lowFor = Math.max(0, lowFor - dt);
    }
    if (lowFor > 3 && shadowsOn) {
      dropShadows();
      lowFor = 0;
    } else if (lowFor > 6 && renderer.getPixelRatio() > 1 && !PORTRAIT) {
      renderer.setPixelRatio(1);
      note = 'drawing at a lower resolution to hold the frame rate';
      lowFor = 0;
    }
  }

  const timer = new THREE.Timer();
  timer.connect(document);
  let elapsed = 0;

  function frame(now) {
    timer.update(now);
    const dt = clamp(timer.getDelta(), 0, 0.1);
    elapsed += dt;

    if (feed.status !== 'connected' && elapsed - lastStaticAt > 0.07) {
      lastStaticAt = elapsed;
      television.showStatic();
    }

    fly.update(dt, signals);
    television.update(dt);
    room.update(dt, elapsed);
    monitor.update(elapsed);
    orbit.update(dt);
    journey.update(dt);
    guardFrameRate(dt);

    overlay.setNote(
      `${Math.round(fps)} frames a second` +
        (shadowsOn ? '' : ', shadows off') +
        (note ? '  |  ' + note : ''),
    );

    if (composed()) {
      renderComposition();
    } else {
      renderer.setViewport(0, 0, window.innerWidth, window.innerHeight);
      renderer.render(scene, camera);
    }
    requestAnimationFrame(frame);
  }

  /** Portrait view 1: TV band on top, fly band under it, the band behind the
   *  strip at the bottom cleared to the dark of the room. Viewports are in
   *  CSS pixels from the bottom left, as WebGL has them. */
  function renderComposition() {
    const width = window.innerWidth;
    const height = window.innerHeight;
    const stripHeight = Math.min(Math.round(strip.getBoundingClientRect().height), Math.round(height * 0.3));
    const tvHeight = Math.round(height * PORTRAIT_TV_SHARE);
    const flyHeight = Math.max(1, height - tvHeight - stripHeight);

    renderer.setScissorTest(true);

    frameTelevision(width / tvHeight);
    renderer.setViewport(0, height - tvHeight, width, tvHeight);
    renderer.setScissor(0, height - tvHeight, width, tvHeight);
    renderer.render(scene, tvCamera);
    // The fly band reuses the shadow map the TV band just drew: nothing has
    // moved between the two renders, and it saves a whole shadow pass.
    renderer.shadowMap.autoUpdate = false;

    flyCamera.aspect = width / flyHeight;
    flyCamera.updateProjectionMatrix();
    const jolt = orbit.shake * orbit.shake * 0.04;
    flyCamera.position.set(
      flyEye.x + (Math.random() - 0.5) * jolt,
      flyEye.y + (Math.random() - 0.5) * jolt,
      flyEye.z + (Math.random() - 0.5) * jolt,
    );
    flyCamera.lookAt(flyLook);
    renderer.setViewport(0, stripHeight, width, flyHeight);
    renderer.setScissor(0, stripHeight, width, flyHeight);
    renderer.render(scene, flyCamera);
    renderer.shadowMap.autoUpdate = true;

    if (stripHeight > 0) {
      renderer.setViewport(0, 0, width, stripHeight);
      renderer.setScissor(0, 0, width, stripHeight);
      renderer.clear();
    }
    renderer.setScissorTest(false);
  }

  filmGrain();
  requestAnimationFrame(frame);
  window.__couchBooted = true;
}

/** A faint moving grain and a vignette over the canvas, in CSS: the noise
 *  tile is drawn once here and slid about by a compositor animation
 *  (index.html), so it costs the GPU next to nothing and no JS per frame. */
function filmGrain() {
  const grain = document.getElementById('grain');
  if (!grain) return;
  const canvas = document.createElement('canvas');
  canvas.width = 160;
  canvas.height = 160;
  const ctx = canvas.getContext('2d');
  const image = ctx.createImageData(160, 160);
  for (let i = 0; i < image.data.length; i += 4) {
    const value = Math.random() * 255;
    image.data[i] = value;
    image.data[i + 1] = value;
    image.data[i + 2] = value;
    image.data[i + 3] = 255;
  }
  ctx.putImageData(image, 0, 0);
  grain.style.setProperty('--grain', `url(${canvas.toDataURL('image/png')})`);
}

try {
  boot();
} catch (error) {
  if (window.couchCrash) window.couchCrash(error && error.stack ? error.stack : String(error));
  else throw error;
}
