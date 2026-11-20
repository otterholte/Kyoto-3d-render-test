import { serve, launch, newPage, sleep } from './harness.mjs';
const OUT = '/tmp/claude-0/-home-user/78aa4f15-d288-5fa7-835e-afbbfb9eb8f9/scratchpad/web';
const { srv, url } = await serve();
const b = await launch();
const { page, errors } = await newPage(b, { viewport: { width: 1280, height: 800 } });
await page.goto(url);
await page.waitForFunction(() => window.__hw && (window.__hw.ready || window.__hw.errors.length), null, { timeout: 240000 });
for (let i = 0; i < 6; i++) { await sleep(2500); console.log('fps', await page.evaluate(() => [__hw.fps, JSON.stringify(__hw.quality)])); }
const mm = await page.evaluate(() => { const c = document.getElementById('minimap'); const g = c.getContext('2d'); const d = g.getImageData(c.width/2, 5, 1, 1).data; return [c.width, c.height, [...d]]; });
console.log('mm', mm);
await page.screenshot({ path: OUT + '/debug.png' });
console.log(errors);
await b.close(); srv.close();
