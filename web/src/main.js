// Higashiyama Walk — bootstrap, UI wiring, quality management and the frame loop.
import * as THREE from 'three';
import { EffectComposer } from 'three/addons/postprocessing/EffectComposer.js';
import { RenderPass } from 'three/addons/postprocessing/RenderPass.js';
import { UnrealBloomPass } from 'three/addons/postprocessing/UnrealBloomPass.js';
import { OutputPass } from 'three/addons/postprocessing/OutputPass.js';
import { PLACES, SPAWN, ZONES, QUALITY } from './config.js';
import { installHeightFog } from './materials.js';
import { Sky } from './sky.js';
import { loadWorld } from './world.js';
import { Controller } from './controller.js';
import { Traveller } from './character.js';
import { FollowCamera } from './camera.js';
import { Input } from './input.js';
import { buildLanterns } from './lanterns.js';
import { buildLeaves } from './particles.js';
import { MiniMap } from './minimap.js';

const $ = (id) => document.getElementById(id);
const store = {
  get(k, d) { try { const v = localStorage.getItem('hw-' + k); return v === null ? d : v; } catch { return d; } },
  set(k, v) { try { localStorage.setItem('hw-' + k, String(v)); } catch { /* storage unavailable */ } },
};
const isTouch = matchMedia('(pointer: coarse)').matches || 'ontouchstart' in window || navigator.maxTouchPoints > 0;
const isMobile = isTouch && Math.min(screen.width, screen.height) < 900;

const hw = (window.__hw = { started: true, ready: false, errors: [], fps: 0, maxDt: 0.1 });

// readable text for anything a promise may reject with (Error, Event from a failed image/script, string ...)
function describe(e) {
  if (!e) return 'unknown error';
  if (e instanceof Error) return e.message || e.name;
  if (typeof Event !== 'undefined' && e instanceof Event) {
    const t = e.target, src = t && (t.currentSrc || t.src || t.href);
    return `failed to load ${src || 'a resource'} (${e.type})`;
  }
  if (typeof e === 'object' && e.message) return String(e.message);
  return String(e);
}

function fatal(msg) {
  const f = $('fatal'); f.hidden = false; f.textContent = msg;
  $('loading').classList.add('done');
}

// loading progress: the bar follows every event; the (aria-live) text only changes on a new stage or every 1.5 s
let lastStage = '', lastTextT = 0;
function progress(f, text) {
  $('load-fill').style.width = Math.round(Math.max(0.02, Math.min(1, f)) * 100) + '%';
  if (!text) return;
  const stage = text.replace(/\s[\d.]+(\s\/\s[\d.]+)?\sMB$/, '');
  const now = performance.now();
  if (stage !== lastStage || now - lastTextT > 1500) {
    $('load-text').textContent = text;
    lastStage = stage; lastTextT = now;
  }
}

async function main() {
  // ---------------------------------------------------------------- renderer
  const canvas = $('scene');
  let renderer;
  try {
    renderer = new THREE.WebGLRenderer({ canvas, antialias: !isMobile, powerPreference: 'high-performance', stencil: false });
  } catch (e) {
    fatal('This walk needs WebGL, which is not available in this browser.');
    throw e;
  }
  installHeightFog();
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = isMobile ? THREE.PCFShadowMap : THREE.PCFSoftShadowMap;
  renderer.shadowMap.autoUpdate = false;   // re-rendered only when the light, its snapped centre or the walker moves
  renderer.setClearColor(0x1d2338, 1);

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(55, innerWidth / innerHeight, 0.1, 2000);

  // ---------------------------------------------------------------- quality
  let qualityPref = store.get('quality', 'auto');
  const autoQ = isMobile ? 'medium' : 'high';
  let Q = QUALITY[qualityPref === 'auto' ? autoQ : qualityPref] || QUALITY[autoQ];
  let dprScale = 1;
  let bloomAllowed = true;
  const baseDpr = () => Math.min(devicePixelRatio || 1, isMobile ? Math.min(1.5, Q.dprCap) : Q.dprCap);

  const sky = new Sky(renderer, scene);
  const tod0 = parseFloat(store.get('tod', '0.35'));
  sky.setTime(Number.isFinite(tod0) ? tod0 : 0.35);

  // ---------------------------------------------------------------- world
  const world = await loadWorld(scene, renderer, progress);
  progress(0.93, 'Hanging the lanterns…');
  let minimapData = { streets: [], buildings: [], barriers: [] };
  try {
    const r = await fetch('assets/minimap.json');
    if (r.ok) minimapData = await r.json();
  } catch (e) { console.warn('minimap.json unavailable', e); }

  const ctrl = new Controller(world.bvh, world.objInfo, world.colGeom);
  const traveller = new Traveller();
  scene.add(traveller.root);
  const follow = new FollowCamera(camera, world.bvh);
  const lanterns = buildLanterns(scene, minimapData, ctrl);
  const leaves = buildLeaves(scene, QUALITY.high.particles);
  const minimap = new MiniMap($('minimap'), $('minimap-wrap'), minimapData);
  if (world.heroLoaded) {
    const h = world.heroInfo || {};
    $('info-pagoda').textContent = `Pagoda: hero model on the surveyed OSM/PLATEAU footprint${h.height_m ? `, ${h.height_m} m incl. sōrin` : ''} (documented/evidence-based; see docs/evidence). Fine carving and colour detail are artistic.`;
  }

  // ---------------------------------------------------------------- post (bloom on high only)
  // one composer, created on first use and then kept: disabling bloom bypasses it (no GPU resource churn)
  let composer = null, bloom = null, useComposer = false;
  function setupComposer() {
    useComposer = Q.bloom && bloomAllowed;
    if (!useComposer || composer) return;
    const rt = new THREE.WebGLRenderTarget(1, 1, { type: THREE.HalfFloatType, samples: Q.msaa ? 4 : 0 });
    composer = new EffectComposer(renderer, rt);
    composer.addPass(new RenderPass(scene, camera));
    bloom = new UnrealBloomPass(new THREE.Vector2(256, 256), 0.5, 0.55, 0.95);
    composer.addPass(bloom);
    composer.addPass(new OutputPass());
    resize();
  }

  // adaptive resolution: refresh-aware (peak fps ~ display refresh), with hysteresis; the first window after
  // start / quality change / tab return is skipped (shader compilation, throttled background timers)
  const adapt = {
    peak: 0, good: 0, cooldown: 0, skip: 1,
    reset() { this.good = 0; this.cooldown = 0; this.skip = 1; },
  };
  let shadowDirty = true;

  function resize() {
    const w = innerWidth, h = innerHeight;
    const pr = Math.max(0.5, baseDpr() * dprScale);
    renderer.setPixelRatio(pr);
    renderer.setSize(w, h);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
    if (composer) { composer.setPixelRatio(pr); composer.setSize(w, h); }
  }
  addEventListener('resize', resize);

  function applyQuality() {
    Q = QUALITY[qualityPref === 'auto' ? autoQ : qualityPref] || QUALITY[autoQ];
    dprScale = 1;
    bloomAllowed = true;
    adapt.reset();
    leaves.points.geometry.setDrawRange(0, Q.particles);
    renderer.shadowMap.enabled = Q.shadows;
    sky.sun.castShadow = Q.shadows;
    for (const m of world.treeMeshes) m.castShadow = Q.treeShadows;
    shadowDirty = true;
    setupComposer();
    resize();
    document.querySelectorAll('.seg button').forEach((b) => b.setAttribute('aria-checked', String(b.dataset.q === qualityPref)));
  }
  applyQuality();

  // ---------------------------------------------------------------- UI
  const input = new Input(canvas, { joy: $('joy'), knob: $('joy-knob') });
  const panels = ['panel-places', 'panel-settings', 'panel-info'];
  const btnFor = { 'panel-places': 'btn-places', 'panel-settings': 'btn-settings', 'panel-info': 'btn-info' };
  function openPanel(id) {
    for (const p of panels) {
      const on = p === id && $(p).hidden;
      $(p).hidden = !on;
      $(btnFor[p]).setAttribute('aria-expanded', String(on));
      if (on) {
        // move focus into the opened panel (its heading), so keyboard and screen-reader users land there
        const h = $(p).querySelector('h2');
        if (h) { h.tabIndex = -1; h.focus({ preventScroll: true }); }
      }
    }
    $('minimap-wrap').hidden = panels.some((p) => !$(p).hidden);
  }
  const closePanels = () => {
    let wasOpen = null;
    for (const p of panels) {
      if (!$(p).hidden) wasOpen = p;
      $(p).hidden = true; $(btnFor[p]).setAttribute('aria-expanded', 'false');
    }
    $('minimap-wrap').hidden = false;
    if (wasOpen && $(wasOpen).contains(document.activeElement)) $(btnFor[wasOpen]).focus({ preventScroll: true });
  };
  $('btn-places').onclick = () => openPanel('panel-places');
  $('btn-settings').onclick = () => openPanel('panel-settings');
  $('btn-info').onclick = () => openPanel('panel-info');
  document.querySelectorAll('[data-close]').forEach((b) => (b.onclick = closePanels));
  canvas.addEventListener('pointerdown', closePanels);
  addEventListener('keydown', (e) => { if (e.key === 'Escape') closePanels(); });

  const list = $('places-list');
  for (const p of PLACES) {
    const li = document.createElement('li');
    const b = document.createElement('button');
    b.innerHTML = `<span class="pl-ja"></span><span class="pl-en"></span>`;
    b.querySelector('.pl-ja').textContent = p.ja;
    b.querySelector('.pl-en').textContent = p.en;
    b.onclick = () => { teleport(p); closePanels(); };
    li.appendChild(b); list.appendChild(li);
  }

  const tod = $('tod');
  tod.value = String(sky.t);
  tod.addEventListener('input', () => { sky.setTime(parseFloat(tod.value)); store.set('tod', tod.value); });
  document.querySelectorAll('.seg button').forEach((b) => (b.onclick = () => {
    qualityPref = b.dataset.q; store.set('quality', qualityPref); applyQuality();
  }));

  // Run toggle: pointerup (works while another finger holds the joystick, when no click is synthesised);
  // keyboard activation arrives as a click with detail 0
  const runBtn = $('btn-run');
  if (isTouch) runBtn.hidden = false;
  const toggleRun = () => {
    input.runToggle = !input.runToggle;
    runBtn.setAttribute('aria-pressed', String(input.runToggle));
  };
  runBtn.addEventListener('pointerdown', (e) => e.preventDefault());
  runBtn.addEventListener('pointerup', (e) => { e.preventDefault(); toggleRun(); });
  runBtn.addEventListener('click', (e) => { if (e.detail === 0) toggleRun(); });

  const hint = $('hint');
  hint.textContent = isTouch
    ? 'Left thumb: walk · drag right: look · pinch: zoom'
    : 'WASD / arrows: walk · Shift: run · drag: look · wheel: zoom';
  let hintTimer = 0;

  let toastT = 0;
  function toast(msg, secs = 3.5) { const t = $('toast'); if (t.textContent !== msg) t.textContent = msg; t.hidden = false; toastT = secs; }

  // ---------------------------------------------------------------- teleport
  const teleportLog = {};
  function teleport(p) {
    const x = p.x, z = -p.n;
    // nearest walkable, collision-free spot; widen the search before giving up (never drop onto a roof)
    const spot = ctrl.findSpot(x, z, p.verify ? 12 : 4) || ctrl.findSpot(x, z, 30);
    let pos;
    if (spot) pos = spot.pos;
    else { const g = ctrl.dropTo(x, z); pos = new THREE.Vector3(x, g ? g.y : 60, z); console.warn('no walkable spot near', p.id); }
    const facing = Math.atan2(p.look[0] - pos.x, -p.look[1] - pos.z);
    ctrl.teleport(pos, facing);
    traveller.renderY = null;
    follow.pitch = p.pitch ?? 0.12; follow.dist = p.dist ?? 5.2;
    follow.snap(pos, facing + Math.PI);
    teleportLog[p.id] = { requested: [p.x, p.n], placed: [+pos.x.toFixed(2), +(-pos.z).toFixed(2), +pos.y.toFixed(2)], offset: spot ? spot.offset : null, ground: spot ? spot.ground : null };
    return teleportLog[p.id];
  }

  // ---------------------------------------------------------------- loop
  const clock = new THREE.Clock();
  let frames = 0, fpsT = 0, mmT = 0, zoneT = 0;
  const fpsHistory = [];
  const fwd = new THREE.Vector3(), right = new THREE.Vector3(), mv = new THREE.Vector3(), lightCol = new THREE.Color(), tmpCol = new THREE.Color();
  let frameErrors = 0, stopped = false, lastShadowY = NaN;

  let fpsStart = performance.now();
  function frame() {
    if (stopped) return;
    requestAnimationFrame(frame);       // scheduled first: one bad frame must not freeze the walk
    try {
      step();
      frameErrors = 0;
    } catch (e) {
      frameErrors++;
      console.error(e);
      hw.errors.push(String(e && e.stack || e));
      if (frameErrors >= 5) { stopped = true; fatal('Sorry — the walk stopped because of an error: ' + describe(e)); }
    }
  }
  function step() {
    const dt = Math.min(clock.getDelta(), hw.maxDt);
    const now = performance.now();
    const inp = input.sample();
    if (inp.look.x || inp.look.y) follow.look(inp.look.x, inp.look.y, now);
    if (inp.zoom !== 1) follow.zoom(inp.zoom);
    fwd.copy(follow.forward);
    right.set(-fwd.z, 0, fwd.x);
    mv.set(0, 0, 0).addScaledVector(fwd, inp.y).addScaledVector(right, inp.x);
    const sub = Math.max(1, Math.ceil(dt / (1 / 60)));
    for (let i = 0; i < sub; i++) {
      ctrl.update(dt / sub, mv, inp.run);
      if (hw.groundTrace) hw.groundTrace.add(ctrl.groundName);
    }
    traveller.update(dt, ctrl.pos, ctrl.facing, ctrl.speed, ctrl.grounded);
    follow.update(dt, traveller.root.position, ctrl.facing, ctrl.speed > 0.3, now, input.touchMode);
    if (sky.placeShadow(ctrl.pos, Q.shadowRange, Q.shadow)) shadowDirty = true;
    // the walker's own shadow: re-render while it moves / animates noticeably
    if (ctrl.speed > 0.02 || !ctrl.grounded || Math.abs(traveller.root.position.y - lastShadowY) > 0.002) shadowDirty = true;
    lastShadowY = traveller.root.position.y;
    if (sky.shadowDirty) { shadowDirty = true; sky.shadowDirty = false; }
    if (shadowDirty && Q.shadows) { renderer.shadowMap.needsUpdate = true; shadowDirty = false; }
    sky.update(dt, camera, world.groundMat);
    lanterns.update(sky.lanternIntensity);
    for (const m of world.glowMats) m.emissiveIntensity = m.userData.baseEmissive * (0.12 + 0.26 * sky.lanternIntensity);
    lightCol.copy(sky.sun.color).multiplyScalar(0.35 + 0.2 * sky.sun.intensity).add(tmpCol.copy(sky.hemi.color).multiplyScalar(sky.hemi.intensity * 0.6));
    leaves.update(dt, camera, lightCol, renderer.domElement.height);
    if (bloom) bloom.strength = 0.25 + 0.18 * sky.lanternIntensity;

    // gentle message while the walker is near the invisible wall at the edge of the surveyed box
    if (ctrl.edgeWarn) toast('The surveyed 400 m area ends here — the lanes of Higashiyama continue beyond.', Math.max(toastT, 1.2));
    if (toastT > 0) { toastT -= dt; if (toastT <= 0) $('toast').hidden = true; }
    if (input.anyInput && ctrl.speed > 0.2 && !hint.classList.contains('fade')) {
      hintTimer += dt;
      if (hintTimer > 5) { hint.classList.add('fade'); setTimeout(() => { hint.hidden = true; }, 1100); }
    }

    mmT -= dt;
    if (mmT <= 0) { mmT = 0.1; minimap.draw(ctrl.pos.x, -ctrl.pos.z, ctrl.facing, follow.yaw); }
    zoneT -= dt;
    if (zoneT <= 0) {
      zoneT = 0.5;
      const n = -ctrl.pos.z, x = ctrl.pos.x;
      const z = ZONES.find((zz) => zz.test(x, n));
      const label = `${z.ja} ${z.en}`;
      if ($('place-name').textContent !== label) $('place-name').textContent = label;
    }

    if (useComposer && composer) composer.render(dt); else renderer.render(scene, camera);

    // fps + adaptive resolution
    frames++; fpsT = (now - fpsStart) / 1000;
    if (fpsT >= 2) {
      const fps = frames / fpsT;
      fpsStart = now;
      hw.fps = Math.round(fps * 10) / 10;
      fpsHistory.push(hw.fps); if (fpsHistory.length > 30) fpsHistory.shift();
      frames = 0; fpsT = 0;
      if (adapt.skip > 0) adapt.skip--;
      else if (qualityPref === 'auto') {
        // peak ~ display refresh (60/90/120 Hz) once vsync-capped; decays slowly so a lower-refresh mode is learnt
        // again. Recovery needs fps >= target AND (at the refresh cap OR well above target): on a 60 Hz panel
        // that is >= 55 fps (the old rule needed an impossible 70 fps)
        adapt.peak = Math.max(fps, adapt.peak * 0.98);
        const target = isMobile ? 30 : 55;
        if (adapt.cooldown > 0) adapt.cooldown--;
        if (fps < target * 0.85) {
          adapt.good = 0;
          if (dprScale > 0.6) { dprScale = Math.max(0.6, dprScale - 0.1); resize(); adapt.cooldown = 3; adapt.skip = 1; }
          else if (useComposer) { bloomAllowed = false; setupComposer(); }
        } else if (dprScale < 1 && fps >= target && (fps >= adapt.peak * 0.92 || fps > target * 1.3)) {
          // running at (near) the refresh cap or well above target: recover resolution after 2 good windows
          if (++adapt.good >= 2 && adapt.cooldown === 0) { dprScale = Math.min(1, dprScale + 0.05); resize(); adapt.good = 0; adapt.skip = 1; }
        } else adapt.good = 0;
      }
      const info = renderer.info.render;
      $('perf-line').textContent = `${hw.fps} fps · ${Math.round(renderer.getPixelRatio() * 100) / 100}× px · ${info.calls} draws · ${(info.triangles / 1000).toFixed(0)}k tris${useComposer ? ' · bloom' : ''}`;
    }
  }

  // tab hidden: drop held input; back: restart the fps window and skip it (rAF was paused)
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) input.clear();
    else { clock.getDelta(); frames = 0; fpsStart = performance.now(); adapt.skip = 1; }
  });

  // ---------------------------------------------------------------- start
  const s = teleport(SPAWN);
  // pre-compile shaders before the loader disappears (no hitch on the first frames)
  progress(0.97, 'Preparing shaders…');
  try {
    follow.update(0, traveller.root.position, ctrl.facing, false, performance.now());
    if (renderer.compileAsync) await renderer.compileAsync(scene, camera);
  } catch (e) { console.warn('shader prewarm skipped', e); }
  progress(1, 'Ready');
  $('hud').hidden = false;
  minimap.resize();
  $('loading').classList.add('done');
  setTimeout(() => { $('loading').hidden = true; }, 700);
  canvas.tabIndex = 0;
  requestAnimationFrame(frame);

  Object.assign(hw, {
    ready: true, THREE, scene, camera, renderer, ctrl, follow, sky, world, lanterns, traveller, input, teleport, teleportLog,
    places: PLACES, spawn: s, fpsHistory, isMobile, isTouch,
    setTime: (t) => { sky.setTime(t); tod.value = String(t); },
    state: () => ({
      x: +ctrl.pos.x.toFixed(3), n: +(-ctrl.pos.z).toFixed(3), y: +ctrl.pos.y.toFixed(3), grounded: ctrl.grounded,
      ground: ctrl.groundName, speed: +ctrl.speed.toFixed(2), facing: +ctrl.facing.toFixed(3), wall: ctrl.wallContact,
      slopeBlock: ctrl.blockedBySlope, camYaw: +follow.yaw.toFixed(3), camDist: +follow.curDist.toFixed(2),
    }),
    probe: (x, n) => { const g = ctrl.dropTo(x, -n); return g && { y: g.y, ny: g.normal.y, name: g.info.name, walkable: g.info.walkable }; },
    quality: () => ({ pref: qualityPref, dprScale, pixelRatio: renderer.getPixelRatio(), bloom: useComposer, shadow: Q.shadow, particles: Q.particles, peakFps: adapt.peak }),
    stats: () => ({ ...world.stats, lanterns: lanterns.count, calls: renderer.info.render.calls, tris: renderer.info.render.triangles }),
  });
}

main().catch((e) => {
  console.error(e);
  hw.errors.push(String(e && e.stack || e));
  if ($('fatal').hidden) fatal('Sorry — the district could not be loaded: ' + describe(e));
});
