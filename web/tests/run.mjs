// End-to-end tests (Playwright, headless Chromium + SwiftShader WebGL).
//   node tests/run.mjs [outDir]
// Desktop 1440x900 + iPhone 13 + Pixel 7 emulation: load, screenshots, real keyboard / touch-joystick input,
// climbing Ninenzaka steps (OSM 30882783) and Sannenzaka stairs (OSM 179116810), wall blocking, teleports,
// console errors and external requests, FPS log. Writes results.json next to the screenshots.
import fs from 'node:fs';
import path from 'node:path';
import { serve, launch, newPage, devices, sleep, WEB } from './harness.mjs';

const OUT = process.argv[2] || '/tmp/claude-0/-home-user/78aa4f15-d288-5fa7-835e-afbbfb9eb8f9/scratchpad/web';
fs.mkdirSync(OUT, { recursive: true });
const ONLY = process.env.ONLY || '';
const results = { desktop: {}, mobile: {}, failures: [] };
const check = (cond, msg) => { if (!cond) { results.failures.push(msg); console.log('  FAIL', msg); } else console.log('  ok  ', msg); };

const STEPS = JSON.parse(fs.readFileSync(path.join(WEB, '..', 'data', 'processed', 'steps.json'), 'utf8')).steps;
const stepOf = (id) => STEPS.find((s) => s.osm_id === id);

async function waitReady(page) {
  const t0 = Date.now();
  await page.waitForFunction(() => window.__hw && (window.__hw.ready || window.__hw.errors.length), null, { timeout: 300000 });
  const err = await page.evaluate(() => __hw.errors);
  if (err.length) throw new Error('page error: ' + err.join('\n'));
  await page.evaluate(() => { __hw.maxDt = 0.5; });
  return (Date.now() - t0) / 1000;
}
const state = (page) => page.evaluate(() => __hw.state());
async function frames(page, n = 2) {
  for (let i = 0; i < n; i++) await page.evaluate(() => new Promise((r) => requestAnimationFrame(() => r())));
}
async function shot(page, name) { await frames(page, 2); await page.screenshot({ path: path.join(OUT, name) }); console.log('  shot', name); }

// steer the camera (as a mouse-drag would) so that "forward" points at (x, n), local frame
async function steer(page, x, n) {
  await page.evaluate(([x, n]) => {
    const p = __hw.ctrl.pos; const dx = x - p.x, dz = -n - p.z;
    __hw.follow.yaw = Math.atan2(-dx, -dz); __hw.follow.lastLook = performance.now();
  }, [x, n]);
}

// hold W (or joystick) and steer along waypoints; returns track summary
async function walk(page, wps, { hold, release, maxWall = 240000, tol = 0.9, shotAt = -1, shotName = '' } = {}) {
  const t0 = Date.now();
  const track = []; const grounds = new Set();
  let i = 0, lastProgress = Date.now(), best = Infinity;
  await steer(page, ...wps[0]);
  await page.evaluate(() => { __hw.groundTrace = new Set(); });
  await hold();
  while (i < wps.length && Date.now() - t0 < maxWall) {
    await steer(page, ...wps[i]);
    await sleep(250);
    const s = await state(page);
    track.push([s.x, s.n, s.y]); grounds.add(s.ground);
    const d = Math.hypot(s.x - wps[i][0], s.n - wps[i][1]);
    if (d < tol) {
      i++; best = Infinity; lastProgress = Date.now();
      if (i === shotAt) await page.screenshot({ path: path.join(OUT, shotName) });
      continue;
    }
    if (d < best - 0.05) { best = d; lastProgress = Date.now(); }
    if (Date.now() - lastProgress > 40000) break; // stuck
  }
  await release();
  await frames(page, 2);
  const s = await state(page);
  for (const g of await page.evaluate(() => { const a = [...__hw.groundTrace]; __hw.groundTrace = null; return a; })) grounds.add(g);
  return { reached: i >= wps.length, waypointsDone: i, final: s, track, grounds: [...grounds], wallSeconds: (Date.now() - t0) / 1000 };
}

async function fpsWindow(page, seconds = 10) {
  await page.evaluate(() => { __hw._f = 0; __hw._t = performance.now(); (function c() { __hw._f++; if (!__hw._stop) requestAnimationFrame(c); })(); });
  await sleep(seconds * 1000);
  return page.evaluate(() => { __hw._stop = true; return +(__hw._f / ((performance.now() - __hw._t) / 1000)).toFixed(2); });
}

// ------------------------------------------------------------------ desktop
async function desktop(browser, url) {
  console.log('DESKTOP 1440x900');
  const { page, errors, ext, warnings } = await newPage(browser, { viewport: { width: 1440, height: 900 } });
  // hold the GLB back for a moment so the loading screen can be captured
  await page.route(/dist\/world(_art)?\.glb$/, async (r) => { await sleep(3000); await r.continue(); });
  await page.goto(url);
  await sleep(1800);
  await page.screenshot({ path: path.join(OUT, 'desktop_00_loading.png') });
  const R = results.desktop;
  R.loadSeconds = await waitReady(page);
  await sleep(1500);
  R.stats = await page.evaluate(() => __hw.stats());
  R.spawn = await state(page);
  check(Math.abs(R.spawn.x + 79) < 0.6 && Math.abs(R.spawn.n - 88.2) < 0.6, `spawn at Yasaka-dori (-79, 88.2): got (${R.spawn.x}, ${R.spawn.n})`);
  check(Math.abs(R.spawn.facing - Math.PI / 2) < 0.2, 'spawn faces east toward the pagoda');
  await shot(page, 'desktop_01_spawn.png');

  // teleports / walkability of every landmark
  R.places = {};
  for (const id of ['yasaka', 'gate', 'ninenzaka', 'ninen-steps', 'ichinenzaka', 'sannen-stairs', 'koshindo']) {
    const t = await page.evaluate((id) => __hw.teleport(__hw.places.find((p) => p.id === id)), id);
    R.places[id] = t;
    check(t.offset !== null && /Terrain|Steps|Paving/.test(t.ground), `place ${id}: walkable spot ${JSON.stringify(t.placed)} offset ${t.offset} m on ${t.ground}`);
  }
  R.probe = await page.evaluate(() => ({ gate: __hw.probe(-5, 75), koshindo: __hw.probe(-36, 66) }));

  // keyboard walk east on Yasaka-dori (real key events)
  await page.evaluate(() => __hw.teleport(__hw.places[0]));
  await frames(page, 2);
  const a = await state(page);
  await page.keyboard.down('w');
  await sleep(6000);
  await page.keyboard.up('w');
  await frames(page, 1);
  const b = await state(page);
  R.keyboardWalk = { from: a, to: b };
  check(b.x - a.x > 1.0, `W key walks forward (east) on Yasaka-dori: dx = ${(b.x - a.x).toFixed(2)} m`);
  await page.keyboard.down('Shift'); await page.keyboard.down('w');
  await sleep(4000);
  const sRun = await state(page);
  await page.keyboard.up('w'); await page.keyboard.up('Shift');
  R.runSpeed = sRun.speed;
  check(sRun.speed > 3, `Shift runs: speed ${sRun.speed} m/s`);
  await shot(page, 'desktop_02_yasaka_walk.png');

  // mouse drag orbit + wheel zoom
  const y0 = (await state(page)).camYaw;
  await page.mouse.move(700, 450); await page.mouse.down(); await page.mouse.move(560, 430, { steps: 4 }); await page.mouse.up();
  await frames(page, 1);
  const y1 = (await state(page)).camYaw;
  check(Math.abs(y1 - y0) > 0.3, `mouse drag orbits camera: yaw ${y0} -> ${y1}`);
  await page.mouse.wheel(0, 400); await frames(page, 3);
  R.zoomDist = (await state(page)).camDist;

  const hold = async () => page.keyboard.down('w');
  const release = async () => page.keyboard.up('w');

  // Ninenzaka steps (OSM 30882783): bottom is the north end, climb south
  const nin = stepOf(30882783);
  const ninWps = [[156.3, 44.5], ...nin.coords.map(([x, n]) => [x, n]), [151.6, 20.5]];
  await page.evaluate(() => __hw.teleport({ id: 't1', x: 156.6, n: 47, look: [155.9, 39.3] }));
  await frames(page, 2);
  const nStart = await state(page);
  const nw = await walk(page, ninWps, { hold, release, shotAt: 3, shotName: 'desktop_03a_ninenzaka_climbing.png' });
  R.ninenzakaSteps = { start: nStart, ...nw, z_bottom: nin.z_bottom, z_top: nin.z_top, track: undefined };
  check(nw.reached, `Ninenzaka steps: reached the top waypoint (${nw.waypointsDone}/${ninWps.length})`);
  check(nw.final.y > nin.z_top - 0.35, `Ninenzaka steps: climbed from ${nStart.y} to ${nw.final.y} m (top ${nin.z_top})`);
  check(nw.grounds.some((g) => /Steps_osm30882783/.test(g)), `Ninenzaka steps: walked on Steps_osm30882783 (${nw.grounds.join(', ')})`);
  // look back down the steps from the top
  await page.evaluate(() => { __hw.follow.yaw = Math.atan2(-(155.9 - __hw.ctrl.pos.x), -(-50 - __hw.ctrl.pos.z)) + Math.PI; __hw.follow.pitch = 0.32; __hw.follow.dist = 6; });
  await page.evaluate(() => __hw.ctrl.facing = Math.atan2(155.9 - __hw.ctrl.pos.x, -50 - __hw.ctrl.pos.z));
  await page.evaluate(() => { __hw.follow.yaw = __hw.ctrl.facing + Math.PI; });
  await sleep(1500);
  await shot(page, 'desktop_03_ninenzaka_steps.png');

  // Sannenzaka stairs (OSM 179116810): first coord is the top (south-west), climb from the bottom
  const san = stepOf(179116810);
  const sanWps = [...san.coords.slice().reverse().map(([x, n]) => [x, n]), [149.6, -181]];
  await page.evaluate(() => __hw.teleport(__hw.places.find((p) => p.id === 'sannen-stairs')));
  await frames(page, 2);
  const sStart = await state(page);
  const sw = await walk(page, sanWps, { hold, release, shotAt: 2, shotName: 'desktop_04a_sannenzaka_climbing.png' });
  R.sannenzakaStairs = { start: sStart, ...sw, z_bottom: san.z_bottom, z_top: san.z_top, track: undefined };
  check(sw.reached, `Sannenzaka stairs: reached the top waypoint (${sw.waypointsDone}/${sanWps.length})`);
  check(sw.final.y > san.z_top - 0.35, `Sannenzaka stairs: climbed from ${sStart.y} to ${sw.final.y} m (top ${san.z_top})`);
  check(sw.grounds.some((g) => /Steps_osm179116810/.test(g)), `Sannenzaka stairs: walked on Steps_osm179116810`);
  await page.evaluate(() => { __hw.ctrl.facing = Math.atan2(166.5 - __hw.ctrl.pos.x, 142 - __hw.ctrl.pos.z); __hw.follow.yaw = __hw.ctrl.facing + Math.PI; __hw.follow.pitch = 0.3; });
  await sleep(1500);
  await shot(page, 'desktop_04_sannenzaka_stairs.png');

  // walls block: from Yasaka-dori walk north into the facades for 6 s
  await page.evaluate(() => __hw.teleport(__hw.places[0]));
  await frames(page, 2);
  const w0 = await state(page);
  await steer(page, -79, 120);
  await page.keyboard.down('w'); await sleep(7000); await page.keyboard.up('w');
  await frames(page, 1);
  const w1 = await state(page);
  const free = await page.evaluate(() => __hw.ctrl.capsuleFree(__hw.ctrl.pos));
  R.wallBuilding = { from: w0, to: w1, capsuleFree: free };
  check(w1.n - w0.n < 4 && free, `building facade blocks: moved ${(w1.n - w0.n).toFixed(2)} m north, capsule free = ${free}`);

  // barrier (OSM wall) blocks: Kōshin-dō precinct fence/wall picked from collider data
  const bar = await page.evaluate(() => {
    // find a tall barrier collider triangle near a walkable spot and walk into it perpendicular
    const info = __hw.world.objInfo; const g = __hw.world.colGeom; const pos = g.attributes.position; const oid = g.attributes.objId; const idx = g.index;
    const T = __hw.THREE; const out = [];
    for (let f = 0; f < idx.count / 3 && out.length < 400; f += 7) {
      const a = idx.getX(f * 3); const o = info[Math.round(oid.getX(a))];
      if (!o || o.role !== 'barrier' || !/Barrier_(wall|retaining_wall)/.test(o.name)) continue;
      const A = new T.Vector3().fromBufferAttribute(pos, idx.getX(f * 3)), B = new T.Vector3().fromBufferAttribute(pos, idx.getX(f * 3 + 1)), C = new T.Vector3().fromBufferAttribute(pos, idx.getX(f * 3 + 2));
      const n = new T.Vector3().crossVectors(B.clone().sub(A), C.clone().sub(A)).normalize();
      if (Math.abs(n.y) > 0.2) continue;
      const mid = A.clone().add(B).add(C).multiplyScalar(1 / 3);
      if (Math.abs(mid.x) > 180 || Math.abs(mid.z) > 180) continue;
      out.push({ name: o.name, mid: [mid.x, mid.z], n: [n.x, n.z], top: Math.max(A.y, B.y, C.y) });
    }
    for (const c of out) {
      for (const sgn of [1, -1]) {
        const sx = c.mid[0] + c.n[0] * 2.2 * sgn, sz = c.mid[1] + c.n[1] * 2.2 * sgn;
        const s = __hw.ctrl.findSpot(sx, sz, 0.6);
        if (!s) continue;
        if (c.top < s.pos.y + 0.8) continue; // wall top must be well above the walker's feet (no step-up)
        return { ...c, start: [s.pos.x, -s.pos.z], side: sgn, feet: s.pos.y };
      }
    }
    return null;
  });
  if (bar) {
    await page.evaluate((b) => __hw.teleport({ id: 'bar', x: b.start[0], n: b.start[1], look: [b.mid[0], -b.mid[1]] }), bar);
    await frames(page, 2);
    await steer(page, bar.mid[0] - bar.n[0] * 3 * bar.side, -(bar.mid[1] - bar.n[1] * 3 * bar.side));
    await page.keyboard.down('w'); await sleep(6000); await page.keyboard.up('w');
    await frames(page, 1);
    const e = await state(page);
    const sideNow = Math.sign((e.x - bar.mid[0]) * bar.n[0] + (-e.n - bar.mid[1]) * bar.n[1]);
    R.wallBarrier = { barrier: bar, end: e, sideNow };
    check(sideNow === bar.side, `OSM wall ${bar.name} blocks the walker (stayed on its side)`);
  } else results.failures.push('no barrier test candidate found');

  // soft boundary: walk west along Matsubara-dori (OSM 27885660) past x = -200
  await page.evaluate(() => __hw.teleport({ id: 'edge', x: -188, n: -19, look: [-230, -18.3] }));
  await frames(page, 2);
  await steer(page, -230, -18.3);
  await page.keyboard.down('Shift'); await page.keyboard.down('w'); await sleep(9000);
  const eMid = await state(page);
  const toastShown = await page.isVisible('#toast');
  await page.screenshot({ path: path.join(OUT, 'desktop_10_boundary.png') });
  await page.keyboard.up('w'); await page.keyboard.up('Shift');
  R.boundary = { end: eMid, toast: toastShown };
  check(eMid.x >= -199.6 && eMid.x < -194, `soft boundary holds the walker inside the 400 m box (x = ${eMid.x})`);
  check(toastShown, 'boundary message shown');

  // pagoda view (from Kōshin-dō, ~47 m west of the tower) and at the gate
  await page.evaluate(() => { __hw.teleport(__hw.places.find((p) => p.id === 'koshindo')); __hw.follow.pitch = -0.22; __hw.follow.dist = 4.5; });
  await sleep(2500);
  await shot(page, 'desktop_05_pagoda.png');
  await page.evaluate(() => __hw.teleport(__hw.places.find((p) => p.id === 'gate')));
  await sleep(2000);
  await shot(page, 'desktop_05b_pagoda_gate.png');

  // blue hour on Ninenzaka with lanterns
  await page.evaluate(() => { __hw.setTime(0.95); __hw.teleport(__hw.places.find((p) => p.id === 'ninenzaka')); __hw.follow.pitch = 0.12; });
  await sleep(2500);
  await shot(page, 'desktop_06_ninenzaka_bluehour.png');
  await page.evaluate(() => { __hw.setTime(0.0); });
  await sleep(1500);
  await shot(page, 'desktop_07_ninenzaka_golden.png');

  // UI panels
  await page.click('#btn-info'); await sleep(400); await shot(page, 'desktop_08_info.png');
  await page.click('#btn-places'); await sleep(300); await shot(page, 'desktop_09_places.png');
  await page.keyboard.press('Escape');

  // fps (SwiftShader software GL: pessimistic) at the spawn
  await page.evaluate(() => { __hw.setTime(0.35); __hw.teleport(__hw.places[0]); });
  R.fps = { auto_high: await fpsWindow(page, 12), quality: await page.evaluate(() => __hw.quality()) };
  await page.click('#btn-settings'); await page.click('.seg button[data-q="low"]', { noWaitAfter: true }); await page.keyboard.press('Escape');
  await sleep(3000);
  R.fps.low = await fpsWindow(page, 12);
  await page.evaluate(() => document.querySelector('.seg button[data-q="auto"]').click());
  R.fps.renderInfo = await page.evaluate(() => __hw.stats());
  R.consoleErrors = errors; R.externalRequests = ext; R.warnings = warnings.filter((w) => !/GPU stall|GL Driver/.test(w)).slice(0, 10);
  check(errors.length === 0, `desktop: no console errors (${errors.length})`);
  check(ext.length === 0, `desktop: no external requests besides pinned CDN modules (${ext.join(', ')})`);
  await page.context().close();
}

// ------------------------------------------------------------------ mobile
async function touch(cdp, type, points) {
  await cdp.send('Input.dispatchTouchEvent', { type, touchPoints: points.map(([x, y], i) => ({ x, y, id: i + 1, radiusX: 4, radiusY: 4, force: 1 })) });
}

async function mobile(browser, url, devName, dev) {
  console.log('MOBILE', devName);
  const key = devName.replace(/\s+/g, '_');
  const { page, errors, ext } = await newPage(browser, { ...dev });
  const cdp = await page.context().newCDPSession(page);
  await page.goto(url);
  const R = (results.mobile[devName] = {});
  R.loadSeconds = await waitReady(page);
  await sleep(1500);
  R.viewport = page.viewportSize();
  R.noHScroll = await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth && document.body.scrollWidth <= innerWidth);
  check(R.noHScroll, `${devName}: no horizontal page scroll`);
  R.quality = await page.evaluate(() => __hw.quality());
  check(R.quality.pixelRatio <= 1.5 + 1e-6, `${devName}: pixel ratio capped at 1.5 (${R.quality.pixelRatio})`);
  R.runVisible = await page.isVisible('#btn-run');
  check(R.runVisible, `${devName}: run toggle visible on touch`);
  await shot(page, `mobile_${key}_01_spawn.png`);
  const { width: W, height: H } = R.viewport;

  // the (visible) hint strip must not block a joystick start on top of it
  const hb = await page.locator('#hint').boundingBox();
  if (hb) {
    await touch(cdp, 'touchStart', [[hb.x + 20, hb.y + hb.height / 2]]);
    R.joyOnHint = await page.evaluate(() => document.getElementById('joy').classList.contains('on'));
    await touch(cdp, 'touchEnd', []);
    check(R.joyOnHint, `${devName}: joystick starts on top of the hint strip`);
  }
  // look-drag starting in the gap between the title chip and the buttons
  const tb = await page.locator('.title-chip').boundingBox(), bb = await page.locator('.btn-row').boundingBox();
  if (tb && bb && bb.x - (tb.x + tb.width) > 6) {
    const gx = (tb.x + tb.width + bb.x) / 2, gy = tb.y + 10;
    const yA = (await state(page)).camYaw;
    await touch(cdp, 'touchStart', [[gx, gy]]);
    for (let i = 1; i <= 4; i++) await touch(cdp, 'touchMove', [[gx - i * 3, gy + i * 25]]);
    await touch(cdp, 'touchEnd', []);
    await frames(page, 1);
    const pB = await page.evaluate(() => __hw.follow.pitch);
    R.gapLook = { yA, pB };
    check(Math.abs(pB - 0.02) > 0.05, `${devName}: look-drag works from the top-bar gap (pitch ${pB.toFixed(2)})`);
  }

  // joystick (left thumb) forward = east
  await page.evaluate(() => __hw.teleport(__hw.places[0]));
  await frames(page, 1);
  const a = await state(page);
  const jx = W * 0.2, jy = H * 0.78;
  await touch(cdp, 'touchStart', [[jx, jy]]);
  await touch(cdp, 'touchMove', [[jx, jy - 30]]);
  await touch(cdp, 'touchMove', [[jx + 2, jy - 70]]);
  await sleep(300);
  await shot(page, `mobile_${key}_02_joystick.png`);
  for (let i = 0; i < 16; i++) { await touch(cdp, 'touchMove', [[jx + (i % 2), jy - 70]]); await sleep(400); }
  await touch(cdp, 'touchEnd', []);
  await frames(page, 1);
  const b = await state(page);
  R.joystick = { from: a, to: b };
  check(b.x - a.x > 1.0, `${devName}: joystick walks forward: dx = ${(b.x - a.x).toFixed(2)} m`);

  // right-side drag look
  const y0 = b.camYaw;
  await touch(cdp, 'touchStart', [[W * 0.75, H * 0.45]]);
  for (let i = 1; i <= 5; i++) await touch(cdp, 'touchMove', [[W * 0.75 - i * 20, H * 0.45]]);
  await touch(cdp, 'touchEnd', []);
  await frames(page, 1);
  const y1 = (await state(page)).camYaw;
  check(Math.abs(y1 - y0) > 0.3, `${devName}: right-side drag looks around (yaw ${y0} -> ${y1})`);

  // pinch zoom out
  const d0 = (await state(page)).camDist;
  await touch(cdp, 'touchStart', [[W * 0.6, H * 0.4], [W * 0.8, H * 0.4]]);
  for (let i = 1; i <= 5; i++) await touch(cdp, 'touchMove', [[W * 0.6 + i * 8, H * 0.4], [W * 0.8 - i * 8, H * 0.4]]);
  await touch(cdp, 'touchEnd', []);
  await frames(page, 3);
  const d1 = await page.evaluate(() => __hw.follow.dist);
  check(d1 > d0 * 1.2, `${devName}: pinch zooms (target distance ${d0} -> ${d1.toFixed(2)})`);

  // run toggle
  await page.tap('#btn-run');
  R.runPressed = await page.getAttribute('#btn-run', 'aria-pressed');
  check(R.runPressed === 'true', `${devName}: run toggle`);
  await page.tap('#btn-run');
  // run toggle with a second finger while the joystick is held
  const rb = await page.locator('#btn-run').boundingBox();
  const rc = [rb.x + rb.width / 2, rb.y + rb.height / 2];
  await touch(cdp, 'touchStart', [[jx, jy]]);
  await touch(cdp, 'touchMove', [[jx, jy - 60]]);
  await touch(cdp, 'touchStart', [[jx, jy - 60], rc]);
  await touch(cdp, 'touchEnd', [[jx, jy - 60]]);
  R.runWhileHeld = await page.getAttribute('#btn-run', 'aria-pressed');
  await touch(cdp, 'touchEnd', []);
  check(R.runWhileHeld === 'true', `${devName}: run toggles while the joystick is held`);
  await page.tap('#btn-run');

  // minimap survives a rotation while a panel hides it
  await page.tap('#btn-settings'); await sleep(200);
  await page.setViewportSize({ width: H, height: W }); await sleep(400);
  await page.setViewportSize({ width: W, height: H }); await sleep(400);
  await page.keyboard.press('Escape'); await sleep(400);
  R.minimapSize = await page.evaluate(() => [document.getElementById('minimap').width, document.getElementById('minimap').height]);
  check(R.minimapSize[0] > 50 && R.minimapSize[1] > 50, `${devName}: minimap keeps its size after resize with a panel open (${R.minimapSize})`);

  // places menu + teleport by tapping
  await page.tap('#btn-places'); await sleep(300);
  await shot(page, `mobile_${key}_03_places.png`);
  await page.tap('#places-list li:nth-child(3) button');
  await sleep(1500);
  const t = await state(page);
  check(Math.hypot(t.x - 153.6, t.n - 98) < 4, `${devName}: tap-teleport to Ninenzaka (${t.x}, ${t.n})`);
  // walk up Ninenzaka a little with the joystick, then screenshot
  await touch(cdp, 'touchStart', [[jx, jy]]);
  for (let i = 0; i < 10; i++) { await touch(cdp, 'touchMove', [[jx + (i % 2), jy - 70]]); await sleep(400); }
  await touch(cdp, 'touchEnd', []);
  await shot(page, `mobile_${key}_04_ninenzaka.png`);
  await page.tap('#btn-settings'); await sleep(300);
  await shot(page, `mobile_${key}_05_settings.png`);
  await page.tap('#btn-info'); await sleep(300);
  await shot(page, `mobile_${key}_06_info.png`);
  R.noHScrollAfter = await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth);
  await page.tap('[data-close="panel-info"]');
  R.fps = await fpsWindow(page, 10);
  R.quality = await page.evaluate(() => __hw.quality());
  R.consoleErrors = errors; R.externalRequests = ext;
  check(errors.length === 0, `${devName}: no console errors (${errors.length}) ${errors.slice(0, 2).join(' | ')}`);
  check(ext.length === 0, `${devName}: no external requests`);
  await page.context().close();
}

// ------------------------------------------------------------------ robustness
async function robustness(browser, url) {
  console.log('ROBUSTNESS');
  // 1. CDN blocked -> watchdog / module error message instead of an endless "Preparing…"
  {
    const { page } = await newPage(browser, { viewport: { width: 800, height: 600 } });
    await page.route(/cdn\.jsdelivr\.net/, (r) => r.abort());
    const t0 = Date.now();
    await page.goto(url);
    await page.waitForSelector('#fatal:not([hidden])', { timeout: 30000 }).catch(() => {});
    const msg = await page.evaluate(() => (document.getElementById('fatal').hidden ? '' : document.getElementById('fatal').textContent));
    results.robust = { cdnBlocked: { msg, seconds: (Date.now() - t0) / 1000 } };
    check(/3D engine/.test(msg), `CDN blocked: clear message after ${results.robust.cdnBlocked.seconds.toFixed(1)} s`);
    await page.context().close();
  }
  // 2. missing surface mask -> plain ground, the walk still starts
  {
    const { page } = await newPage(browser, { viewport: { width: 800, height: 600 } });
    await page.route(/surface_mask\.png/, (r) => r.fulfill({ status: 404, body: 'nf' }));
    await page.goto(url);
    await page.waitForFunction(() => window.__hw && (window.__hw.ready || !document.getElementById('fatal').hidden), null, { timeout: 300000 });
    const ok = await page.evaluate(() => window.__hw.ready && document.getElementById('fatal').hidden);
    results.robust.noMask = ok;
    check(ok, 'missing surface_mask.png: walk starts with plain ground');
    // 3. a throwing frame does not freeze the loop
    await page.evaluate(() => { __hw.maxDt = 0.5; const T = __hw.traveller; T._u = T.update; let n = 2; T.update = function (...a) { if (n-- > 0) throw new Error('injected'); return T._u.apply(T, a); }; });
    await sleep(6000);
    const alive = await page.evaluate(() => new Promise((r) => { const p0 = __hw.traveller.idleT; setTimeout(() => r(__hw.traveller.idleT > p0), 4000); }));
    check(alive, 'frame loop survives an exception in one frame');
    await page.context().close();
  }
}

const { srv, url } = await serve();
const browser = await launch();
try {
  if (!ONLY || ONLY === 'robust') await robustness(browser, url);
  if (!ONLY || ONLY === 'desktop') await desktop(browser, url);
  if (!ONLY || ONLY === 'mobile') {
    await mobile(browser, url, 'iPhone 13', devices['iPhone 13']);
    await mobile(browser, url, 'Pixel 7', devices['Pixel 7']);
  }
} catch (e) {
  console.error(e);
  results.failures.push('exception: ' + e.message);
} finally {
  await browser.close();
  srv.close();
  fs.writeFileSync(path.join(OUT, 'results.json'), JSON.stringify(results, null, 1));
  console.log('\nFAILURES:', results.failures.length ? results.failures : 'none');
}
