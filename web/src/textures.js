// Texture library: PBR sets (albedo / normal / ORM) for facades, roofs, ground, walls and leaf cards.
//
// 1. If the texture-library agent's files exist, they are used:
//      assets/tex/facade_atlas.json   (facade module atlas + ground/roof/wall/leaf sets, see web/README.md)
// 2. Otherwise every set is generated procedurally at load (canvas 2D: albedo + height -> normal, roughness),
//    so the renderer is never untextured. Procedural textures are ARTISTIC stand-ins.
import * as THREE from 'three';

// ---------------------------------------------------------------- facade module slots (shader indices)
// 0-7 exist in the procedural atlas; 8-12 are extra variants (fall back to a similar procedural slot)
export const MODULES = ['koshi', 'noren', 'mushiko', 'lattice', 'shopfront', 'modern_upper', 'temple', 'plain',
  'koshi_dark', 'shop_open', 'itabari', 'glazed_railing', 'plaster_base', 'vermilion'];
const PROC_FALLBACK = { koshi_dark: 'koshi', shop_open: 'noren', itabari: 'plain', glazed_railing: 'lattice', plaster_base: 'plain', vermilion: 'temple' };
// texture-library module names (facade_atlas v1) for each slot
const LIB_MODULE = {
  koshi: 'machiya_gf_senkoshi', noren: 'machiya_gf_noren_entrance', mushiko: 'machiya_uf_mushikomado',
  lattice: 'machiya_uf_window_lattice', shopfront: 'modern_gf_shopfront', modern_upper: 'modern_uf_window',
  temple: 'white_plaster_timber', plain: 'machiya_uf_plaster', koshi_dark: 'machiya_gf_senkoshi_dark',
  shop_open: 'machiya_gf_shop_open', itabari: 'machiya_gf_itabari', glazed_railing: 'machiya_uf_glazed_railing',
  plaster_base: 'machiya_gf_plaster_base', vermilion: 'white_plaster_vermilion',
};
// texture-library set names (library.json) for each role
const LIB_SET = {
  kawara: 'roof_kawara_sangawara', ishidatami: 'ishidatami_granite', sett: 'setts_granite', asphalt: 'asphalt_worn',
  gravel: 'gravel', soil: 'earth_moss', stonewall: 'ishigaki_mossy', stoneStep: 'ishidatami_granite',
};
// foliage cards by species
export const LEAF_CARDS = { maple: 'maple_autumn', mapleGreen: 'maple_green', cherry: 'cherry_leaf', pine: 'pine_needles', broad: 'maple_green', shrub: 'shrub_azalea', bamboo: 'bamboo_leaves' };
export const M = Object.fromEntries(MODULES.map((m, i) => [m, i]));
export const ATLAS_GRID = [4, 2];          // columns, rows (procedural atlas)
export const BAY_M = 1.82;                 // one ken: module width in metres

// ---------------------------------------------------------------- helpers
const rnd = (() => { let a = 12345; return () => { a |= 0; a = (a + 0x6d2b79f5) | 0; let t = Math.imul(a ^ (a >>> 15), 1 | a); t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296; }; })();
function canvas(w, h) {
  const c = document.createElement('canvas'); c.width = w; c.height = h;
  return [c, c.getContext('2d', { willReadFrequently: true })];
}
const grey = (v) => { const x = Math.round(Math.max(0, Math.min(1, v)) * 255); return `rgb(${x},${x},${x})`; };
const rgb = (r, g, b) => `rgb(${Math.round(r * 255)},${Math.round(g * 255)},${Math.round(b * 255)})`;
// value jitter (shared factor, so stones/woods vary in lightness, not in hue) + a small hue drift
const jit = (c, a, hue = 0.04) => { const f = 1 + (rnd() - 0.5) * a; return c.map((v) => Math.max(0, Math.min(1, v * f * (1 + (rnd() - 0.5) * hue)))); };

// tileable value noise canvas
function noiseCanvas(size, cells, oct = 3) {
  const [c, g] = canvas(size, size);
  const img = g.createImageData(size, size);
  const grids = [];
  for (let o = 0; o < oct; o++) { const n = cells << o; grids.push({ n, v: Float32Array.from({ length: n * n }, rnd) }); }
  for (let y = 0; y < size; y++) for (let x = 0; x < size; x++) {
    let s = 0, a = 0.5, norm = 0;
    for (const { n, v } of grids) {
      const fx = x / size * n, fy = y / size * n, ix = Math.floor(fx), iy = Math.floor(fy), tx = fx - ix, ty = fy - iy;
      const sx = tx * tx * (3 - 2 * tx), sy = ty * ty * (3 - 2 * ty);
      const p = (i, j) => v[((j % n + n) % n) * n + ((i % n + n) % n)];
      s += a * ((p(ix, iy) * (1 - sx) + p(ix + 1, iy) * sx) * (1 - sy) + (p(ix, iy + 1) * (1 - sx) + p(ix + 1, iy + 1) * sx) * sy);
      norm += a; a *= 0.5;
    }
    const k = (y * size + x) * 4, val = Math.round(s / norm * 255);
    img.data[k] = img.data[k + 1] = img.data[k + 2] = val; img.data[k + 3] = 255;
  }
  g.putImageData(img, 0, 0);
  return c;
}

// height canvas -> tangent-space normal map canvas
function normalFromHeight(hc, strength = 2.0, wrap = true) {
  const w = hc.width, h = hc.height;
  const src = hc.getContext('2d').getImageData(0, 0, w, h).data;
  const [c, g] = canvas(w, h);
  const out = g.createImageData(w, h);
  const H = (x, y) => {
    if (wrap) { x = (x + w) % w; y = (y + h) % h; } else { x = Math.max(0, Math.min(w - 1, x)); y = Math.max(0, Math.min(h - 1, y)); }
    return src[(y * w + x) * 4] / 255;
  };
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
    const dx = (H(x + 1, y - 1) + 2 * H(x + 1, y) + H(x + 1, y + 1) - H(x - 1, y - 1) - 2 * H(x - 1, y) - H(x - 1, y + 1)) * strength;
    const dy = (H(x - 1, y + 1) + 2 * H(x, y + 1) + H(x + 1, y + 1) - H(x - 1, y - 1) - 2 * H(x, y - 1) - H(x + 1, y - 1)) * strength;
    // canvas y runs down, texture v runs up (flipY): +dy in canvas = -v
    let nx = -dx, ny = dy, nz = 1;
    const l = Math.hypot(nx, ny, nz); nx /= l; ny /= l; nz /= l;
    const k = (y * w + x) * 4;
    out.data[k] = (nx * 0.5 + 0.5) * 255; out.data[k + 1] = (ny * 0.5 + 0.5) * 255; out.data[k + 2] = (nz * 0.5 + 0.5) * 255; out.data[k + 3] = 255;
  }
  g.putImageData(out, 0, 0);
  return c;
}

// roughness canvas (+ cavity AO from height) -> ORM canvas (R ao, G roughness, B metal)
function ormFrom(rc, hc, aoAmt = 0.5) {
  const w = rc.width, h = rc.height;
  const r = rc.getContext('2d').getImageData(0, 0, w, h).data;
  const hh = hc ? hc.getContext('2d').getImageData(0, 0, w, h).data : null;
  const [c, g] = canvas(w, h);
  const out = g.createImageData(w, h);
  for (let i = 0; i < w * h; i++) {
    const k = i * 4;
    out.data[k] = hh ? 255 * (1 - aoAmt + aoAmt * Math.min(1, hh[k] / 160)) : 255;
    out.data[k + 1] = r[k]; out.data[k + 2] = 0; out.data[k + 3] = 255;
  }
  g.putImageData(out, 0, 0);
  return c;
}

function tex(c, { srgb = false, repeat = true, aniso = 8 } = {}) {
  const t = new THREE.CanvasTexture(c);
  t.colorSpace = srgb ? THREE.SRGBColorSpace : THREE.NoColorSpace;
  t.wrapS = t.wrapT = repeat ? THREE.RepeatWrapping : THREE.ClampToEdgeWrapping;
  t.anisotropy = aniso;
  t.generateMipmaps = true;
  t.minFilter = THREE.LinearMipmapLinearFilter;
  return t;
}

// three-channel set from three canvases
function set(albedo, height, rough, { normal = 2, ao = 0.5, wrap = true, size_m = [1, 1] } = {}) {
  return {
    map: tex(albedo, { srgb: true, repeat: wrap }),
    normalMap: tex(normalFromHeight(height, normal, wrap), { repeat: wrap }),
    ormMap: tex(ormFrom(rough, height, ao), { repeat: wrap }),
    size_m, procedural: true,
  };
}

// overlay grime / variation from a noise canvas
function grime(g, w, h, n, alpha, mode = 'multiply') {
  g.save(); g.globalAlpha = alpha; g.globalCompositeOperation = mode; g.drawImage(n, 0, 0, w, h); g.restore();
}

// ---------------------------------------------------------------- facade atlas (8 modules of 1 bay x 1 storey)
function facadeAtlas() {
  const CW = 256, CH = 512, [cols, rows] = ATLAS_GRID;
  const W = CW * cols, Hh = CH * rows;
  const [A, a] = canvas(W, Hh), [Hc, h] = canvas(W, Hh), [R, r] = canvas(W, Hh);
  const noise = noiseCanvas(256, 8, 4), fine = noiseCanvas(128, 32, 2);
  const BENGARA = [0.29, 0.13, 0.08], DARKWOOD = [0.16, 0.1, 0.07], PLASTER = [0.82, 0.74, 0.6], EARTH = [0.66, 0.5, 0.34];
  for (let m = 0; m < cols * rows; m++) {
    const ox = (m % cols) * CW, oy = Math.floor(m / cols) * CH;
    // module-local helpers: x,y in 0..1 with y = 0 at the FLOOR (bottom of the cell)
    const R_ = (x0, y0, x1, y1, col, ht, ro) => {
      const X = ox + x0 * CW, Y = oy + (1 - y1) * CH, Wd = (x1 - x0) * CW, Ht = (y1 - y0) * CH;
      a.fillStyle = Array.isArray(col) ? rgb(...col) : col; a.fillRect(X, Y, Wd, Ht);
      h.fillStyle = grey(ht); h.fillRect(X, Y, Wd, Ht);
      r.fillStyle = grey(ro); r.fillRect(X, Y, Wd, Ht);
    };
    const name = MODULES[m];
    // base layer: plaster / boards
    R_(0, 0, 1, 1, jit(PLASTER, 0.05), 0.55, 0.9);
    const posts = () => { R_(0, 0, 0.07, 1, DARKWOOD, 0.75, 0.75); R_(0.93, 0, 1, 1, DARKWOOD, 0.75, 0.75); };
    const beam = (y0, y1) => R_(0, y0, 1, y1, DARKWOOD, 0.8, 0.7);
    const stoneBase = () => R_(0, 0, 1, 0.05, [0.42, 0.41, 0.4], 0.62, 0.85);
    if (name === 'koshi' || name === 'noren') {
      stoneBase();
      R_(0.07, 0.05, 0.93, 0.74, [0.04, 0.03, 0.025], 0.2, 0.9);           // dark interior
      if (name === 'koshi') {
        for (let x = 0.08; x < 0.92; x += 0.05) R_(x, 0.05, x + 0.028, 0.74, jit(BENGARA, 0.15), 0.72, 0.65);
        for (const y of [0.05, 0.4, 0.71]) R_(0.07, y, 0.93, y + 0.03, BENGARA, 0.78, 0.65);
      } else {
        R_(0.07, 0.05, 0.93, 0.3, [0.5, 0.33, 0.16], 0.25, 0.9);            // warm lit floor
        const indigo = jit([0.07, 0.11, 0.25], 0.2);
        for (let i = 0; i < 3; i++) R_(0.1 + i * 0.27, 0.42, 0.34 + i * 0.27, 0.74, indigo, 0.5, 0.97);
        a.fillStyle = 'rgb(235,228,210)'; a.beginPath(); a.arc(ox + 0.5 * CW, oy + (1 - 0.6) * CH, 0.1 * CW, 0, 7); a.fill();
      }
      posts(); beam(0.74, 0.8);
      R_(0.07, 0.8, 0.93, 0.97, jit(EARTH, 0.08), 0.55, 0.92);
      beam(0.97, 1);
    } else if (name === 'mushiko') {
      beam(0, 0.1);
      R_(0, 0.1, 1, 0.97, jit(EARTH, 0.06), 0.55, 0.93);
      for (let i = 0; i < 4; i++) {
        const x = 0.16 + i * 0.19;
        R_(x, 0.32, x + 0.09, 0.78, [0.06, 0.05, 0.04], 0.25, 0.9);
        a.fillStyle = rgb(...EARTH); a.beginPath(); a.arc(ox + (x + 0.045) * CW, oy + (1 - 0.78) * CH, 0.045 * CW, Math.PI, 0); a.fill();
      }
      beam(0.97, 1);
    } else if (name === 'lattice') {
      beam(0, 0.1);
      R_(0, 0.1, 1, 1, jit(DARKWOOD, 0.1), 0.6, 0.8);
      for (let x = 0; x < 1; x += 0.08) R_(x, 0.1, x + 0.008, 1, [0.08, 0.05, 0.035], 0.45, 0.8);  // board joints
      R_(0.15, 0.3, 0.85, 0.82, [0.85, 0.8, 0.66], 0.35, 0.95);           // shoji
      for (let x = 0.15; x < 0.86; x += 0.07) R_(x, 0.3, x + 0.018, 0.82, BENGARA, 0.7, 0.7);
      for (let y = 0.3; y < 0.83; y += 0.104) R_(0.15, y, 0.85, y + 0.012, BENGARA, 0.7, 0.7);
      R_(0.12, 0.27, 0.88, 0.3, DARKWOOD, 0.85, 0.7);
    } else if (name === 'shopfront') {
      R_(0, 0, 1, 1, [0.62, 0.6, 0.57], 0.55, 0.6);
      R_(0.05, 0.03, 0.95, 0.72, [0.1, 0.13, 0.16], 0.3, 0.08);            // glass
      R_(0.05, 0.03, 0.95, 0.25, [0.32, 0.22, 0.12], 0.3, 0.2);            // lit interior seen through
      for (const x of [0.05, 0.49, 0.93]) R_(x, 0.03, x + 0.02, 0.72, [0.55, 0.56, 0.58], 0.7, 0.3);
      R_(0, 0.74, 1, 0.9, jit([0.55, 0.12, 0.1], 0.4), 0.65, 0.5);          // sign band
      R_(0, 0, 1, 0.03, [0.3, 0.3, 0.3], 0.6, 0.7);
    } else if (name === 'modern_upper') {
      R_(0, 0, 1, 1, jit([0.74, 0.71, 0.66], 0.06), 0.55, 0.85);
      for (let y = 0; y < 1; y += 0.05) R_(0, y, 1, y + 0.004, [0.6, 0.58, 0.55], 0.5, 0.85); // tile lines
      R_(0.18, 0.28, 0.82, 0.82, [0.5, 0.52, 0.55], 0.65, 0.3);             // aluminium frame
      R_(0.21, 0.31, 0.79, 0.79, [0.12, 0.15, 0.19], 0.3, 0.06);            // glass
      R_(0.495, 0.31, 0.505, 0.79, [0.5, 0.52, 0.55], 0.65, 0.3);
      R_(0.15, 0.08, 0.85, 0.1, [0.4, 0.4, 0.42], 0.8, 0.4);                // rail
    } else if (name === 'temple') {
      R_(0, 0, 1, 0.16, [0.3, 0.29, 0.28], 0.62, 0.85);                     // stone base
      R_(0, 0.16, 1, 1, [0.9, 0.88, 0.82], 0.55, 0.92);                     // white plaster
      posts(); beam(0.7, 0.77); beam(0.94, 1); beam(0.16, 0.2);
    } else {
      // plain side wall: yakisugi boards below, earth plaster above
      R_(0, 0, 1, 0.45, jit([0.11, 0.09, 0.075], 0.1), 0.55, 0.85);
      for (let x = 0; x < 1; x += 0.1) R_(x, 0, x + 0.01, 0.45, [0.05, 0.04, 0.03], 0.42, 0.85);
      R_(0, 0.45, 1, 0.48, DARKWOOD, 0.75, 0.75);
      R_(0, 0.48, 1, 1, jit(EARTH, 0.08), 0.55, 0.93);
    }
    // weathering: soft noise and darkening toward the ground (splash) and under the eave
    a.save(); a.beginPath(); a.rect(ox, oy, CW, CH); a.clip();
    a.globalAlpha = 0.22; a.globalCompositeOperation = 'multiply'; a.drawImage(noise, ox, oy, CW, CH);
    a.globalAlpha = 0.12; a.drawImage(fine, ox, oy, CW, CH);
    const gr = a.createLinearGradient(0, oy + CH, 0, oy);
    gr.addColorStop(0, 'rgba(60,50,40,0.35)'); gr.addColorStop(0.12, 'rgba(255,255,255,0)'); gr.addColorStop(0.9, 'rgba(255,255,255,0)'); gr.addColorStop(1, 'rgba(40,35,30,0.35)');
    a.globalAlpha = 1; a.fillStyle = gr; a.fillRect(ox, oy, CW, CH);
    a.restore();
    h.save(); h.globalAlpha = 0.08; h.globalCompositeOperation = 'overlay'; h.drawImage(fine, ox, oy, CW, CH); h.restore();
  }
  return set(A, Hc, R, { normal: 2.5, ao: 0.6, wrap: false, size_m: [BAY_M * cols, 3 * rows] });
}

// ---------------------------------------------------------------- tileable sets
function kawara() {
  const S = 512, [A, a] = canvas(S, S), [Hc, h] = canvas(S, S), [R, r] = canvas(S, S);
  const cols = 4, rows = 4, cw = S / cols, rh = S / rows;
  const n = noiseCanvas(128, 16, 3);
  for (let j = 0; j < rows; j++) for (let i = 0; i < cols; i++) {
    const x = i * cw, y = j * rh;
    // concave pan (hira-gawara) + convex round tile edge: horizontal cross-section shading
    const gH = h.createLinearGradient(x, 0, x + cw, 0);
    gH.addColorStop(0, grey(0.75)); gH.addColorStop(0.18, grey(0.35)); gH.addColorStop(0.5, grey(0.25)); gH.addColorStop(0.82, grey(0.35)); gH.addColorStop(1, grey(0.75));
    h.fillStyle = gH; h.fillRect(x, y, cw, rh);
    // overlap step: bottom edge of each course is raised
    const gV = h.createLinearGradient(0, y, 0, y + rh);
    gV.addColorStop(0, 'rgba(0,0,0,0.35)'); gV.addColorStop(0.85, 'rgba(255,255,255,0.0)'); gV.addColorStop(1, 'rgba(255,255,255,0.35)');
    h.fillStyle = gV; h.fillRect(x, y, cw, rh);
    const base = jit([0.2, 0.21, 0.23], 0.12);
    a.fillStyle = rgb(...base); a.fillRect(x, y, cw, rh);
    const gA = a.createLinearGradient(x, 0, x + cw, 0);
    gA.addColorStop(0, 'rgba(255,255,255,0.22)'); gA.addColorStop(0.2, 'rgba(0,0,0,0.0)'); gA.addColorStop(0.5, 'rgba(0,0,0,0.25)'); gA.addColorStop(0.8, 'rgba(0,0,0,0)'); gA.addColorStop(1, 'rgba(255,255,255,0.22)');
    a.fillStyle = gA; a.fillRect(x, y, cw, rh);
    a.fillStyle = 'rgba(0,0,0,0.45)'; a.fillRect(x, y + rh - 4, cw, 4);
  }
  r.fillStyle = grey(0.45); r.fillRect(0, 0, S, S);
  grime(a, S, S, n, 0.35); grime(r, S, S, n, 0.4, 'overlay');
  return set(A, Hc, R, { normal: 3, ao: 0.5, size_m: [0.28 * cols, 0.25 * rows] });
}

function slabs({ S = 512, size_m = 2.4, rowH = 0.3, len = [0.45, 1.0], tone = [0.5, 0.47, 0.42], joint = 0.012, var_ = 0.25 } = {}) {
  const [A, a] = canvas(S, S), [Hc, h] = canvas(S, S), [R, r] = canvas(S, S);
  const px = S / size_m;
  a.fillStyle = 'rgb(40,38,34)'; a.fillRect(0, 0, S, S);
  h.fillStyle = grey(0.15); h.fillRect(0, 0, S, S);
  r.fillStyle = grey(0.9); r.fillRect(0, 0, S, S);
  const n = noiseCanvas(256, 16, 4);
  for (let y = 0; y < S; y += rowH * px) {
    let x = -rnd() * len[1] * px;
    while (x < S) {
      const L = (len[0] + rnd() * (len[1] - len[0])) * px;
      const c = jit(tone, var_);
      const j = joint * px;
      for (const ox of [0, -S, S]) {            // wrap horizontally (tileable)
        a.fillStyle = rgb(...c); a.fillRect(x + ox + j, y + j, L - 2 * j, rowH * px - 2 * j);
        h.fillStyle = grey(0.55 + rnd() * 0.15); h.fillRect(x + ox + j, y + j, L - 2 * j, rowH * px - 2 * j);
        r.fillStyle = grey(0.6 + rnd() * 0.2); r.fillRect(x + ox + j, y + j, L - 2 * j, rowH * px - 2 * j);
      }
      x += L;
    }
  }
  grime(a, S, S, n, 0.3); grime(h, S, S, n, 0.25, 'overlay');
  return set(A, Hc, R, { normal: 2.2, ao: 0.6, size_m: [size_m, size_m] });
}

function speckle({ S = 512, size_m = 4, tone = [0.12, 0.12, 0.13], dots = 9000, dotTone = [0.25, 0.24, 0.23], rough = 0.85, cells = 16, h0 = 0.5 } = {}) {
  const [A, a] = canvas(S, S), [Hc, h] = canvas(S, S), [R, r] = canvas(S, S);
  const n = noiseCanvas(256, cells, 4);
  a.fillStyle = rgb(...tone); a.fillRect(0, 0, S, S);
  h.fillStyle = grey(h0); h.fillRect(0, 0, S, S);
  r.fillStyle = grey(rough); r.fillRect(0, 0, S, S);
  for (let i = 0; i < dots; i++) {
    const x = rnd() * S, y = rnd() * S, s = 0.6 + rnd() * 2.2;
    a.fillStyle = rgb(...jit(dotTone, 0.6)); a.fillRect(x, y, s, s);
    h.fillStyle = grey(0.55 + rnd() * 0.4); h.fillRect(x, y, s, s);
  }
  grime(a, S, S, n, 0.4); grime(h, S, S, n, 0.3, 'overlay'); grime(r, S, S, n, 0.25, 'overlay');
  return set(A, Hc, R, { normal: 1.6, ao: 0.4, size_m: [size_m, size_m] });
}

function stoneWall() {
  const S = 512, [A, a] = canvas(S, S), [Hc, h] = canvas(S, S), [R, r] = canvas(S, S);
  a.fillStyle = 'rgb(70,66,60)'; a.fillRect(0, 0, S, S);
  h.fillStyle = grey(0.2); h.fillRect(0, 0, S, S);
  r.fillStyle = grey(0.9); r.fillRect(0, 0, S, S);
  const n = noiseCanvas(256, 12, 4);
  let y = 0;
  while (y < S) {
    const rh = 40 + rnd() * 50; let x = -rnd() * 80;
    while (x < S) {
      const w = 60 + rnd() * 110;
      for (const ox of [0, -S, S]) {
        a.fillStyle = rgb(...jit([0.52, 0.5, 0.46], 0.25)); a.fillRect(x + ox + 3, y + 3, w - 6, Math.min(rh, S - y) - 6);
        const g = h.createRadialGradient(x + ox + w / 2, y + rh / 2, 2, x + ox + w / 2, y + rh / 2, w * 0.6);
        g.addColorStop(0, grey(0.85)); g.addColorStop(1, grey(0.45));
        h.fillStyle = g; h.fillRect(x + ox + 3, y + 3, w - 6, Math.min(rh, S - y) - 6);
      }
      x += w;
    }
    y += rh;
  }
  grime(a, S, S, n, 0.35);
  return set(A, Hc, R, { normal: 3, ao: 0.6, size_m: [2, 2] });
}

function leafCard() {
  const S = 256, [A, a] = canvas(S, S);
  a.clearRect(0, 0, S, S);
  const leaf = (x, y, s, rot, tone) => {
    a.save(); a.translate(x, y); a.rotate(rot); a.scale(s, s);
    a.fillStyle = rgb(...tone);
    a.beginPath();
    for (let k = 0; k < 5; k++) {           // five-lobed maple-like leaf
      const t = -Math.PI / 2 + (k - 2) * 0.55;
      a.moveTo(0, 0);
      a.quadraticCurveTo(Math.cos(t - 0.3) * 0.55, Math.sin(t - 0.3) * 0.55, Math.cos(t), Math.sin(t));
      a.quadraticCurveTo(Math.cos(t + 0.3) * 0.55, Math.sin(t + 0.3) * 0.55, 0, 0);
    }
    a.fill();
    a.strokeStyle = 'rgba(0,0,0,0.25)'; a.lineWidth = 0.04; a.beginPath(); a.moveTo(0, 0.25); a.lineTo(0, -0.8); a.stroke();
    a.restore();
  };
  // twigs
  a.strokeStyle = 'rgb(60,45,35)'; a.lineWidth = 2;
  for (let i = 0; i < 5; i++) { a.beginPath(); a.moveTo(S / 2, S * 0.95); a.quadraticCurveTo(S * (0.2 + rnd() * 0.6), S * 0.5, S * (0.1 + rnd() * 0.8), S * (0.1 + rnd() * 0.3)); a.stroke(); }
  for (let i = 0; i < 70; i++) {
    const ang = rnd() * 6.28, rr = Math.sqrt(rnd()) * S * 0.42;
    const v = 0.55 + rnd() * 0.45;
    leaf(S / 2 + Math.cos(ang) * rr, S / 2 + Math.sin(ang) * rr * 0.9, 13 + rnd() * 9, rnd() * 6.28, [v, v * (0.92 + rnd() * 0.08), v * 0.85]);
  }
  const t = tex(A, { srgb: true, repeat: false, aniso: 4 });
  t.premultiplyAlpha = false;
  return { map: t, procedural: true };
}

// ---------------------------------------------------------------- external library (texture agent)
// assets/tex/facade_atlas.json ("facade_atlas v1": files{albedo,normal,orm,emit}, modules{name:{uv_rect,...}}),
// assets/tex/library.json (sets{name:{files{albedo,normal,orm}, size_m}}), assets/tex/foliage_atlas.json
// (files, cards{name:{uv_rect,size_m}}). uv_rect = [u0, v0, u1, v1], origin bottom-left. Missing items keep
// the procedural fallback.
const texLoader = new THREE.TextureLoader();
async function loadTex(url, srgb, repeat = true) {
  const t = await texLoader.loadAsync(url);
  t.colorSpace = srgb ? THREE.SRGBColorSpace : THREE.NoColorSpace;
  t.wrapS = t.wrapT = repeat ? THREE.RepeatWrapping : THREE.ClampToEdgeWrapping;
  t.anisotropy = 8;
  return t;
}
async function loadSetFiles(dir, files, repeat) {
  const [map, normalMap, ormMap] = await Promise.all([
    files.albedo ? loadTex(dir + files.albedo, true, repeat) : null,
    files.normal ? loadTex(dir + files.normal, false, repeat) : null,
    files.orm ? loadTex(dir + files.orm, false, repeat) : null,
  ]);
  return { map, normalMap, ormMap };
}
async function fetchJson(url) {
  const r = await fetch(url, { cache: 'no-store' });
  if (!r.ok) throw new Error(url + ' ' + r.status);
  return r.json();
}
async function loadExternal(cfg, lib) {
  const out = { ...lib };
  const used = [];
  const jobs = [];
  if (cfg.facade) {
    jobs.push((async () => {
      const dir = cfg.facade.replace(/[^/]*$/, '');
      const j = await fetchJson(cfg.facade);
      const f = j.files || {};
      const [s, emitMap] = await Promise.all([loadSetFiles(dir, f, false), f.emit ? loadTex(dir + f.emit, false, false) : null]);
      const rects = MODULES.map((name, i) => {
        const m = j.modules && j.modules[LIB_MODULE[name]];
        return m && m.uv_rect ? m.uv_rect : lib.facade.rects[i];
      });
      if (!s.map) return;
      out.facade = { ...lib.facade, ...Object.fromEntries(Object.entries(s).filter(([, v]) => v)), rects, emitMap, external: true };
      // procedural normal/orm rects do not match the library atlas: drop them if the library has none
      if (!s.normalMap) out.facade.normalMap = null;
      if (!s.ormMap) out.facade.ormMap = null;
      used.push('facade atlas');
    })().catch((e) => console.warn('facade atlas failed, procedural kept', e)));
  }
  if (cfg.library) {
    jobs.push((async () => {
      const dir = cfg.library.replace(/[^/]*$/, '');
      const j = await fetchJson(cfg.library);
      const sets = j.sets || {};
      const cache = new Map();
      await Promise.all(Object.entries(LIB_SET).map(async ([role, name]) => {
        const d = sets[name];
        if (!d || !d.files) return;
        if (!cache.has(name)) cache.set(name, loadSetFiles(dir, d.files, true));
        const v = await cache.get(name);
        if (!v.map) return;
        out[role] = { ...lib[role], ...Object.fromEntries(Object.entries(v).filter(([, x]) => x)), size_m: d.size_m || lib[role].size_m, procedural: false, name };
        used.push(role + '=' + name);
      }));
    })().catch((e) => console.warn('texture library failed, procedural kept', e)));
  }
  if (cfg.foliage) {
    jobs.push((async () => {
      const dir = cfg.foliage.replace(/[^/]*$/, '');
      const j = await fetchJson(cfg.foliage);
      const f = j.files || {};
      const map = f.albedo ? await loadTex(dir + f.albedo, true, false) : null;
      if (!map) return;
      const cards = Object.fromEntries(Object.entries(j.cards || {}).map(([k, v]) => [k, v.uv_rect]));
      out.leaf = { map, cards, procedural: false };
      used.push('foliage cards');
    })().catch((e) => console.warn('foliage atlas failed, procedural kept', e)));
  }
  await Promise.all(jobs);
  out.source = used.length ? 'texture library: ' + used.join(', ') + (used.length < 10 ? ' (+ procedural fallbacks)' : '') : lib.source;
  return out;
}

// texUrl: path of the texture library json as listed by dist/manifest.json (null = procedural only;
// the page never probes for files that may not exist, so a missing library logs no 404)
export async function loadTextureLibrary(texCfg) {
  const t0 = performance.now();
  const procRect = (name) => {
    const i = MODULES.indexOf(PROC_FALLBACK[name] || name), [c, r] = [i % ATLAS_GRID[0], Math.floor(i / ATLAS_GRID[0])];
    const row = ATLAS_GRID[1] - 1 - r;
    return [c / ATLAS_GRID[0], row / ATLAS_GRID[1], (c + 1) / ATLAS_GRID[0], (row + 1) / ATLAS_GRID[1]];
  };
  const lib = {
    facade: { ...facadeAtlas(), rects: MODULES.map(procRect), bay_m: BAY_M, storey_m: 3.0, emitMap: null },
    kawara: kawara(),
    ishidatami: slabs({ size_m: 2.4, rowH: 0.3, len: [0.45, 1.0], tone: [0.55, 0.5, 0.43] }),
    sett: slabs({ size_m: 1.2, rowH: 0.1, len: [0.09, 0.14], tone: [0.46, 0.42, 0.36], joint: 0.008, var_: 0.4 }),
    stoneStep: slabs({ size_m: 2.0, rowH: 0.35, len: [0.6, 1.4], tone: [0.55, 0.53, 0.5], var_: 0.15 }),
    asphalt: speckle({ size_m: 4, tone: [0.1, 0.1, 0.11], dotTone: [0.22, 0.21, 0.2], dots: 14000, rough: 0.8 }),
    gravel: speckle({ size_m: 2, tone: [0.42, 0.37, 0.3], dotTone: [0.55, 0.5, 0.42], dots: 26000, rough: 0.92, h0: 0.4 }),
    soil: speckle({ size_m: 4, tone: [0.2, 0.16, 0.1], dotTone: [0.14, 0.2, 0.08], dots: 6000, rough: 0.95, cells: 8 }),
    stonewall: stoneWall(),
    leaf: { ...leafCard(), cards: {} },
    source: 'procedural (artistic stand-in)',
  };
  let out = lib;
  const cfg = typeof texCfg === 'string' ? { facade: texCfg } : (texCfg || null);
  if (cfg) out = await loadExternal(cfg, lib);
  out.ms = Math.round(performance.now() - t0);
  return out;
}
