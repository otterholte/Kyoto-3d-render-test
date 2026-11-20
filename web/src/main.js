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

const hw = (window.__hw = { ready: false, errors: [], fps: 0 });

function fatal(msg) {
  const f = $('fatal'); f.hidden = false; f.textContent = msg;
  $('loading').classList.add('done');
}

function progress(f, text) {
  $('load-fill').style.width = Math.round(Math.max(0.02, Math.min(1, f)) * 100) + '%';
  if (text) $('load-text').textContent = text;
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
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
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
  if (world.heroLoaded) $('info-pagoda').textContent = 'Pagoda: hero model on the surveyed footprint (documented height 46 m); carved detail is artistic.';

  // ---------------------------------------------------------------- post (bloom on high only)
  let composer = null, bloom = null;
  function setupComposer() {
    const want = Q.bloom && bloomAllowed;
    if (!want) { if (composer) { composer.dispose(); composer = null; bloom = null; } return; }
    if (composer) return;
    const rt = new THREE.WebGLRenderTarget(1, 1, { type: THREE.HalfFloatType, samples: Q.msaa ? 4 : 0 });
    composer = new EffectComposer(renderer, rt);
    composer.addPass(new RenderPass(scene, camera));
    bloom = new UnrealBloomPass(new THREE.Vector2(256, 256), 0.5, 0.55, 0.95);
    composer.addPass(bloom);
    composer.addPass(new OutputPass());
    resize();
  }

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
    leaves.points.geometry.setDrawRange(0, Q.particles);
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
    }
    $('minimap-wrap').hidden = panels.some((p) => !$(p).hidden);
  }
  const closePanels = () => { for (const p of panels) { $(p).hidden = true; $(btnFor[p]).setAttribute('aria-expanded', 'false'); } $('minimap-wrap').hidden = false; };
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

  const runBtn = $('btn-run');
  if (isTouch) runBtn.hidden = false;
  runBtn.addEventListener('click', () => {
    input.runToggle = !input.runToggle;
    runBtn.setAttribute('aria-pressed', String(input.runToggle));
  });

  const hint = $('hint');
  hint.textContent = isTouch
    ? 'Left thumb: walk · drag right: look · pinch: zoom'
    : 'WASD / arrows: walk · Shift: run · drag: look · wheel: zoom';
  let hintTimer = 0;

  let toastT = 0;
  function toast(msg, secs = 3.5) { const t = $('toast'); t.textContent = msg; t.hidden = false; toastT = secs; }

  // ---------------------------------------------------------------- teleport
  const teleportLog = {};
  function teleport(p) {
    const x = p.x, z = -p.n;
    const spot = ctrl.findSpot(x, z, p.verify ? 12 : 4);
    let pos;
    if (spot) pos = spot.pos;
    else { const g = ctrl.dropTo(x, z); pos = new THREE.Vector3(x, g ? g.y : 60, z); }
    const facing = Math.atan2(p.look[0] - pos.x, -p.look[1] - pos.z);
    ctrl.teleport(pos, facing);
    traveller.renderY = null;
    follow.pitch = 0.18; follow.dist = 5.2;
    follow.snap(pos, facing + Math.PI);
    teleportLog[p.id] = { requested: [p.x, p.n], placed: [+pos.x.toFixed(2), +(-pos.z).toFixed(2), +pos.y.toFixed(2)], offset: spot ? spot.offset : null, ground: spot ? spot.ground : null };
    return teleportLog[p.id];
  }

  // ---------------------------------------------------------------- loop
  const clock = new THREE.Clock();
  let frames = 0, fpsT = 0, mmT = 0, zoneT = 0, edgeCool = 0;
  const fpsHistory = [];
  const fwd = new THREE.Vector3(), right = new THREE.Vector3(), mv = new THREE.Vector3(), lightCol = new THREE.Color();

  let fpsStart = performance.now();
  function frame() {
    const dt = Math.min(clock.getDelta(), 0.05);
    const now = performance.now();
    const inp = input.sample();
    if (inp.look.x || inp.look.y) follow.look(inp.look.x, inp.look.y, now);
    if (inp.zoom !== 1) follow.zoom(inp.zoom);
    fwd.copy(follow.forward);
    right.set(-fwd.z, 0, fwd.x);
    mv.set(0, 0, 0).addScaledVector(fwd, inp.y).addScaledVector(right, inp.x);
    ctrl.update(dt, mv, inp.run);
    traveller.update(dt, ctrl.pos, ctrl.facing, ctrl.speed, ctrl.grounded);
    follow.update(dt, traveller.root.position, ctrl.facing, ctrl.speed > 0.3, now, input.touchMode);
    sky.placeShadow(ctrl.pos, Q.shadowRange, Q.shadow);
    sky.update(dt, camera, world.groundMat);
    lanterns.update(sky.lanternIntensity);
    lightCol.copy(sky.sun.color).multiplyScalar(0.35 + 0.2 * sky.sun.intensity).add(sky.hemi.color.clone().multiplyScalar(sky.hemi.intensity * 0.6));
    leaves.update(dt, camera, lightCol, renderer.domElement.height);
    if (bloom) bloom.strength = 0.25 + 0.18 * sky.lanternIntensity;

    if (ctrl.edgeWarn && edgeCool <= 0) {
      toast('The surveyed 400 m area ends here — the lanes of Higashiyama continue beyond.');
      edgeCool = 8;
    }
    edgeCool -= dt;
    if (toastT > 0) { toastT -= dt; if (toastT <= 0) $('toast').hidden = true; }
    if (input.anyInput && ctrl.speed > 0.2) { hintTimer += dt; if (hintTimer > 5) hint.classList.add('fade'); }

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

    if (composer) composer.render(dt); else renderer.render(scene, camera);

    // fps + adaptive resolution
    frames++; fpsT = (now - fpsStart) / 1000;
    if (fpsT >= 2) {
      const fps = frames / fpsT;
      fpsStart = now;
      hw.fps = Math.round(fps * 10) / 10;
      fpsHistory.push(hw.fps); if (fpsHistory.length > 30) fpsHistory.shift();
      frames = 0; fpsT = 0;
      if (qualityPref === 'auto') {
        const target = isMobile ? 30 : 55;
        if (fps < target * 0.85 && dprScale > 0.6) { dprScale = Math.max(0.6, dprScale - 0.1); resize(); }
        else if (fps < target * 0.85 && composer) { bloomAllowed = false; setupComposer(); }
        else if (fps > target * 1.2 + 4 && dprScale < 1) { dprScale = Math.min(1, dprScale + 0.05); resize(); }
      }
      const info = renderer.info.render;
      $('perf-line').textContent = `${hw.fps} fps · ${Math.round(renderer.getPixelRatio() * 100) / 100}× px · ${info.calls} draws · ${(info.triangles / 1000).toFixed(0)}k tris${composer ? ' · bloom' : ''}`;
    }
    requestAnimationFrame(frame);
  }

  // ---------------------------------------------------------------- start
  const s = teleport(SPAWN);
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
    get quality() { return { pref: qualityPref, dprScale, pixelRatio: renderer.getPixelRatio(), bloom: !!composer, shadow: Q.shadow }; },
    setTime: (t) => { sky.setTime(t); tod.value = String(t); },
    state: () => ({
      x: +ctrl.pos.x.toFixed(3), n: +(-ctrl.pos.z).toFixed(3), y: +ctrl.pos.y.toFixed(3), grounded: ctrl.grounded,
      ground: ctrl.groundName, speed: +ctrl.speed.toFixed(2), facing: +ctrl.facing.toFixed(3), wall: ctrl.wallContact,
      slopeBlock: ctrl.blockedBySlope, camYaw: +follow.yaw.toFixed(3), camDist: +follow.curDist.toFixed(2),
    }),
    probe: (x, n) => { const g = ctrl.dropTo(x, -n); return g && { y: g.y, ny: g.normal.y, name: g.info.name, walkable: g.info.walkable }; },
    stats: () => ({ ...world.stats, lanterns: lanterns.count, calls: renderer.info.render.calls, tris: renderer.info.render.triangles }),
  });
}

main().catch((e) => {
  console.error(e);
  hw.errors.push(String(e && e.stack || e));
  if ($('fatal').hidden) fatal('Sorry — the district could not be loaded. ' + (e && e.message ? e.message : ''));
});
