// Test harness: static server for web/ + Playwright page factory that serves the pinned CDN modules
// (three@0.170.0, three-mesh-bvh@0.8.3) from node_modules, so tests run offline with the same code.
import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';

const require = createRequire(import.meta.url);
export const { chromium, devices } = require('playwright');
export const WEB = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

const TYPES = { '.html': 'text/html', '.js': 'text/javascript', '.mjs': 'text/javascript', '.css': 'text/css', '.json': 'application/json', '.glb': 'model/gltf-binary', '.png': 'image/png', '.svg': 'image/svg+xml' };

export function serve(port = 0) {
  const srv = http.createServer((req, res) => {
    const u = decodeURIComponent(new URL(req.url, 'http://x').pathname);
    let p = path.join(WEB, u === '/' ? 'index.html' : u);
    if (!p.startsWith(WEB) || !fs.existsSync(p) || fs.statSync(p).isDirectory()) { res.writeHead(404); res.end('nf'); return; }
    const st = fs.statSync(p);
    res.writeHead(200, { 'content-type': TYPES[path.extname(p)] || 'application/octet-stream', 'content-length': st.size, 'cache-control': 'no-store' });
    if (req.method === 'HEAD') { res.end(); return; }
    fs.createReadStream(p).pipe(res);
  });
  return new Promise((r) => srv.listen(port, '127.0.0.1', () => r({ srv, url: `http://127.0.0.1:${srv.address().port}/` })));
}

const CDN = [
  [/^https:\/\/cdn\.jsdelivr\.net\/npm\/three@0\.170\.0\/(.*)$/, 'node_modules/three/'],
  [/^https:\/\/cdn\.jsdelivr\.net\/npm\/three-mesh-bvh@0\.8\.3\/(.*)$/, 'node_modules/three-mesh-bvh/'],
];

export async function launch() {
  return chromium.launch({ args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist', '--enable-webgl'] });
}

export async function newPage(browser, ctxOpts, log) {
  const ctx = await browser.newContext(ctxOpts);
  const page = await ctx.newPage();
  const ext = [];
  await page.route(/^https?:\/\/(?!127\.0\.0\.1)/, async (route) => {
    const url = route.request().url();
    for (const [re, dir] of CDN) {
      const m = url.match(re);
      if (m) {
        const f = path.join(WEB, dir, m[1]);
        if (fs.existsSync(f)) return route.fulfill({ status: 200, contentType: 'text/javascript', body: fs.readFileSync(f) });
      }
    }
    ext.push(url);
    return route.abort();
  });
  const errors = [], warnings = [];
  page.on('console', (m) => {
    if (m.type() === 'error') errors.push(m.text());
    else if (m.type() === 'warning') warnings.push(m.text());
    if (log) log(`[${m.type()}] ${m.text()}`);
  });
  page.on('pageerror', (e) => errors.push('pageerror: ' + e.message));
  return { ctx, page, errors, warnings, ext };
}

export const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
