// Exercise the art-pass code path (authored materials, merged per material+section) by flagging the current
// world GLB as kind "art" via a manifest override.  node tests/artpath.mjs
import fs from 'node:fs';
import { serve, launch, newPage, sleep } from './harness.mjs';
const { srv, url } = await serve();
const b = await launch();
const { page, errors } = await newPage(b, { viewport: { width: 1000, height: 640 } });
await page.route(/dist\/manifest\.json$/, (r) => { const m = JSON.parse(fs.readFileSync('dist/manifest.json')); m.world.kind = 'art'; r.fulfill({ body: JSON.stringify(m), contentType: 'application/json' }); });
await page.goto(url);
await page.waitForFunction(() => window.__hw && (window.__hw.ready || window.__hw.errors.length), null, { timeout: 300000 });
await sleep(5000);
console.log(JSON.stringify(await page.evaluate(() => { const s = __hw.stats(); delete s.manifest; return s; })));
await page.screenshot({ path: (process.argv[2] || '/tmp') + '/artpath.png' });
console.log(errors);
await b.close(); srv.close();
