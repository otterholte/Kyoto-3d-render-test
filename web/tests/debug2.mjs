import { serve, launch, newPage, sleep } from './harness.mjs';
const { srv, url } = await serve();
const b = await launch();
const { page, errors } = await newPage(b, { viewport: { width: 800, height: 500 } });
await page.goto(url);
await page.waitForFunction(() => window.__hw && (window.__hw.ready || window.__hw.errors.length), null, { timeout: 300000 });
const r = await page.evaluate(() => {
  const info = __hw.world.objInfo; const g = __hw.world.colGeom; const oid = g.attributes.objId; const idx = g.index;
  const roles = {}; const names = {};
  for (let f = 0; f < idx.count / 3; f += 1) { const o = info[Math.round(oid.getX(idx.getX(f * 3)))]; roles[o.role] = (roles[o.role] || 0) + 1; if (o.role === 'barrier') names[o.name] = 1; }
  return { roles, names: Object.keys(names).slice(0, 10), nInfo: info.length };
});
console.log(JSON.stringify(r));
await b.close(); srv.close();
