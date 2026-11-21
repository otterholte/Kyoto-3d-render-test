// Relative render cost per tier (SwiftShader: only ratios are meaningful). node tests/perf.mjs
import { serve, launch, newPage, sleep } from './harness.mjs';
const { srv, url } = await serve();
const b = await launch();
const out = {};
for (const q of (process.env.TIERS || 'low,medium,high').split(',')) {
  const { page, errors } = await newPage(b, { viewport: { width: 640, height: 400 } });
  await page.goto(url + '?q=' + q);
  await page.waitForFunction(() => window.__hw && window.__hw.ready, null, { timeout: 300000 });
  await sleep(8000);
  const r = await page.evaluate(async () => {
    const T = []; for (let i = 0; i < 4; i++) { const t0 = performance.now(); await new Promise((res) => requestAnimationFrame(() => requestAnimationFrame(res))); T.push((performance.now() - t0) / 2); }
    return { ms: T.map(Math.round), env: !!__hw.scene.environment, info: __hw.renderer.info.render.calls };
  });
  out[q] = { ...r, errors: errors.length };
  console.log(q, JSON.stringify(out[q]));
  await page.context().close();
}
await b.close(); srv.close();
