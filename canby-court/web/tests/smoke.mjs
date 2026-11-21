// quick smoke: load, screenshot, errors
import { serve, launch, newPage, sleep } from './harness.mjs';
const OUT = process.argv[2] || '/tmp/claude-0/-home-user/78aa4f15-d288-5fa7-835e-afbbfb9eb8f9/scratchpad/cc';
import fs from 'node:fs'; fs.mkdirSync(OUT, { recursive: true });
const { srv, url } = await serve();
const b = await launch();
const { page, errors } = await newPage(b, { viewport: { width: 1280, height: 800 } }, (l) => { if (!/GPU stall|GL Driver/.test(l)) console.log(l.slice(0, 300)); });
const q = process.env.Q || '?q=low&scale=0.5';
const t0 = Date.now();
await page.goto(url + q + (process.env.SEASON ? '&season=' + process.env.SEASON : ''));
await page.waitForFunction(() => window.__cc && (window.__cc.ready || window.__cc.errors.length || !document.getElementById('fatal').hidden), null, { timeout: 300000 });
console.log('ready in', (Date.now() - t0) / 1000, 's', await page.evaluate(() => ({ err: __cc.errors, fatal: document.getElementById('fatal').textContent, stats: __cc.ready && __cc.stats(), state: __cc.ready && __cc.state(), world: __cc.ready && __cc.world() })));
await sleep(1500);
await page.screenshot({ path: OUT + '/smoke.png' });
if (false) {
  const r = await page.evaluate(() => __cc.simulate(JSON.parse(process_env_sim)).catch?.() );
}
console.log('errors', errors);
await b.close(); srv.close();
