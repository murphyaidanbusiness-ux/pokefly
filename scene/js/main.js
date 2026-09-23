/**
 * Puts the scene together and drives it from the feed.
 *
 * Every number the browser draws comes from a message; nothing here simulates
 * anything. The render loop runs at the display's rate and the feed arrives at
 * about 45 state messages and 30 video frames a second, so everything the fly
 * does is smoothed toward the last message rather than snapped to it.
 */

import * as THREE from '../vendor/three.module.js';

import { FlyActor } from './fly.js';
import { Monitor } from './monitor.js';
import { Feed, PROTOCOL_VERSION, unpackBits } from './net.js';
import { Orbit } from './orbit.js';
import { Overlay } from './overlay.js';
import { SEAT_HEIGHT, buildRoom } from './room.js';
import { VIEWS, clamp } from './theme.js';
import { Television } from './tv.js';

function boot() {
  const stage = document.getElementById('stage');
  const overlay = new Overlay(document.getElementById('overlay'));

  const renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: 'high-performance' });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.setSize(window.innerWidth, window.innerHeight);
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.15;
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  stage.appendChild(renderer.domElement);

  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x0b0910);
  scene.fog = new THREE.Fog(0x0b0910, 7, 17);

  const camera = new THREE.PerspectiveCamera(42, window.innerWidth / window.innerHeight, 0.05, 60);
  const orbit = new Orbit(THREE, camera, renderer.domElement);
  orbit.setView(VIEWS[1], true);
  overlay.setView(VIEWS[1].name);

  buildRoom(THREE, scene);
  const television = new Television(THREE, scene);
  const fly = new FlyActor(THREE, scene, SEAT_HEIGHT);
  const monitor = new Monitor(THREE, scene);

  const signals = { firing: 0.08, dopamine: 0, inBattle: false };
  let hello = null;
  let lastStaticAt = 0;
  let shadowsOn = true;
  let lowFor = 0;
  let fps = 60;
  let note = '';

  // -- the feed ---------------------------------------------------------

  const feed = new Feed({
    onHello(message) {
      hello = message;
      if (message.protocol !== PROTOCOL_VERSION) {
        note = `the server speaks protocol ${message.protocol}, this page speaks ${PROTOCOL_VERSION}`;
      }
      monitor.setLabels(message.spike_labels);
      overlay.setHello(message);
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
    },
    onVideo(pixels) {
      television.draw(pixels);
    },
    onStatus(status, detail) {
      overlay.setStatus(status, detail);
    },
  });
  feed.start();

  // -- keys -------------------------------------------------------------

  window.addEventListener('keydown', (event) => {
    const key = event.key.toLowerCase();
    if (VIEWS[key]) {
      orbit.setView(VIEWS[key]);
      overlay.setView(VIEWS[key].name);
    } else if (key === 'g') {
      const mode = television.toggleMode();
      note = mode === 'green' ? 'Game Boy green' : 'plain gray';
    } else if (key === 'h') {
      overlay.toggle();
    } else if (key === 'r') {
      orbit.setView(VIEWS[1]);
      overlay.setView(VIEWS[1].name);
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
    } else if (lowFor > 6 && renderer.getPixelRatio() > 1) {
      renderer.setPixelRatio(1);
      note = 'drawing at a lower resolution to hold the frame rate';
      lowFor = 0;
    }
  }

  const clock = new THREE.Clock();
  let elapsed = 0;

  function frame() {
    const dt = clamp(clock.getDelta(), 0, 0.1);
    elapsed += dt;

    if (feed.status !== 'connected' && elapsed - lastStaticAt > 0.07) {
      lastStaticAt = elapsed;
      television.showStatic();
    }

    fly.update(dt, signals);
    television.update(dt);
    monitor.update(elapsed);
    orbit.update(dt);
    guardFrameRate(dt);

    overlay.setNote(
      `${Math.round(fps)} frames a second` +
        (shadowsOn ? '' : ', shadows off') +
        (note ? '  |  ' + note : ''),
    );

    renderer.render(scene, camera);
    requestAnimationFrame(frame);
  }

  requestAnimationFrame(frame);
  window.__couchBooted = true;
}

try {
  boot();
} catch (error) {
  if (window.couchCrash) window.couchCrash(error && error.stack ? error.stack : String(error));
  else throw error;
}
