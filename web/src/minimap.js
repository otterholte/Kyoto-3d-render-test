// North-up mini-map drawn from assets/minimap.json (PLATEAU footprints, OSM streets/steps/barriers),
// the 400 m boundary, landmarks and the player arrow. Tap toggles local / whole-area view.
import { PLACES } from './config.js';

const EXT = 230;      // static layer covers -EXT..EXT m
const PPM = 3;        // static layer pixels per metre

export class MiniMap {
  constructor(canvas, wrap, data) {
    this.canvas = canvas; this.wrap = wrap; this.data = data;
    this.full = false;
    this.ctx = canvas.getContext('2d');
    this.layer = this.drawStatic();
    this.dpr = Math.min(devicePixelRatio || 1, 2);
    const toggle = () => {
      this.full = !this.full;
      wrap.classList.toggle('full', this.full);
      wrap.setAttribute('aria-pressed', String(this.full));
    };
    wrap.setAttribute('role', 'button');
    wrap.tabIndex = 0;
    wrap.setAttribute('aria-pressed', 'false');
    wrap.setAttribute('aria-label', 'Mini-map, north up. Activate to switch between the local view and the whole area.');
    wrap.addEventListener('click', toggle);
    wrap.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggle(); } });
    // ResizeObserver also catches rotation / panel-hidden states; 0-sized (hidden) boxes are ignored
    if (typeof ResizeObserver !== 'undefined') new ResizeObserver(() => this.resize()).observe(wrap);
    else addEventListener('resize', () => this.resize());
    this.resize();
  }

  resize() {
    const r = this.wrap.getBoundingClientRect();
    if (r.width < 2 || r.height < 2) return;      // hidden: keep the last good size
    const dpr = Math.min(devicePixelRatio || 1, 2);
    const w = Math.round(r.width * dpr), h = Math.round(r.height * dpr);
    if (w === this.canvas.width && h === this.canvas.height) return;
    this.canvas.width = w; this.canvas.height = h;
    this.dpr = dpr;
  }

  drawStatic() {
    const S = EXT * 2 * PPM;
    const c = document.createElement('canvas');
    c.width = c.height = S;
    const g = c.getContext('2d');
    const X = (x) => (x + EXT) * PPM, Y = (n) => (EXT - n) * PPM;
    g.fillStyle = '#ddd2bb'; g.fillRect(0, 0, S, S);
    // streets
    g.lineCap = 'round'; g.lineJoin = 'round';
    const streets = this.data.streets.slice().sort((a, b) => (a.hw === 'steps') - (b.hw === 'steps'));
    for (const s of streets) {
      const stone = /paving|sett|stone/.test(s.sf || '') || s.hw === 'pedestrian';
      g.strokeStyle = s.hw === 'steps' ? '#9a8f80' : stone ? '#f6efe0' : /footway|path|track/.test(s.hw) ? '#efe6d3' : '#fbfaf6';
      g.lineWidth = Math.max(1.6, Math.min(s.w, 14)) * PPM;
      g.beginPath();
      for (let i = 0; i < s.pts.length; i += 2) {
        const f = i ? 'lineTo' : 'moveTo';
        g[f](X(s.pts[i]), Y(s.pts[i + 1]));
      }
      g.stroke();
      if (s.hw === 'steps') {
        // hatch the stairs
        g.strokeStyle = '#6f655a'; g.lineWidth = 0.35 * PPM; g.setLineDash([0.25 * PPM, 0.55 * PPM]);
        g.stroke(); g.setLineDash([]);
      }
    }
    // buildings
    g.fillStyle = '#a99782'; g.strokeStyle = '#7f6f5f'; g.lineWidth = 0.25 * PPM;
    for (const b of this.data.buildings) {
      g.beginPath();
      for (let i = 0; i < b.length; i += 2) { const f = i ? 'lineTo' : 'moveTo'; g[f](X(b[i]), Y(b[i + 1])); }
      g.closePath(); g.fill(); g.stroke();
    }
    // barriers
    g.strokeStyle = '#5d5248'; g.lineWidth = 0.4 * PPM;
    for (const b of this.data.barriers) {
      g.beginPath();
      for (let i = 0; i < b.length; i += 2) { const f = i ? 'lineTo' : 'moveTo'; g[f](X(b[i]), Y(b[i + 1])); }
      g.stroke();
    }
    // outside boundary veil + boundary
    g.fillStyle = 'rgba(40,44,70,0.35)';
    g.fillRect(0, 0, S, X(-200)); g.fillRect(0, X(200), S, S - X(200));
    g.fillRect(0, X(-200), X(-200), X(200) - X(-200)); g.fillRect(X(200), X(-200), S - X(200), X(200) - X(-200));
    g.strokeStyle = '#c4553b'; g.lineWidth = 1.2 * PPM; g.setLineDash([3 * PPM, 2 * PPM]);
    g.strokeRect(X(-200), Y(200), 400 * PPM, 400 * PPM); g.setLineDash([]);
    // pagoda
    g.fillStyle = '#c4553b';
    g.beginPath(); g.arc(X(9.67), Y(83.46), 4.2 * PPM, 0, Math.PI * 2); g.fill();
    return c;
  }

  draw(px, pn, heading, camYaw) {
    const g = this.ctx, W = this.canvas.width, H = this.canvas.height;
    const span = this.full ? 430 : 130;           // metres across
    const s = W / span;                           // px per metre
    const cx = this.full ? 0 : px, cn = this.full ? 0 : pn;
    g.setTransform(1, 0, 0, 1, 0, 0);
    g.fillStyle = '#cfc4ad'; g.fillRect(0, 0, W, H);
    const k = s / PPM;
    g.setTransform(k, 0, 0, k, W / 2 - (cx + EXT) * PPM * k, H / 2 - (EXT - cn) * PPM * k);
    g.imageSmoothingEnabled = true;
    g.drawImage(this.layer, 0, 0);
    g.setTransform(1, 0, 0, 1, 0, 0);
    const SX = (x) => W / 2 + (x - cx) * s, SY = (n) => H / 2 - (n - cn) * s;
    // landmarks
    g.font = `${Math.round(10 * this.dpr)}px system-ui, sans-serif`;
    for (const p of PLACES) {
      const x = SX(p.x), y = SY(p.n);
      if (x < -10 || y < -10 || x > W + 10 || y > H + 10) continue;
      g.fillStyle = '#2a2522'; g.beginPath(); g.arc(x, y, 2.2 * this.dpr, 0, 7); g.fill();
    }
    // view cone
    const ax = SX(px), ay = SY(pn);
    const dpr = this.dpr;
    g.fillStyle = 'rgba(255,240,200,0.35)';
    g.beginPath(); g.moveTo(ax, ay);
    const camDirX = -Math.sin(camYaw), camDirN = Math.cos(camYaw); // camera forward in (east, north)
    const a0 = Math.atan2(-camDirN, camDirX);
    g.arc(ax, ay, 26 * dpr, a0 - 0.5, a0 + 0.5); g.closePath(); g.fill();
    // player arrow (heading = yaw in three: facing vector (sin, cos) in x,z => east = sin, north = -cos)
    const hx = Math.sin(heading), hn = -Math.cos(heading);
    const ang = Math.atan2(-hn, hx);
    g.save(); g.translate(ax, ay); g.rotate(ang);
    g.fillStyle = '#c4553b'; g.strokeStyle = '#fff'; g.lineWidth = 1.6 * dpr;
    g.beginPath(); g.moveTo(9 * dpr, 0); g.lineTo(-6 * dpr, 6 * dpr); g.lineTo(-3 * dpr, 0); g.lineTo(-6 * dpr, -6 * dpr); g.closePath();
    g.fill(); g.stroke(); g.restore();
  }
}
