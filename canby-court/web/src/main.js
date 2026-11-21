// Canby Court — bootstrap, season switching, walk / sled modes, UI wiring, quality management and the frame loop.
import * as THREE from 'three';
import { PLACES, SPAWN, ZONES, QUALITY, SEASONS, SLED } from './config.js';
import { store, loadJSON, describe, clamp } from './util.js';
import { SU } from './shared.js';
import { loadTerrain, trackTexture } from './terrain.js';
import { buildPlaceholder, loadGLBWorld } from './world.js';
import { Sky, buildTreeline } from './sky.js';
import { Post } from './post.js';
import { Controller } from './controller.js';
import { FollowCamera, ChaseCamera } from './camera.js';
import { Input } from './input.js';
import { Character } from './character.js';
import { SledGame, Autopilot, simulate } from './sled.js';
import { jumpMeta } from './kickers.js';
import { Snowfall, Puffs, Trail, Footprints } from './effects.js';
import { MiniMap } from './minimap.js';
import { Sound } from './audio.js';
import { Grass } from './grass.js';

const $ = (id) => document.getElementById(id);
const isTouch = matchMedia('(pointer: coarse)').matches || 'ontouchstart' in window || navigator.maxTouchPoints > 0;
const isMobile = isTouch && Math.min(screen.width, screen.height) < 900;
const cc = (window.__cc = { started: true, ready: false, errors: [], fps: 0, maxDt: 0.1, animScale: 1 });

function fatal(msg) { const f = $('fatal'); f.hidden = false; f.textContent = msg; $('loading').classList.add('done'); }
let lastStage = '', lastTextT = 0;
function progress(f, text) {
  $('load-fill').style.width = Math.round(clamp(f, 0.02, 1) * 100) + '%';
  if (!text) return;
  const now = performance.now();
  if (text !== lastStage || now - lastTextT > 1500) { $('load-text').textContent = text; lastStage = text; lastTextT = now; }
}
const loadImage = (url) => new Promise((res, rej) => { const i = new Image(); i.onload = () => res(i); i.onerror = rej; i.src = url; });
// three.js yaw (forward = (sin, cos) in x/z) from a math heading (deg CCW from east, local frame)
const yawFromHeading = (deg) => { const a = THREE.MathUtils.degToRad(deg); return Math.atan2(Math.cos(a), -Math.sin(a)); };

async function main() {
  // ---------------------------------------------------------------- renderer
  const canvas = $('scene');
  let renderer;
  try {
    renderer = new THREE.WebGLRenderer({ canvas, antialias: !isMobile, powerPreference: 'high-performance', stencil: false, preserveDrawingBuffer: false });
  } catch (e) { fatal('Canby Court needs WebGL, which is not available in this browser.'); throw e; }
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.AgXToneMapping;
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = isMobile ? THREE.PCFShadowMap : THREE.PCFSoftShadowMap;
  renderer.shadowMap.autoUpdate = false;
  renderer.setClearColor(0x1e2a36, 1);
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(55, innerWidth / innerHeight, 0.1, 3000);

  // ---------------------------------------------------------------- quality
  const params = new URLSearchParams(location.search);
  let qualityPref = store.get('quality', 'auto');
  const urlQ = params.get('q'); if (urlQ && QUALITY[urlQ]) qualityPref = urlQ;
  const urlScale = parseFloat(params.get('scale'));
  const fixedScale = urlScale >= 0.25 && urlScale <= 1 ? urlScale : null;
  const autoQ = isMobile ? 'medium' : 'high';
  let Q = QUALITY[qualityPref === 'auto' ? autoQ : qualityPref] || QUALITY[autoQ];
  let dprScale = 1, bloomAllowed = true;
  const baseDpr = () => Math.min(devicePixelRatio || 1, isMobile ? Math.min(1.5, Q.dprCap) : Q.dprCap);

  // ---------------------------------------------------------------- data
  progress(0.03, 'Reading the survey…');
  const manifest = await loadJSON('dist/manifest.json?t=' + Date.now());
  const v = '?v=' + encodeURIComponent(manifest.generated || '');
  const data = await loadJSON(manifest.worldData + v);
  progress(0.1, 'Terrain (3DEP 0.5 m)…');
  const terrain = await loadTerrain(manifest);
  const surfImg = await loadImage(manifest.surface.file + v).catch(() => null);
  const surfTex = new THREE.Texture(surfImg || undefined);
  if (surfImg) { surfTex.needsUpdate = true; }
  surfTex.colorSpace = THREE.NoColorSpace; surfTex.wrapS = surfTex.wrapT = THREE.ClampToEdgeWrapping; surfTex.anisotropy = 4;
  const trackTex = trackTexture(terrain, data.sled.path);
  // photographic ground sets (optional): loaded only for the placeholder world
  let groundLib = null;
  if (manifest.groundTex && !(manifest.worlds && manifest.worlds.summer && manifest.worlds.winter)) {
    progress(0.14, 'Ground textures…');
    const tl = new THREE.TextureLoader();
    try {
      groundLib = {};
      await Promise.all(Object.entries(manifest.groundTex).map(async ([k, t]) => {
        if (isMobile && (k === 'roof' || k === 'siding')) return;
        const [a, n] = await Promise.all([tl.loadAsync(t.albedo + v), tl.loadAsync(t.normal + v)]);
        a.colorSpace = THREE.SRGBColorSpace;
        for (const x of [a, n]) { x.wrapS = x.wrapT = THREE.RepeatWrapping; x.anisotropy = isMobile ? 4 : 8; }
        groundLib[k] = { a, n, size: t.size };
      }));
    } catch (e) { console.warn('ground textures unavailable, procedural ground', e); groundLib = null; }
  }
  // leaf-card atlas for the placeholder trees (optional)
  let foliage = null;
  if (manifest.foliage && groundLib) {
    try {
      const [cells, albedo] = await Promise.all([loadJSON(manifest.foliage.json + v), new THREE.TextureLoader().loadAsync(manifest.foliage.albedo + v)]);
      albedo.colorSpace = THREE.SRGBColorSpace; albedo.anisotropy = 4;
      foliage = { cells: cells.cells, albedo };
    } catch (e) { console.warn('foliage atlas unavailable', e); }
  }
  const ctx = { manifest, data, terrain, surfTex, trackTex, lite: isMobile, groundLib, foliage };
  // 3905 front door from the scene metadata (when present): the "front door" place stands in front of it
  const d3905 = (data.houses.find((h) => h.number === 3905) || {}).doors?.find((d) => d.kind === 'door');
  if (d3905) { const pf = PLACES.find((p) => p.id === 'front'); pf.x = d3905.c[0] + d3905.n[0] * 3.2; pf.n = d3905.c[1] + d3905.n[1] * 3.2; pf.look = d3905.c; }
  const jumps = jumpMeta(data.sled.jumps, terrain);

  // ---------------------------------------------------------------- worlds (lazy per season)
  let placeholder = null;
  const worlds = {};
  async function worldFor(season, onProg) {
    if (worlds[season]) return worlds[season];
    const entry = manifest.worlds && manifest.worlds[season];
    if (entry) {
      try {
        worlds[season] = await loadGLBWorld(entry, season, ctx, onProg);
        return worlds[season];
      } catch (e) { console.warn(`world_${season}.glb failed — using the placeholder world`, e); }
    }
    if (!placeholder) placeholder = buildPlaceholder(ctx);
    worlds[season] = placeholder;
    return placeholder;
  }
  let season = params.get('season') === 'winter' || params.get('season') === 'summer' ? params.get('season') : store.get('season', 'summer');
  if (!SEASONS[season]) season = 'summer';
  progress(0.2, season === 'winter' ? 'Snowing on Canby Court…' : 'Building Canby Court…');
  let world = await worldFor(season, (e) => { if (e && e.total) progress(0.2 + 0.5 * e.loaded / e.total, `World ${(e.loaded / 1048576).toFixed(1)} / ${(e.total / 1048576).toFixed(1)} MB`); });
  scene.add(world.root);
  world.setSeason(season);
  let col = world.colliderFor(season);

  progress(0.72, 'Getting dressed…');
  const person = new Character();
  await person.load(manifest, (e) => { if (e && e.total) progress(0.72 + 0.15 * e.loaded / e.total, 'Character…'); });
  scene.add(person.root, person.sledRoot);
  person.setSeason(season);

  // ---------------------------------------------------------------- lighting, sky, effects
  const sky = new Sky(renderer, scene);
  const treeline = buildTreeline(terrain);
  scene.add(treeline);
  const snow = new Snowfall(QUALITY.high.snow);
  const puffs = new Puffs(300);
  const trail = new Trail(700);
  const prints = new Footprints(360);
  scene.add(snow.points, puffs.points, trail.mesh, prints.mesh);
  const sound = new Sound();
  // summer grass tufts on the placeholder lawns
  let grass = null;
  try { if (surfImg) { grass = new Grass(terrain, surfImg, manifest.surface, 7000); scene.add(grass.mesh); } } catch (e) { console.warn('grass disabled', e); grass = null; }

  const ctrl = new Controller(col);
  const follow = new FollowCamera(camera, col.bvh);
  follow.minDist = 1.6; follow.maxDist = 18;
  const chase = new ChaseCamera(camera, col.bvh);
  const game = new SledGame({ jumps, berm: data.sled.berm, path: data.sled.path, onEvent: (e) => onSledEvent(e) });
  game.setCollider(col);

  function applySeasonLook(s) {
    sky.setSeason(s);
    if (post) {
      const G = SEASONS[s].grade, u = post.grade.material.uniforms;
      u.uSat.value = G.sat; u.uContrast.value = G.contrast; u.uShadowTint.value.set(...G.shadow); u.uHighTint.value.set(...G.high);
    }
    SU.uSeason.value = s === 'winter' ? 1 : 0;
    snow.points.visible = s === 'winter';
    if (grass) grass.mesh.visible = s === 'summer' && world.kind === 'placeholder' && !!Q.grass;
    prints.mesh.visible = s === 'winter';
    trail.mesh.visible = s === 'winter';
    sound.season = s;
    document.body.classList.toggle('winter', s === 'winter');
    $('btn-season').setAttribute('aria-label', s === 'winter' ? 'Switch to summer' : 'Switch to winter');
    $('btn-season').title = s === 'winter' ? 'Switch to summer' : 'Switch to winter';
    if (minimap) minimap.season = s;
    shadowDirty = true;
  }
  let minimap = null, post = null;
  let shadowDirty = true;
  applySeasonLook(season);

  // ---------------------------------------------------------------- post
  post = new Post(renderer, scene, camera);
  applySeasonLook(season);
  let useComposer = false;
  const setupComposer = () => { useComposer = !!Q.post; post.configure({ ...Q, bloom: Q.bloom && bloomAllowed }); post.bloom.strength = 0.12; post.bloom.threshold = 0.92; };
  const photo = { on: false };
  const adapt = { peak: 0, good: 0, cooldown: 0, skip: 1, reset() { this.good = 0; this.cooldown = 0; this.skip = 1; } };
  function resize() {
    const w = innerWidth, h = innerHeight, pr = Math.max(0.5, baseDpr() * dprScale);
    renderer.setPixelRatio(pr); renderer.setSize(w, h);
    camera.aspect = w / h; camera.updateProjectionMatrix();
    post.setSize(w, h, pr);
    if (minimap) minimap.resize();
  }
  addEventListener('resize', resize);
  function applyQuality() {
    Q = photo.on ? QUALITY.ultra : (QUALITY[qualityPref === 'auto' ? autoQ : qualityPref] || QUALITY[autoQ]);
    cc.tier = photo.on ? 'ultra' : (qualityPref === 'auto' ? autoQ : qualityPref);
    dprScale = fixedScale || 1; bloomAllowed = true; adapt.reset();
    snow.setCount(Q.snow);
    if (world.setDetail) world.setDetail(cc.tier);
    if (grass) { grass.setMax(isMobile ? 2500 : 7000); grass.mesh.visible = season === 'summer' && world.kind === 'placeholder' && !!Q.grass; }
    renderer.shadowMap.enabled = Q.shadows; sky.sun.castShadow = Q.shadows;
    shadowDirty = true;
    setupComposer(); resize();
    document.querySelectorAll('.seg button').forEach((b) => b.setAttribute('aria-checked', String(b.dataset.q === qualityPref)));
  }
  applyQuality();

  // ---------------------------------------------------------------- UI
  const input = new Input(canvas, { joy: $('joy'), knob: $('joy-knob') });
  minimap = new MiniMap($('minimap'), $('minimap-wrap'), data, surfImg, manifest.surface);
  minimap.season = season;
  if (isTouch) document.body.classList.add('touch');
  const panels = ['panel-places', 'panel-settings', 'panel-info'];
  const btnFor = { 'panel-places': 'btn-places', 'panel-settings': 'btn-settings', 'panel-info': 'btn-info' };
  function openPanel(id) {
    for (const p of panels) {
      const on = p === id && $(p).hidden;
      $(p).hidden = !on; $(btnFor[p]).setAttribute('aria-expanded', String(on));
      if (on) { const h = $(p).querySelector('h2'); if (h) { h.tabIndex = -1; h.focus({ preventScroll: true }); } }
    }
    $('minimap-wrap').hidden = panels.some((p) => !$(p).hidden);
  }
  function closePanels() {
    let was = null;
    for (const p of panels) { if (!$(p).hidden) was = p; $(p).hidden = true; $(btnFor[p]).setAttribute('aria-expanded', 'false'); }
    $('minimap-wrap').hidden = false;
    if (was && $(was).contains(document.activeElement)) $(btnFor[was]).focus({ preventScroll: true });
  }
  $('btn-places').onclick = () => openPanel('panel-places');
  $('btn-settings').onclick = () => openPanel('panel-settings');
  $('btn-info').onclick = () => openPanel('panel-info');
  document.querySelectorAll('[data-close]').forEach((b) => (b.onclick = closePanels));
  canvas.addEventListener('pointerdown', closePanels);
  document.querySelectorAll('.seg button').forEach((b) => (b.onclick = () => { qualityPref = b.dataset.q; store.set('quality', qualityPref); applyQuality(); }));
  $('btn-sound').onclick = () => {
    if (sound.on) { sound.stop(); } else if (!sound.start()) { toast('Sound is not available in this browser.'); }
    $('btn-sound').setAttribute('aria-pressed', String(sound.on));
    $('btn-sound').textContent = sound.on ? 'Sound on — tap to mute' : 'Sound off — tap to turn on';
  };
  $('info-world').textContent = (manifest.worlds && (manifest.worlds.summer || manifest.worlds.winter))
    ? 'Scene: art-pass GLB worlds (Blender), see docs/scene.md.'
    : 'Scene: procedural stand-in built in the browser from the survey data (the detailed art pass is not published yet).';

  for (const p of PLACES) {
    const li = document.createElement('li'), b = document.createElement('button');
    b.innerHTML = '<span class="pl-en"></span><span class="pl-sub"></span>';
    b.querySelector('.pl-en').textContent = p.en; b.querySelector('.pl-sub').textContent = p.sub;
    b.onclick = () => { closePanels(); if (mode === 'sled') exitSled(); teleport(p); if (p.sledHere) toast(season === 'winter' ? 'Press “Sled” to ride the run.' : 'Sledding needs snow — switch to winter (❄ button).', 4); };
    li.appendChild(b); $('places-list').appendChild(li);
  }

  const runBtn = $('btn-run');
  if (isTouch) runBtn.hidden = false;
  const toggleRun = () => { input.runToggle = !input.runToggle; runBtn.setAttribute('aria-pressed', String(input.runToggle)); };
  runBtn.addEventListener('pointerdown', (e) => e.preventDefault());
  runBtn.addEventListener('pointerup', (e) => { e.preventDefault(); toggleRun(); });
  runBtn.addEventListener('click', (e) => { if (e.detail === 0) toggleRun(); });

  const hint = $('hint');
  const walkHint = isTouch ? 'Left thumb: walk · drag right: look · pinch: zoom' : 'WASD: walk · Shift: run · Space: jump · drag: look';
  hint.textContent = walkHint;
  let hintTimer = 0;
  let toastT = 0;
  function toast(msg, secs = 3.5) { const t = $('toast'); if (t.textContent !== msg) t.textContent = msg; t.hidden = false; toastT = secs; }

  // ---------------------------------------------------------------- teleport
  const teleportLog = {};
  function teleport(p) {
    const x = p.x, z = -p.n;
    const spot = ctrl.findSpot(x, z, 6) || ctrl.findSpot(x, z, 25);
    let pos;
    if (spot) pos = spot.pos;
    else { const g = ctrl.dropTo(x, z); pos = new THREE.Vector3(x, g ? g.y : terrain.height(x, p.n), z); }
    const facing = Math.atan2(p.look[0] - pos.x, -p.look[1] - pos.z);
    ctrl.teleport(pos, facing);
    person.renderY = null;
    follow.pitch = p.pitch ?? 0.12; follow.dist = p.dist ?? 5.5;
    follow.snap(pos, facing + Math.PI);
    prints.last = null;
    teleportLog[p.id || 'xy'] = { requested: [p.x, p.n], placed: [+pos.x.toFixed(2), +(-pos.z).toFixed(2), +pos.y.toFixed(2)], offset: spot ? spot.offset : null, ground: spot ? spot.ground : null };
    return teleportLog[p.id || 'xy'];
  }

  // ---------------------------------------------------------------- season switch (fade)
  let switching = false;
  async function setSeason(s, { fade = true } = {}) {
    if (s === season || switching || !SEASONS[s]) return;
    switching = true;
    if (mode === 'sled') exitSled();
    document.body.classList.toggle('to-summer', s === 'summer');
    if (fade) { $('fade').classList.add('on'); await new Promise((r) => setTimeout(r, 480)); }
    try {
      const w = await worldFor(s);
      if (w !== world) { scene.remove(world.root); scene.add(w.root); world = w; }
      world.setSeason(s);
      if (world.setDetail) world.setDetail(cc.tier);
      col = world.colliderFor(s);
      ctrl.setCollider(col); follow.bvh = col.bvh; chase.bvh = col.bvh; game.setCollider(col);
      season = s; store.set('season', s);
      person.setSeason(s);
      applySeasonLook(s);
      trail.clear(); prints.clear();
      // re-seat the walker on the new ground
      const g = ctrl.dropTo(ctrl.pos.x, ctrl.pos.z, ctrl.pos.y + 3);
      if (g) ctrl.pos.y = g.y;
      if (!ctrl.capsuleFree(ctrl.pos)) { const sp = ctrl.findSpot(ctrl.pos.x, ctrl.pos.z, 12); if (sp) ctrl.pos.copy(sp.pos); }
      ctrl.grounded = true; person.renderY = null;
      if (renderer.compileAsync) await renderer.compileAsync(scene, camera).catch(() => {});
    } finally {
      if (fade) $('fade').classList.remove('on');
      switching = false;
    }
    toast(s === 'winter' ? 'Winter — fresh snow on Canby Court. Sled from the top of the bulb!' : 'Summer — a warm July evening.', 3.5);
  }
  $('btn-season').onclick = () => setSeason(season === 'winter' ? 'summer' : 'winter');

  // ---------------------------------------------------------------- sled mode
  let mode = 'walk';
  let autopilot = null;
  const startLocal = data.sled.start.center_local, startYaw = yawFromHeading(data.sled.start.heading_deg);
  let best = parseInt(store.get('best', '0'), 10) || 0;
  $('s-best').textContent = best ? String(best) : '–';
  function enterSled() {
    if (season !== 'winter') { toast('Sledding needs snow — switch to winter first.'); return; }
    closePanels(); $('panel-finish').hidden = true;
    mode = 'sled';
    document.body.classList.add('sledding');
    $('sled-hud').hidden = false; $('btn-sled').hidden = true; runBtn.hidden = true;
    person.setMode('sled');
    trail.clear();
    game.startAt(startLocal, terrain.height(startLocal[0], startLocal[1]), startYaw);
    chase.reset(game.pos, game.heading);
    chase.update(0, game.pos, game.vel, game.heading, false, performance.now());
    hint.hidden = false; hint.classList.remove('fade');
    hint.textContent = isTouch ? 'Left thumb: steer (down = brake) · POP at the lip · tricks in the air' : 'A/D steer · S brake · Space pop at the lip · 1/2/3 tricks · R restart · Esc walk';
    hintTimer = 0;
    shadowDirty = true;
  }
  function exitSled() {
    if (mode !== 'sled') return;
    mode = 'walk';
    game.active = false; autopilot = null;
    document.body.classList.remove('sledding');
    $('sled-hud').hidden = true; $('panel-finish').hidden = true;
    if (isTouch) runBtn.hidden = false;
    person.setMode('walk');
    // stand up next to the sled
    const p = game.pos.clone();
    const spot = ctrl.findSpot(p.x + Math.cos(game.heading) * 0.9, p.z - Math.sin(game.heading) * 0.9, 6);
    ctrl.teleport(spot ? spot.pos : p, game.heading);
    follow.snap(ctrl.pos, game.heading + Math.PI);
    camera.fov = 55; camera.updateProjectionMatrix();
    hint.textContent = walkHint;
    shadowDirty = true;
  }
  $('btn-sled').onclick = enterSled;
  $('sled-exit').onclick = exitSled;
  $('sled-restart').onclick = () => { $('panel-finish').hidden = true; trail.clear(); game.restartRun(); chase.reset(game.pos, game.heading); };
  $('f-again').onclick = () => { $('panel-finish').hidden = true; trail.clear(); game.restartRun(); chase.reset(game.pos, game.heading); };
  $('f-walk').onclick = exitSled;
  // on-screen sled buttons: pointerdown (works while the other thumb steers)
  const press = (el, fn) => {
    el.addEventListener('pointerdown', (e) => { e.preventDefault(); e.stopPropagation(); el.classList.add('active'); fn(); });
    const up = () => el.classList.remove('active');
    el.addEventListener('pointerup', up); el.addEventListener('pointercancel', up); el.addEventListener('pointerleave', up);
    el.addEventListener('click', (e) => { if (e.detail === 0) fn(); });
  };
  press($('s-boost'), () => input.press('space'));
  document.querySelectorAll('.trick-btn').forEach((b) => press(b, () => input.press('trick:' + b.dataset.trick)));

  // sled HUD messages
  let popTimer = null;
  function popMsg(text, fail = false) {
    const el = $('s-pop');
    el.classList.remove('show', 'fail'); void el.offsetWidth;
    el.textContent = text; el.classList.add('show'); if (fail) el.classList.add('fail');
    clearTimeout(popTimer); popTimer = setTimeout(() => el.classList.remove('show'), 1700);
  }
  const tmpV = new THREE.Vector3();
  function spray(n, speed = 2, size = 0.12) {
    for (let i = 0; i < n; i++) {
      tmpV.set((Math.random() - 0.5) * speed, Math.random() * speed * 0.8, (Math.random() - 0.5) * speed).addScaledVector(game.vel, 0.3);
      puffs.emit(game.pos, tmpV, { life: 0.9, size, grow: 0.6, alpha: 0.65, drag: 2.5, grav: 3, jitter: 0.6 });
    }
  }
  function onSledEvent(e) {
    switch (e.type) {
      case 'go': popMsg('Go!'); sound.cue('go'); break;
      case 'pop': if (e.label !== 'Ollie') { popMsg(`${e.label} +${e.points}`); sound.cue('pop'); } break;
      case 'trick-start': sound.cue('trick'); break;
      case 'trick-done': popMsg(`${e.label}${e.combo > 1 ? ' ×' + e.combo : ''}${e.sketchy ? ' (sketchy)' : ''}\n+${e.points}`); break;
      case 'land': popMsg(`Clean landing! +${e.points}\n${e.airtime.toFixed(2)} s air`); spray(14, 2.5); sound.cue('land'); trail.break(); break;
      case 'wipeout': popMsg(`Wipeout!\n${e.reason}`, true); spray(30, 3.5, 0.2); sound.cue('wipeout'); trail.break(); break;
      case 'respawn': popMsg('Back to the checkpoint'); chase.reset(game.pos, game.heading); trail.break(); break;
      case 'bump': sound.cue('bump'); break;
      case 'hay': spray(20, 2.5, 0.2); break;
      case 'finish': {
        const f = e;
        if (f.score > best) { best = f.score; store.set('best', String(best)); }
        $('s-best').textContent = best ? String(best) : '–';
        $('f-title').textContent = f.overrun ? 'Into 38th St — too far!' : 'Run complete';
        $('f-score').textContent = String(f.score); $('f-time').textContent = f.time.toFixed(1) + ' s';
        $('f-speed').textContent = Math.round(game.maxSpeed * 3.6) + ' km/h'; $('f-best').textContent = String(best);
        const ul = $('f-jumps'); ul.textContent = '';
        for (const j of game.jumpLog.filter((x) => x.jump)) {
          const li = document.createElement('li');
          const jm = jumps.find((q) => q.id === j.jump);
          li.textContent = `${jm ? jm.label : j.jump}: ${j.airtime.toFixed(2)} s air${j.pop ? ', ' + j.pop.label.toLowerCase() : ''}${j.tricks.length ? ', ' + j.tricks.map((t) => t.label).join(' + ') : ''} — ${j.clean ? j.points + ' pts' : 'wipeout'}`;
          ul.appendChild(li);
        }
        setTimeout(() => { if (mode === 'sled' && game.finished) $('panel-finish').hidden = false; }, 900);
        break;
      }
      default: break;
    }
  }

  // ---------------------------------------------------------------- photo mode
  function setPhoto(on) {
    if (photo.on === on) return;
    photo.on = on; $('hud').hidden = on; $('photo-bar').hidden = !on;
    if (!on) person.root.visible = true;
    applyQuality(); shadowDirty = true;
    if (on) $('photo-save').focus({ preventScroll: true }); else $('btn-photo').focus({ preventScroll: true });
  }
  $('btn-photo').onclick = () => { closePanels(); setPhoto(true); };
  $('photo-exit').onclick = () => setPhoto(false);
  $('photo-person').onclick = () => { person.root.visible = !person.root.visible; $('photo-person').setAttribute('aria-pressed', String(person.root.visible)); shadowDirty = true; };
  $('photo-save').onclick = () => {
    photo.capture = () => renderer.domElement.toBlob((blob) => {
      if (!blob) return;
      const a = document.createElement('a'); a.href = URL.createObjectURL(blob);
      a.download = `canby-court-${season}-${new Date().toISOString().slice(0, 19).replace(/[:T]/g, '-')}.png`;
      document.body.appendChild(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(a.href), 4000);
    }, 'image/png');
  };
  canvas.addEventListener('pointerdown', () => { if (photo.on) $('photo-bar').classList.toggle('dim'); });
  addEventListener('keydown', (e) => {
    if (e.key !== 'Escape') return;
    if (photo.on) setPhoto(false); else if (mode === 'sled') exitSled(); else closePanels();
  });

  // ---------------------------------------------------------------- loop
  const clock = new THREE.Clock();
  let frames = 0, fpsStart = performance.now(), mmT = 0, zoneT = 0, breathT = 1.5, frameErrors = 0, stopped = false, lastShadowY = NaN;
  const fpsHistory = [];
  const fwd = new THREE.Vector3(), right = new THREE.Vector3(), mv = new THREE.Vector3(), head = new THREE.Vector3(), tv = new THREE.Vector3();
  function frame() {
    if (stopped) return;
    requestAnimationFrame(frame);
    try { step(); frameErrors = 0; } catch (e) {
      frameErrors++; console.error(e); cc.errors.push(String(e && e.stack || e));
      if (frameErrors >= 5) { stopped = true; fatal('Sorry — Canby Court stopped because of an error: ' + describe(e)); }
    }
  }
  function step() {
    const dt = Math.min(clock.getDelta(), cc.maxDt);
    cc.simTime = (cc.simTime || 0) + dt;
    const now = performance.now();
    const inp = input.sample();
    SU.uTime.value += dt;
    let focus;
    if (mode === 'walk') {
      if (inp.look.x || inp.look.y) follow.look(inp.look.x, inp.look.y, now);
      if (inp.zoom !== 1) follow.zoom(inp.zoom);
      if (inp.pressed.includes('space') && ctrl.jump(4.2)) person._jumpStart = now;
      fwd.copy(follow.forward); right.set(-fwd.z, 0, fwd.x);
      mv.set(0, 0, 0).addScaledVector(fwd, inp.y).addScaledVector(right, inp.x);
      const sub = Math.max(1, Math.ceil(dt / (1 / 60)));
      for (let i = 0; i < sub; i++) { ctrl.update(dt / sub, mv, inp.run); if (cc.groundTrace) cc.groundTrace.add(ctrl.groundName); }
      person.updateWalk(dt * cc.animScale, ctrl.pos, ctrl.facing, ctrl.speed, ctrl.grounded);
      follow.update(dt, person.root.position, ctrl.facing, ctrl.speed > 0.3, now, input.touchMode);
      focus = ctrl.pos;
      if (season === 'winter' && ctrl.grounded && ctrl.speed > 0.3) prints.step(ctrl.pos, ctrl.facing, ctrl.groundNormal);
      // sled button near the top of the run (winter)
      const nearTop = season === 'winter' && Math.hypot(ctrl.pos.x - startLocal[0], -ctrl.pos.z - startLocal[1]) < 16;
      if ($('btn-sled').hidden === nearTop) $('btn-sled').hidden = !nearTop;
      if (ctrl.edgeWarn) toast('The surveyed area ends here — Bellingham continues beyond.', Math.max(toastT, 1.2));
      if (ctrl.speed > 0.02 || !ctrl.grounded || Math.abs(person.root.position.y - lastShadowY) > 0.002) shadowDirty = true;
      lastShadowY = person.root.position.y;
    } else {
      // sled controls
      for (const k of inp.pressed) {
        if (k === 'space') { const r = game.boost(); if (r === 'missed' || r === 'used') { /* no-op */ } }
        else if (k === '1' || k === 'trick:superman') game.trickPress('superman');
        else if (k === '2' || k === 'trick:spread_eagle') game.trickPress('spread_eagle');
        else if (k === '3' || k === 'trick:grab') game.trickPress('grab');
        else if (k === 'r') { $('panel-finish').hidden = true; trail.clear(); game.restartRun(); chase.reset(game.pos, game.heading); }
      }
      if (inp.look.x || inp.look.y) chase.glance(inp.look.x, inp.look.y, now);
      let steer = inp.kx, brake = inp.ky < 0 ? 1 : 0, paddle = inp.ky > 0 ? 1 : 0;
      if (input.joy.id !== null) {
        steer = clamp(input.joy.x * 1.25, -1, 1);
        brake = input.joy.y < -0.45 ? clamp((-input.joy.y - 0.45) * 2, 0, 1) : 0;
        paddle = input.joy.y > 0.45 ? 1 : 0;
      }
      let sin = { steer, brake, paddle };
      if (autopilot) {
        // autopilot drives the game in its own sub-steps so it can act at the right moment
        let t = dt; while (t > 1e-6) { const h = Math.min(1 / 120, t); sin = autopilot.input(); game.step(h, sin); t -= h; }
      } else game.update(dt, sin);
      person.updateSled(dt * cc.animScale, game, sin.steer);
      chase.update(dt, game.wipe ? game.wipe.riderPos : game.pos, game.vel, game.heading, !game.grounded, now);
      focus = game.pos;
      // effects: track ribbon, skid spray
      if (game.grounded && !game.wipe && game.started) {
        tv.set(Math.sin(game.heading), 0, Math.cos(game.heading));
        trail.add(game.pos, tv, game.normal, 1);
        const sp = game.vel.length();
        if (game.skid > 0.15 || (sp > 6 && Math.random() < 0.15)) spray(game.skid > 0.15 ? 3 : 1, 1.6 + game.skid * 2, 0.1);
      }
      sledHud();
      shadowDirty = true;
    }
    // breath puffs in winter
    if (season === 'winter' && !photo.on) {
      breathT -= dt;
      if (breathT <= 0) {
        breathT = 3.2 + Math.random() * 1.2;
        person.headWorld(head);
        const f = mode === 'sled' ? tv.set(Math.sin(game.heading), 0, Math.cos(game.heading)) : tv.set(Math.sin(ctrl.facing), 0, Math.cos(ctrl.facing));
        head.addScaledVector(f, 0.14); head.y -= 0.04;
        for (let i = 0; i < 4; i++) puffs.emit(head, f.clone().multiplyScalar(0.35).add(mode === 'sled' ? game.vel : ctrl.vel), { life: 1.4, size: 0.08, grow: 0.35, alpha: 0.22, drag: 2.2, grav: -0.08, jitter: 0.08 });
      }
    }
    if (season === 'winter') snow.update(dt, camera, renderer.domElement.height);
    else if (grass && grass.mesh.visible) grass.update(camera.position);
    puffs.update(dt, camera, renderer.domElement.height);
    if (Q.shadows && sky.placeShadow(focus, Q.shadowRange, Q.shadow)) shadowDirty = true;
    if (sky.shadowDirty) { shadowDirty = true; sky.shadowDirty = false; }
    if (shadowDirty && Q.shadows) { renderer.shadowMap.needsUpdate = true; shadowDirty = false; }
    sky.update(dt, camera);
    sound.update(dt, { speed: mode === 'sled' ? game.vel.length() : ctrl.speed, sledding: mode === 'sled' && game.started && !game.finished, airborne: !game.grounded, skid: game.skid });

    if (toastT > 0) { toastT -= dt; if (toastT <= 0) $('toast').hidden = true; }
    if (input.anyInput && (mode === 'walk' ? ctrl.speed > 0.2 : game.started) && !hint.classList.contains('fade')) {
      hintTimer += dt;
      if (hintTimer > (mode === 'walk' ? 5 : 7)) { hint.classList.add('fade'); }
    }
    mmT -= dt;
    if (mmT <= 0) {
      mmT = 0.1;
      const p = mode === 'walk' ? ctrl.pos : game.pos;
      minimap.draw(p.x, -p.z, mode === 'walk' ? ctrl.facing : game.heading, follow.yaw, mode === 'sled');
    }
    zoneT -= dt;
    if (zoneT <= 0) {
      zoneT = 0.5;
      const p = mode === 'walk' ? ctrl.pos : game.pos;
      const z = ZONES.find((zz) => zz.test(p.x, -p.z));
      const label = `${z.en} · ${SEASONS[season].label}`;
      if ($('place-name').textContent !== label) $('place-name').textContent = label;
    }
    if (useComposer) post.draw(dt); else renderer.render(scene, camera);
    if (photo.capture) { const cb = photo.capture; photo.capture = null; cb(); }

    frames++;
    const el = (now - fpsStart) / 1000;
    if (el >= 2) {
      const fps = frames / el; fpsStart = now; frames = 0;
      cc.fps = Math.round(fps * 10) / 10;
      fpsHistory.push(cc.fps); if (fpsHistory.length > 30) fpsHistory.shift();
      if (adapt.skip > 0) adapt.skip--;
      else if (qualityPref === 'auto' && !photo.on && !fixedScale) {
        adapt.peak = Math.max(fps, adapt.peak * 0.98);
        const target = isMobile ? 30 : 55;
        if (adapt.cooldown > 0) adapt.cooldown--;
        if (fps < target * 0.85) {
          adapt.good = 0;
          if (dprScale > 0.6) { dprScale = Math.max(0.6, dprScale - 0.1); resize(); adapt.cooldown = 3; adapt.skip = 1; }
          else if (Q.bloom && bloomAllowed) { bloomAllowed = false; setupComposer(); }
          else if (post.gtao.enabled) post.gtao.enabled = false;
        } else if (dprScale < 1 && fps >= target && (fps >= adapt.peak * 0.92 || fps > target * 1.3)) {
          if (++adapt.good >= 2 && adapt.cooldown === 0) { dprScale = Math.min(1, dprScale + 0.05); resize(); adapt.good = 0; adapt.skip = 1; }
        } else adapt.good = 0;
      }
      const info = renderer.info.render;
      $('perf-line').textContent = `${cc.fps} fps · ${Math.round(renderer.getPixelRatio() * 100) / 100}× px · ${info.calls} draws · ${(info.triangles / 1000).toFixed(0)}k tris · ${world.kind} world`;
    }
  }

  let lastHud = 0;
  function sledHud() {
    const now = performance.now();
    if (now - lastHud < 80) return;
    lastHud = now;
    const sp = game.vel.length();
    $('s-speed').textContent = String(Math.round(sp * 3.6));
    $('s-time').textContent = game.runTime.toFixed(1);
    $('s-score').textContent = String(game.score);
    $('s-air').textContent = !game.grounded && game.airTime > 0.15 && !game.wipe ? `air ${game.airTime.toFixed(1)} s` : '';
    $('s-prog').style.width = Math.round(clamp(game.arc / game.path.length, 0, 1) * 100) + '%';
    const cd = game.countdown > 0 ? String(Math.ceil(game.countdown / 0.8)) : '';
    if ($('s-count').textContent !== cd) $('s-count').textContent = cd;
    const r = game.grounded && !game.popUsed ? game.onRamp() : null;
    $('s-boost').classList.toggle('ready', !!r);
    document.querySelectorAll('.trick-btn').forEach((b) => b.classList.toggle('active', game.trick && game.trick.name === b.dataset.trick));
  }

  document.addEventListener('visibilitychange', () => {
    if (document.hidden) input.clear(); else { clock.getDelta(); frames = 0; fpsStart = performance.now(); adapt.skip = 1; }
  });

  // ---------------------------------------------------------------- start
  const spawn = teleport(SPAWN);
  progress(0.95, 'Preparing shaders…');
  try {
    sky.update(0, camera);
    follow.update(0, person.root.position, ctrl.facing, false, performance.now());
    if (renderer.compileAsync) await renderer.compileAsync(scene, camera);
  } catch (e) { console.warn('shader prewarm skipped', e); }
  progress(1, 'Ready');
  $('hud').hidden = false;
  minimap.resize();
  $('loading').classList.add('done');
  setTimeout(() => { $('loading').hidden = true; }, 700);
  canvas.tabIndex = 0;
  requestAnimationFrame(frame);

  // ---------------------------------------------------------------- test hooks
  Object.assign(cc, {
    ready: true, THREE, scene, camera, renderer, ctrl, follow, chase, sky, person, input, game, post, terrain, data, jumps, manifest,
    teleport: (id) => teleport(typeof id === 'string' ? PLACES.find((p) => p.id === id) : id), teleportLog, spawn, places: PLACES, fpsHistory, isMobile, isTouch,
    setSeason, enterSled, exitSled, setPhoto,
    season: () => season, mode: () => mode, world: () => ({ kind: world.kind, hasKickers: world.hasKickers ?? true, tris: col.tris, bvhMs: col.buildMs, instanced: world.instanced || 0, colliders: col.objInfo.length }),
    state: () => ({
      x: +ctrl.pos.x.toFixed(3), n: +(-ctrl.pos.z).toFixed(3), y: +ctrl.pos.y.toFixed(3), grounded: ctrl.grounded, ground: ctrl.groundName,
      speed: +ctrl.speed.toFixed(2), facing: +ctrl.facing.toFixed(3), wall: ctrl.wallContact, camYaw: +follow.yaw.toFixed(3), mode, season,
    }),
    sled: () => game.summary(),
    autopilot: (opts) => { autopilot = opts ? new Autopilot(game, opts) : null; return !!autopilot; },
    // headless run with the same physics/collider: {pop, tricks: {jump_3_big: 'superman'}}
    simulate: (opts = {}) => {
      const g2 = new SledGame({ jumps, berm: data.sled.berm, path: data.sled.path });
      g2.setCollider(world.colliderFor('winter'));
      const s = simulate(g2, startLocal, terrain.height(startLocal[0], startLocal[1]), startYaw, opts, opts.maxT || 60);
      s.events = g2.events.filter((e) => e.type !== 'checkpoint');
      return s;
    },
    probe: (x, n) => { const g = ctrl.dropTo(x, -n); return g && { y: g.y, ny: g.normal.y, name: g.info.name, walkable: g.info.walkable }; },
    quality: () => ({ pref: qualityPref, tier: cc.tier, dprScale, pixelRatio: renderer.getPixelRatio(), shadow: Q.shadow }),
    stats: () => ({ calls: renderer.info.render.calls, tris: renderer.info.render.triangles, world: world.kind, character: person.isGLB ? 'glb' : 'placeholder', clips: Object.keys(person.actions) }),
  });
}

main().catch((e) => {
  console.error(e);
  cc.errors.push(String(e && e.stack || e));
  if ($('fatal').hidden) fatal('Sorry — Canby Court could not be loaded: ' + describe(e));
});
