// Headless Chromium check: GLB loads, all clips exist and play, screenshots per outfit/clip.
// usage: NODE_PATH=<node_modules with three> node test.cjs <assetsDir> <outDir>
const http = require('http'); const fs = require('fs'); const path = require('path');
const { chromium } = require('playwright');
const assets = path.resolve(process.argv[2]); const outDir = path.resolve(process.argv[3] || '.');
const threeDir = process.env.THREE_DIR || path.resolve(path.dirname(require.resolve('three')), '..');
const types = { '.html': 'text/html', '.js': 'text/javascript', '.mjs': 'text/javascript', '.glb': 'model/gltf-binary', '.wasm': 'application/wasm' };
const srv = http.createServer((req, res) => {
  let u = decodeURIComponent(req.url.split('?')[0]); let f;
  if (u === '/' ) f = path.join(__dirname, 'index.html');
  else if (u.startsWith('/three/')) f = path.join(threeDir, u.slice(7));
  else if (u.startsWith('/assets/')) f = path.join(assets, u.slice(8));
  if (!f || !fs.existsSync(f)) { res.writeHead(404); return res.end(); }
  res.writeHead(200, { 'Content-Type': types[path.extname(f)] || 'application/octet-stream' }); fs.createReadStream(f).pipe(res);
}).listen(0, async () => {
  const port = srv.address().port;
  const browser = await chromium.launch({ args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist', '--enable-webgl'] });
  const page = await browser.newPage({ viewport: { width: 960, height: 540 } });
  const logs = []; page.on('console', m => logs.push(m.text())); page.on('pageerror', e => logs.push('pageerror ' + e.message));
  const cases = [['summer', 'idle', 0.3, 'q'], ['winter', 'idle', 0.3, 'q'], ['summer', 'walk', 0.25, 'side'], ['summer', 'run', 0.3, 'side'],
    ['winter', 'sled_sit', 0.5, 'q'], ['winter', 'superman', 0.5, 'side'], ['winter', 'spread_eagle', 0.5, 'front'], ['winter', 'sled_grab', 0.5, 'q']];
  const results = [];
  for (const [outfit, clip, t, view] of cases) {
    await page.goto(`http://localhost:${port}/?outfit=${outfit}&clip=${clip}&t=${t}&view=${view}`);
    await page.waitForFunction(() => window.__result && (window.__result.ok || window.__result.errors.length), null, { timeout: 120000 });
    const r = await page.evaluate(() => window.__result);
    const shot = path.join(outDir, `webtest_${outfit}_${clip}.png`);
    await page.screenshot({ path: shot });
    results.push({ outfit, clip, ok: r.ok, errors: r.errors, tris: r.tris, headY: +r.headY.toFixed(3), shot });
    if (!results.clips) results.clips = r.clips, results.meshes = r.meshes, results.sledNodes = r.sledNodes;
  }
  console.log(JSON.stringify({ results, clips: results.clips, sledNodes: results.sledNodes, logs: logs.filter(l => /error|warn/i.test(l)).slice(0, 10) }, null, 1));
  await browser.close(); srv.close();
});
