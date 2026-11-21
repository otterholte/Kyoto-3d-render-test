// End-to-end tests (Playwright, headless Chromium + SwiftShader WebGL).
//   node tests/run.mjs [outDir]          (default outDir: ../docs/web_screens)
// Desktop 1440x900 + iPhone 13 + Pixel 7: load without console errors, real keyboard / touch input, a full walk
// around 3905 Canby Ct (circuit), wall blocking, season toggle (button), a scripted sled run over all three
// kickers (real-time autopilot + headless physics checks: big-kicker airtime, pop raises the apex, a trick
// scores, the berm stops the sled before 38th St), sled HUD buttons on touch. Writes results.json.
import fs from 'node:fs';
import path from 'node:path';
import { serve, launch, newPage, devices, sleep, WEB } from './harness.mjs';

const OUT = process.argv[2] || path.join(WEB, '..', 'docs', 'web_screens');
fs.mkdirSync(OUT, { recursive: true });
const ONLY = process.env.ONLY || '';
const DESK_Q = process.env.DESK_Q || '?q=low&scale=0.5', MOB_Q = process.env.MOB_Q || '?q=medium&scale=0.5';
const results = { started: new Date().toISOString(), desktop: {}, mobile: {}, failures: [] };
const check = (cond, msg) => { if (!cond) { results.failures.push(msg); console.log('  FAIL', msg); } else console.log('  ok  ', msg); };
const WD = JSON.parse(fs.readFileSync(path.join(WEB, 'assets', 'world_data.json'), 'utf8'));
const H3905 = WD.houses.find((h) => h.number === 3905);

async function waitReady(page) {
  const t0 = Date.now();
  await page.waitForFunction(() => window.__cc && (window.__cc.ready || window.__cc.errors.length || !document.getElementById('fatal').hidden), null, { timeout: 300000 });
  const err = await page.evaluate(() => __cc.errors.concat(document.getElementById('fatal').hidden ? [] : [document.getElementById('fatal').textContent]));
  if (err.length) throw new Error('page error: ' + err.join('\n'));
  await page.evaluate(() => { __cc.maxDt = 0.25; });
  return (Date.now() - t0) / 1000;
}
const state = (page) => page.evaluate(() => __cc.state());
const sled = (page) => page.evaluate(() => __cc.sled());
async function frames(page, n = 2) { for (let i = 0; i < n; i++) await page.evaluate(() => new Promise((r) => requestAnimationFrame(() => r()))); }
async function shot(page, name) { await frames(page, 2); await page.screenshot({ path: path.join(OUT, name), timeout: 300000 }); console.log('  shot', name); }
async function steer(page, x, n) {
  await page.evaluate(([x, n]) => { const p = __cc.ctrl.pos; const dx = x - p.x, dz = -n - p.z; __cc.follow.yaw = Math.atan2(-dx, -dz); __cc.follow.lastLook = performance.now(); }, [x, n]);
}
function inPoly(x, y, poly) {
  let ins = false;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const [xi, yi] = poly[i], [xj, yj] = poly[j];
    if ((yi > y) !== (yj > y) && x < (xj - xi) * (y - yi) / (yj - yi) + xi) ins = !ins;
  }
  return ins;
}

// hold W (+Shift) and steer through waypoints (local x, north); returns track summary
async function walk(page, wps, { tol = 1.2, maxWall = 300000, run = true, stuckMs = 45000 } = {}) {
  const t0 = Date.now(); const track = []; let i = 0, best = Infinity, lastProgress = Date.now();
  await steer(page, ...wps[0]);
  await page.keyboard.down('KeyW'); if (run) await page.keyboard.down('ShiftLeft');
  while (i < wps.length && Date.now() - t0 < maxWall) {
    await steer(page, ...wps[i]);
    await sleep(200);
    const s = await state(page);
    track.push([s.x, s.n, s.y]);
    const d = Math.hypot(s.x - wps[i][0], s.n - wps[i][1]);
    if (d < tol) { i++; best = Infinity; lastProgress = Date.now(); continue; }
    if (d < best - 0.05) { best = d; lastProgress = Date.now(); }
    if (Date.now() - lastProgress > stuckMs) break;
  }
  await page.keyboard.up('KeyW'); if (run) await page.keyboard.up('ShiftLeft');
  await frames(page, 2);
  return { reached: i >= wps.length, waypointsDone: i, of: wps.length, final: await state(page), track, wallSeconds: (Date.now() - t0) / 1000 };
}

// ------------------------------------------------------------------ desktop
async function desktop(browser, url) {
  console.log('DESKTOP 1440x900');
  const { page, errors, ext } = await newPage(browser, { viewport: { width: 1440, height: 900 } });
  await page.goto(url + DESK_Q + '&season=summer');
  const R = results.desktop;
  R.loadSeconds = await waitReady(page);
  console.log('  ready in', R.loadSeconds, 's', JSON.stringify(await page.evaluate(() => __cc.stats())));
  R.stats = await page.evaluate(() => __cc.stats());
  check(R.stats.character === 'glb' || R.stats.character === 'placeholder', `character loaded (${R.stats.character}; clips ${R.stats.clips.join(',')})`);
  await sleep(800);
  await shot(page, 'desktop_01_summer_spawn.png');
  R.spawn = await state(page);
  check(R.spawn.grounded && /terrain|ground|road|snow|drive|walk/i.test(R.spawn.ground), `spawn on the ground at the bulb (${R.spawn.ground}, z ${R.spawn.y})`);

  // places: every target lands on a walkable, free spot near the request
  R.places = {};
  for (const id of ['bulb', 'front', 'back', 'top', 'bottom']) {
    const t = await page.evaluate((id) => __cc.teleport(id), id);
    R.places[id] = t;
    check(t.offset !== null && t.offset <= 4, `place "${id}" -> (${t.placed}) offset ${t.offset} m on ${t.ground}`);
  }

  // keyboard walk: W moves forward
  await page.evaluate(() => __cc.teleport('bulb'));
  const a = await state(page);
  await page.keyboard.down('KeyW'); await sleep(2500); await page.keyboard.up('KeyW');
  const b = await state(page);
  R.keyboardWalk = Math.hypot(b.x - a.x, b.n - a.n);
  check(R.keyboardWalk > 1.0, `W walks forward (${R.keyboardWalk.toFixed(2)} m)`);

  // walk into the 3905 wall: blocked
  await page.evaluate(() => __cc.teleport({ x: -6.5, n: -9, look: [0, 0] }));
  const w0 = await state(page);
  await steer(page, 0, -2);
  await page.keyboard.down('KeyW'); await sleep(5000); await page.keyboard.up('KeyW');
  const w1 = await state(page);
  R.wall = { from: w0, to: w1, inside: inPoly(w1.x, w1.n, H3905.fp) };
  check(!R.wall.inside, `walking into 3905 is blocked (stopped at ${w1.x}, ${w1.n}; wall contact ${w1.wall})`);

  // circuit around 3905: footprint offset ~3 m, adjusted to free walkable spots in the page
  const cx = H3905.centroid[0], cy = H3905.centroid[1];
  const ring = [];
  for (let k = 0; k < 16; k++) {
    const ang = (k / 16) * Math.PI * 2 - Math.PI * 0.75;
    // march outward from the centroid until 3.2 m outside the footprint
    let r = 2; while (inPoly(cx + Math.cos(ang) * r, cy + Math.sin(ang) * r, H3905.fp) && r < 30) r += 0.25;
    ring.push([cx + Math.cos(ang) * (r + 3.2), cy + Math.sin(ang) * (r + 3.2)]);
  }
  const wps = await page.evaluate((ring) => ring.map(([x, n]) => { const s = __cc.ctrl.findSpot(x, -n, 3); return s ? [+s.pos.x.toFixed(2), +(-s.pos.z).toFixed(2)] : [x, n]; }), ring);
  wps.push(wps[0]);
  await page.evaluate((p) => __cc.teleport({ x: p[0], n: p[1], look: [p[0] + 1, p[1]] }), wps[0]);
  const circ = await walk(page, wps.slice(1), { tol: 1.4 });
  let swept = 0;
  for (let i = 1; i < circ.track.length; i++) {
    const a0 = Math.atan2(circ.track[i - 1][1] - cy, circ.track[i - 1][0] - cx), a1 = Math.atan2(circ.track[i][1] - cy, circ.track[i][0] - cx);
    swept += Math.atan2(Math.sin(a1 - a0), Math.cos(a1 - a0));
  }
  const entered = circ.track.some(([x, n]) => inPoly(x, n, H3905.fp));
  R.circuit = { waypoints: wps, reached: circ.reached, done: `${circ.waypointsDone}/${circ.of}`, sweptDeg: Math.round(Math.abs(swept) * 180 / Math.PI), entered, seconds: circ.wallSeconds };
  check(circ.reached && Math.abs(swept) > Math.PI * 1.9, `walked all the way around 3905 (${R.circuit.done} waypoints, ${R.circuit.sweptDeg} deg swept, ${circ.wallSeconds.toFixed(0)} s)`);
  check(!entered, 'never inside the 3905 footprint during the circuit');
  await page.evaluate(() => __cc.teleport('back'));
  await sleep(600);
  await shot(page, 'desktop_02_summer_backyard.png');

  // season toggle with the real button
  await page.evaluate(() => __cc.teleport('bulb'));
  await page.click('#btn-season');
  await page.waitForFunction(() => __cc.season() === 'winter', null, { timeout: 120000 });
  await sleep(1500);
  R.winter = { season: await page.evaluate(() => __cc.season()), world: await page.evaluate(() => __cc.world()), state: await state(page) };
  check(R.winter.season === 'winter' && R.winter.state.grounded, `season button -> winter (${R.winter.world.kind} world, kickers ${R.winter.world.hasKickers})`);
  check(await page.evaluate(() => document.body.classList.contains('winter')), 'winter UI state');
  await shot(page, 'desktop_03_winter_bulb.png');

  // sled: go to the top, the Sled button appears, click it
  await page.evaluate(() => __cc.teleport('top'));
  await sleep(1200);
  check(await page.isVisible('#btn-sled'), 'Sled button visible at the top of the run (winter)');
  await page.click('#btn-sled');
  await sleep(300);
  check(await page.evaluate(() => __cc.mode()) === 'sled', 'sled mode on');
  await shot(page, 'desktop_04_sled_start.png');
  // real keyboard steering during the countdown / first metres: A turns left (heading increases)
  const h0 = await page.evaluate(() => __cc.game.heading);
  await page.keyboard.down('KeyA'); await sleep(3500); await page.keyboard.up('KeyA');
  const h1 = await page.evaluate(() => __cc.game.heading);
  R.keyboardSteer = { h0, h1 };
  check(h1 - h0 > 0.05, `A steers the sled left (heading ${h0.toFixed(2)} -> ${h1.toFixed(2)})`);
  // R restarts
  await page.keyboard.press('KeyR');
  await sleep(200);
  const rs = await sled(page);
  check(rs.countdown > 0 && rs.arc < 3, `R restarts the run (countdown ${rs.countdown}, arc ${rs.arc})`);

  // scripted real-time run (autopilot: pops at every lip, Superman on the big kicker, Grab on the mid)
  await page.evaluate(() => __cc.autopilot({ pop: true, tricks: { jump_3_big: 'superman', jump_2_mid: 'grab' } }));
  const t0 = Date.now(); let shotAir = false, shotTrick = false, s;
  while (Date.now() - t0 < 400000) {
    s = await sled(page);
    if (!shotAir && !s.grounded && s.airTime > 0.25 && s.arc > 30 && s.arc < 45) { await page.screenshot({ path: path.join(OUT, 'desktop_05_sled_air_starter.png') }); shotAir = true; console.log('  shot desktop_05_sled_air_starter.png'); }
    if (!shotTrick && s.trick === 'superman') { await page.screenshot({ path: path.join(OUT, 'desktop_06_sled_superman.png') }); shotTrick = true; console.log('  shot desktop_06_sled_superman.png'); }
    if (s.finished) break;
    await sleep(120);
  }
  await sleep(1500);
  await shot(page, 'desktop_07_sled_finish.png');
  s = await sled(page);
  R.realtimeRun = s;
  const byId = Object.fromEntries(s.jumps.filter((j) => j.jump).map((j) => [j.jump, j]));
  check(['jump_1_starter', 'jump_2_mid', 'jump_3_big'].every((id) => byId[id]), `real-time run hit all three kickers (${Object.keys(byId).join(', ')})`);
  check(byId.jump_3_big && byId.jump_3_big.airtime > 0.5, `big kicker airtime ${byId.jump_3_big && byId.jump_3_big.airtime} s > 0.5 s`);
  check(s.jumps.some((j) => j.tricks.some((t) => t.points > 0)), `a trick scored (${s.jumps.flatMap((j) => j.tricks.map((t) => t.label + ' ' + t.points)).join(', ')}); score ${s.score}`);
  check(s.finished && !s.finished.overrun && s.finished.toJunction > 2, `stopped before 38th St (${s.finished && s.finished.toJunction} m short of the junction, at ${JSON.stringify(s.finished && s.finished.stopPos)})`);
  check(await page.isVisible('#panel-finish'), 'run-complete panel shown');
  R.best = await page.evaluate(() => { try { return localStorage.getItem('cc-best'); } catch { return null; } });
  check(+R.best > 0, `best score stored (${R.best})`);

  // headless physics checks (same collider + physics, fixed 1/120 s steps)
  const noPop = await page.evaluate(() => __cc.simulate({ pop: false }));
  const withPop = await page.evaluate(() => __cc.simulate({ pop: true }));
  const tr = await page.evaluate(() => __cc.simulate({ pop: true, tricks: { jump_3_big: 'superman' } }));
  const bj = (r) => r.jumps.find((j) => j.jump === 'jump_3_big') || {};
  R.sim = { noPop: { big: bj(noPop), finished: noPop.finished, score: noPop.score }, withPop: { big: bj(withPop), finished: withPop.finished, score: withPop.score }, trick: { big: bj(tr), score: tr.score } };
  check(bj(noPop).airtime > 0.5, `headless: big kicker airtime without pop ${bj(noPop).airtime} s > 0.5 s`);
  check(bj(withPop).apex > bj(noPop).apex + 0.3, `headless: pop raises the big-kicker apex ${bj(noPop).apex} -> ${bj(withPop).apex} m`);
  check(bj(tr).tricks && bj(tr).tricks.some((t) => t.name === 'superman' && t.points >= 600) && bj(tr).clean, `headless: Superman on the big kicker scores (${JSON.stringify(bj(tr).tricks)})`);
  for (const [k, r] of [['no pop', noPop], ['pop', withPop]]) check(r.finished && !r.finished.overrun && r.finished.toJunction > 2, `headless (${k}): berm / stop zone stops the sled ${r.finished && r.finished.toJunction} m before 38th St`);
  // an unfinished trick at touch-down is a wipeout (Superman on the small starter kicker without pop)
  const wipe = await page.evaluate(() => __cc.simulate({ pop: false, tricks: { jump_1_starter: 'superman' }, maxT: 14 }));
  R.sim.wipeout = wipe.events.filter((e) => e.type === 'wipeout' || e.type === 'respawn');
  check(R.sim.wipeout.some((e) => e.type === 'wipeout') && R.sim.wipeout.some((e) => e.type === 'respawn'), `unfinished trick -> wipeout + respawn at checkpoint (${JSON.stringify(R.sim.wipeout)})`);

  // leave the sled, back to summer
  await page.click('#f-walk');
  await sleep(300);
  check(await page.evaluate(() => __cc.mode()) === 'walk', 'Walk button leaves the sled');
  await page.click('#btn-season');
  await page.waitForFunction(() => __cc.season() === 'summer', null, { timeout: 120000 });
  await sleep(800);
  check((await state(page)).grounded, 'back to summer, walker grounded');
  await page.click('#btn-places'); await sleep(300);
  await shot(page, 'desktop_08_places.png');
  await page.keyboard.press('Escape');
  await page.click('#btn-info'); await sleep(300);
  await shot(page, 'desktop_09_info.png');
  await page.keyboard.press('Escape');
  R.fps = await page.evaluate(() => __cc.fps);
  R.errors = errors; R.external = ext;
  check(errors.length === 0, `desktop: no console errors (${errors.length}) ${errors.slice(0, 3).join(' | ')}`);
  check(ext.length === 0, `desktop: no external requests besides the CDN (${ext.join(', ')})`);
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
  await page.goto(url + MOB_Q + '&season=summer');
  const R = (results.mobile[devName] = {});
  R.loadSeconds = await waitReady(page);
  await sleep(1200);
  R.viewport = page.viewportSize();
  const { width: W, height: H } = R.viewport;
  R.noHScroll = await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth && document.body.scrollWidth <= innerWidth);
  check(R.noHScroll, `${devName}: no horizontal page scroll`);
  R.quality = await page.evaluate(() => __cc.quality());
  check(R.quality.pixelRatio <= 1.5 + 1e-6, `${devName}: pixel ratio capped (${R.quality.pixelRatio})`);
  check(await page.isVisible('#btn-run'), `${devName}: run toggle visible on touch`);
  await shot(page, `mobile_${key}_01_summer.png`);

  // joystick walk
  await page.evaluate(() => __cc.teleport('bulb'));
  await frames(page, 1);
  const a = await state(page);
  const jx = W * 0.2, jy = H * 0.78;
  await touch(cdp, 'touchStart', [[jx, jy]]);
  await touch(cdp, 'touchMove', [[jx, jy - 30]]);
  await touch(cdp, 'touchMove', [[jx + 2, jy - 70]]);
  for (let i = 0; i < 10; i++) { await touch(cdp, 'touchMove', [[jx + (i % 2), jy - 70]]); await sleep(350); }
  await touch(cdp, 'touchEnd', []);
  await frames(page, 1);
  const b = await state(page);
  R.joystick = Math.hypot(b.x - a.x, b.n - a.n);
  check(R.joystick > 1.0, `${devName}: joystick walks (${R.joystick.toFixed(2)} m)`);
  // right-side drag look
  const y0 = (await state(page)).camYaw;
  await touch(cdp, 'touchStart', [[W * 0.75, H * 0.45]]);
  for (let i = 1; i <= 5; i++) await touch(cdp, 'touchMove', [[W * 0.75 - i * 20, H * 0.45]]);
  await touch(cdp, 'touchEnd', []);
  await frames(page, 1);
  const y1 = (await state(page)).camYaw;
  check(Math.abs(y1 - y0) > 0.3, `${devName}: right-side drag looks around (${y0} -> ${y1})`);

  // season toggle by tap
  await page.tap('#btn-season');
  await page.waitForFunction(() => __cc.season() === 'winter', null, { timeout: 120000 });
  await sleep(1200);
  await shot(page, `mobile_${key}_02_winter.png`);
  // places -> top of the run, Sled button
  await page.tap('#btn-places'); await sleep(300);
  await shot(page, `mobile_${key}_03_places.png`);
  await page.tap('#places-list li:nth-child(4) button');
  await sleep(1200);
  check(await page.isVisible('#btn-sled'), `${devName}: Sled button visible at the top`);
  await page.tap('#btn-sled');
  await sleep(500);
  check(await page.evaluate(() => __cc.mode()) === 'sled', `${devName}: sled mode via tap`);
  R.sledHudFits = await page.evaluate(() => {
    const ids = ['s-boost', 'sled-exit', 'sled-restart'];
    return ids.every((id) => { const r = document.getElementById(id).getBoundingClientRect(); return r.left >= 0 && r.right <= innerWidth && r.top >= 0 && r.bottom <= innerHeight && r.width >= 44 && r.height >= 44; })
      && [...document.querySelectorAll('.trick-btn')].every((el) => { const r = el.getBoundingClientRect(); return r.right <= innerWidth && r.bottom <= innerHeight && r.height >= 40; });
  });
  check(R.sledHudFits, `${devName}: sled buttons inside the screen with touch-sized targets`);
  await page.waitForFunction(() => __cc.sled().countdown === 0 && __cc.sled().speed > 1, null, { timeout: 120000 });
  // left thumb steers right: heading decreases
  const hA = await page.evaluate(() => __cc.game.heading);
  await touch(cdp, 'touchStart', [[jx, jy]]);
  await touch(cdp, 'touchMove', [[jx + 40, jy]]);
  for (let i = 0; i < 6; i++) { await touch(cdp, 'touchMove', [[jx + 60 + (i % 2), jy]]); await sleep(300); }
  await touch(cdp, 'touchEnd', []);
  const hB = await page.evaluate(() => __cc.game.heading);
  R.touchSteer = { hA, hB };
  check(hB < hA - 0.05, `${devName}: joystick steers the sled right (heading ${hA.toFixed(2)} -> ${hB.toFixed(2)})`);
  // POP button: ollie on flat snow (registers the press), trick button press accepted while airborne
  const pop = await page.evaluate(() => { const before = __cc.game.events.length; return before; });
  await page.tap('#s-boost');
  await sleep(200);
  const evs = await page.evaluate((n) => __cc.game.events.slice(n).map((e) => e.type), pop);
  check(evs.includes('pop'), `${devName}: POP button works (${evs.join(',')})`);
  await shot(page, `mobile_${key}_04_sled.png`);
  await page.tap('#sled-exit');
  await sleep(300);
  check(await page.evaluate(() => __cc.mode()) === 'walk', `${devName}: leave the sled by tap`);
  await page.tap('#btn-info'); await sleep(300);
  await shot(page, `mobile_${key}_05_info.png`);
  R.errors = errors; R.external = ext;
  check(errors.length === 0, `${devName}: no console errors (${errors.length}) ${errors.slice(0, 3).join(' | ')}`);
  await page.context().close();
}

// ------------------------------------------------------------------ main
const { srv, url } = await serve();
const browser = await launch();
try {
  if (!ONLY || ONLY === 'desktop') await desktop(browser, url);
  if (!ONLY || ONLY === 'mobile') {
    await mobile(browser, url, 'iPhone 13', devices['iPhone 13']);
    await mobile(browser, url, 'Pixel 7', devices['Pixel 7']);
  }
} catch (e) {
  results.failures.push('exception: ' + (e && e.stack || e));
  console.error(e);
} finally {
  results.finished = new Date().toISOString();
  fs.writeFileSync(path.join(OUT, 'results.json'), JSON.stringify(results, null, 1));
  await browser.close(); srv.close();
  console.log(results.failures.length ? `\n${results.failures.length} FAILURE(S)` : '\nALL CHECKS PASSED');
  process.exit(results.failures.length ? 1 : 0);
}
