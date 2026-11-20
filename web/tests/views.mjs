// Quick visual check: node tests/views.mjs [outDir]  (screenshots of a few views at 1280x800)
import path from 'node:path';
import { serve, launch, newPage, sleep } from './harness.mjs';
const OUT = process.argv[2] || '/tmp/claude-0/-home-user/78aa4f15-d288-5fa7-835e-afbbfb9eb8f9/scratchpad/web';
const VIEWS = (process.env.VIEWS || 'gate').split(',');
const { srv, url } = await serve();
const b = await launch();
const { page, errors } = await newPage(b, { viewport: { width: 1280, height: 800 } });
await page.goto(url);
await page.waitForFunction(() => window.__hw && (window.__hw.ready || window.__hw.errors.length), null, { timeout: 300000 });
const setups = {
  gate: () => { __hw.setTime(0.3); __hw.teleport(__hw.places.find((p) => p.id === 'gate')); },
  yasaka: () => { __hw.setTime(0.3); __hw.teleport(__hw.places[0]); },
  koshindo: () => { __hw.setTime(0.5); __hw.teleport(__hw.places.find((p) => p.id === 'koshindo')); __hw.follow.pitch = 0.05; __hw.follow.dist = 7; },
  aerial: () => { __hw.setTime(0.2); __hw.teleport(__hw.places.find((p) => p.id === 'gate')); __hw.follow.pitch = 1.0; __hw.follow.dist = 14; },
  ninen: () => { __hw.setTime(0.8); __hw.teleport(__hw.places.find((p) => p.id === 'ninenzaka')); },
  sannen: () => { __hw.setTime(0.6); __hw.teleport(__hw.places.find((p) => p.id === 'sannen-stairs')); __hw.follow.pitch = 0.1; },
};
for (const v of VIEWS) {
  await page.evaluate(`(${setups[v].toString()})()`);
  await sleep(4000);
  await page.screenshot({ path: path.join(OUT, `view_${v}.png`) });
  console.log('shot', v);
}
console.log('errors', errors, await page.evaluate(() => __hw.stats().pagodaUrl));
await b.close(); srv.close();
