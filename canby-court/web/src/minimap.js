// Mini-map: surface classes (assets/surface.png) as a soft base map + house/building footprints, Canby Ct, trees,
// sled run with kickers (winter), and the player arrow. North up. Tap toggles local (±45 m) / whole area.
const PAL = {
  summer: { asphalt: [92, 94, 100], concrete: [196, 192, 182], lawn: [128, 168, 96], bed: [96, 112, 72], bg: '#9db07f' },
  winter: { asphalt: [190, 196, 208], concrete: [222, 226, 232], lawn: [240, 243, 248], bed: [226, 231, 238], bg: '#e9edf3' },
};

export class MiniMap {
  constructor(canvas, wrap, data, surfaceImg, surfMeta) {
    this.c = canvas; this.g = canvas.getContext('2d'); this.wrap = wrap; this.data = data;
    this.full = false; this.season = 'summer';
    this.meta = surfMeta;
    this.base = {};
    this.img = surfaceImg;
    wrap.addEventListener('click', () => { this.full = !this.full; wrap.classList.toggle('full', this.full); this.resize(); });
    wrap.tabIndex = 0;
    wrap.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); wrap.click(); } });
    this.resize();
  }
  baseFor(season) {
    if (this.base[season]) return this.base[season];
    const img = this.img;
    if (!img) return null;
    const W = img.naturalWidth || img.width, H = img.naturalHeight || img.height;
    const cv = document.createElement('canvas'); cv.width = W; cv.height = H;
    const g = cv.getContext('2d');
    g.drawImage(img, 0, 0);
    let d;
    try { d = g.getImageData(0, 0, W, H); } catch { return null; }
    const P = PAL[season], a = d.data;
    for (let i = 0; i < a.length; i += 4) {
      const r = a[i] / 255, gg = a[i + 1] / 255, b = a[i + 2] / 255, rest = Math.max(0, 1 - r - gg - b);
      for (let k = 0; k < 3; k++) a[i + k] = P.asphalt[k] * r + P.concrete[k] * gg + P.lawn[k] * b + P.bed[k] * rest;
      a[i + 3] = 255;
    }
    g.putImageData(d, 0, 0);
    this.base[season] = cv;
    return cv;
  }
  resize() {
    const r = this.wrap.getBoundingClientRect();
    const dpr = Math.min(2, devicePixelRatio || 1);
    this.c.width = Math.max(2, Math.round(r.width * dpr)); this.c.height = Math.max(2, Math.round(r.height * dpr));
    this.dpr = dpr;
  }
  draw(px, pn, facing, camYaw, sledOn) {
    const g = this.g, W = this.c.width, H = this.c.height;
    const span = this.full ? 300 : 90;                 // metres across
    const s = Math.min(W, H) / span;
    const cx = this.full ? -50 : px, cn = this.full ? -25 : pn;
    const X = (x) => W / 2 + (x - cx) * s, Y = (n) => H / 2 - (n - cn) * s;
    g.fillStyle = PAL[this.season].bg; g.fillRect(0, 0, W, H);
    const base = this.baseFor(this.season);
    if (base) {
      const [x0, y0, x1, y1] = this.meta.bounds;
      g.imageSmoothingEnabled = true;
      g.drawImage(base, X(x0), Y(y1), (x1 - x0) * s, (y1 - y0) * s);
    }
    // footprints
    const poly = (pts) => { g.beginPath(); pts.forEach(([x, y], i) => (i ? g.lineTo(X(x), Y(y)) : g.moveTo(X(x), Y(y)))); g.closePath(); };
    g.lineWidth = Math.max(1, this.dpr);
    for (const b of this.data.context_buildings) { poly(b.fp); g.fillStyle = this.season === 'winter' ? '#c9ced8' : '#8f8a84'; g.fill(); }
    for (const h of this.data.houses) {
      poly(h.fp);
      g.fillStyle = h.number === 3905 ? '#c4553b' : this.season === 'winter' ? '#b5bcc8' : '#6f6a66'; g.fill();
      g.strokeStyle = 'rgba(0,0,0,.35)'; g.stroke();
    }
    // trees
    for (const t of this.data.trees) {
      const r = Math.max(1.2, t.r) * s;
      if (X(t.x) < -r || X(t.x) > W + r || Y(t.y) < -r || Y(t.y) > H + r) continue;
      g.beginPath(); g.arc(X(t.x), Y(t.y), r, 0, Math.PI * 2);
      g.fillStyle = t.type === 'conifer' ? 'rgba(30,70,40,.55)' : this.season === 'winter' ? 'rgba(110,95,80,.25)' : 'rgba(70,110,50,.45)';
      g.fill();
    }
    // sled run + kickers (winter)
    if (this.season === 'winter') {
      const p = this.data.sled.path;
      g.beginPath(); p.forEach(([x, y], i) => (i ? g.lineTo(X(x), Y(y)) : g.moveTo(X(x), Y(y))));
      g.strokeStyle = 'rgba(40,110,220,.75)'; g.lineWidth = Math.max(2, 2.4 * s); g.setLineDash([6 * this.dpr, 4 * this.dpr]); g.stroke(); g.setLineDash([]);
      for (const j of this.data.sled.jumps) {
        g.beginPath(); g.arc(X(j.center_local[0]), Y(j.center_local[1]), Math.max(3 * this.dpr, 1.8 * s), 0, Math.PI * 2);
        g.fillStyle = '#d9381e'; g.fill();
      }
      const b = this.data.sled.berm.center_local;
      g.fillStyle = '#9c7b3c'; g.fillRect(X(b[0]) - 3 * this.dpr, Y(b[1]) - 6 * this.dpr, 6 * this.dpr, 12 * this.dpr);
    }
    // view cone + player arrow
    const ax = X(px), ay = Y(pn);
    if (!sledOn) {
      const ang = Math.atan2(-Math.cos(camYaw), -Math.sin(camYaw));
      g.beginPath(); g.moveTo(ax, ay);
      g.arc(ax, ay, 26 * this.dpr, ang - 0.5, ang + 0.5);
      g.closePath(); g.fillStyle = 'rgba(255,255,255,.28)'; g.fill();
    }
    g.save(); g.translate(ax, ay); g.rotate(Math.PI - facing);
    const a = 7 * this.dpr;
    g.beginPath(); g.moveTo(0, -a * 1.3); g.lineTo(a * 0.85, a); g.lineTo(0, a * 0.5); g.lineTo(-a * 0.85, a); g.closePath();
    g.fillStyle = '#ffcf3a'; g.strokeStyle = '#2a2522'; g.lineWidth = 1.5 * this.dpr; g.fill(); g.stroke();
    g.restore();
  }
}
