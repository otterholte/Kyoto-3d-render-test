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
for (const v of VIEWS) {
  if (ONLY && !ONLY.includes(v.name)) continue;
  await page.evaluate(async (v) => { await __cc.setSeason(v.season, { fade: false }); __cc.teleport(v.place); if (v.yaw !== undefined) __cc.follow.yaw = v.yaw; }, v);
  await sleep(2500);
  await page.evaluate(() => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r))));
  await page.screenshot({ path: path.join(OUT, v.name + '.png') });
  console.log('shot', v.name);
}
console.log('errors', errors);
await b.close(); srv.close();
