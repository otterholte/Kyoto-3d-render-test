// Screenshot views (docs/web_screens or a given dir):  node tests/views.mjs [outDir] [q]
import fs from 'node:fs';
import path from 'node:path';
import { serve, launch, newPage, sleep, WEB } from './harness.mjs';
const OUT = process.argv[2] || path.join(WEB, '..', 'docs', 'web_screens');
const Q = process.argv[3] || '?q=high&scale=0.75';
const ONLY = process.env.ONLY ? process.env.ONLY.split(',') : null;
fs.mkdirSync(OUT, { recursive: true });
const VIEWS = [
  { name: 'summer_bulb', season: 'summer', place: 'bulb' },
  { name: 'summer_front', season: 'summer', place: 'front' },
  { name: 'summer_back', season: 'summer', place: 'back' },
  { name: 'summer_street', season: 'summer', place: 'bottom' },
  { name: 'winter_bulb', season: 'winter', place: 'bulb' },
  { name: 'winter_front', season: 'winter', place: 'front' },
  { name: 'winter_top', season: 'winter', place: 'top' },
  { name: 'winter_street', season: 'winter', place: 'bottom' },
];
const { srv, url } = await serve();
const b = await launch();
const { page, errors } = await newPage(b, { viewport: { width: 1440, height: 900 } });
await page.goto(url + Q + '&season=summer');
await page.waitForFunction(() => window.__cc && (window.__cc.ready || window.__cc.errors.length), null, { timeout: 300000 });
await page.evaluate(() => { __cc.maxDt = 0.6; });
for (const v of VIEWS) {
  if (ONLY && !ONLY.includes(v.name)) continue;
  await page.evaluate(async (v) => { await __cc.setSeason(v.season, { fade: false }); __cc.teleport(v.place); if (v.yaw !== undefined) __cc.follow.yaw = v.yaw; }, v);
  await sleep(2500);
  await page.evaluate(() => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r))));
  await page.screenshot({ path: path.join(OUT, v.name + '.png') });
  console.log('shot', v.name);
}
// sled poses (frozen mid-clip, side view): sit + the three tricks
if (!ONLY || ONLY.some((n) => n.startsWith('sled_'))) {
  await page.evaluate(async () => { await __cc.setSeason('winter', { fade: false }); __cc.teleport('top'); __cc.enterSled(); });
  await page.waitForFunction(() => __cc.game.countdown === 0, null, { timeout: 300000 });
  await page.evaluate(() => { const g = __cc.game; g.active = false; g.vel.set(0, 0, 0); });
  for (const [name, f] of [['sled_sit', 0], ['superman', 0.45], ['spread_eagle', 0.5], ['grab', 0.5]]) {
    if (ONLY && !ONLY.includes('sled_' + name.replace('sled_', ''))) continue;
    await page.evaluate(([name, f]) => {
      const g = __cc.game, P = __cc.person;
      __cc.animScale = name === 'sled_sit' ? 1 : 0;
      if (name === 'sled_sit') { g.trick = null; g.grounded = true; }
      else {
        g.grounded = false; g.trick = { name, t: 0.5, dur: 1, label: name, points: 0 };
        P.playTrick(name, 1); const a = P.actions[name]; a.time = a.getClip().duration * f;
      }
      __cc.chase.yawOff = -1.35; __cc.chase.pitchOff = 0.05; __cc.chase.lastLook = performance.now() + 1e9;
    }, [name, f]);
    await sleep(1500);
    await page.evaluate(() => { __cc.animScale = 0; });
    await sleep(800);
    await page.screenshot({ path: path.join(OUT, 'sled_' + name.replace('sled_', '') + '.png') });
    console.log('shot sled_' + name);
  }
  await page.evaluate(() => { __cc.animScale = 1; __cc.exitSled(); });
}
console.log('errors', errors);
await b.close(); srv.close();
