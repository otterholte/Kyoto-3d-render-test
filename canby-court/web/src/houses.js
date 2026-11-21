// Placeholder houses from data/processed/houses.json (measured footprints, inferred eave/ridge heights, observed roof
// form, ridge bearing and roof colour) and context_buildings.json (footprint + floors only).
//  - walls: footprint extruded from below grade to the roof line (gable ends follow the roof), procedural lap siding,
//    windows per storey, a garage door on the side the evidence names, a front door where asked (artistic)
//  - roofs: height field "distance to the eave line x pitch" (= hip roof; edges across the ridge are skipped for
//    side-gable roofs), clamped at the inferred ridge height, 0.45 m overhang with fascia + soffit
// Facade colours are not in the evidence (gap): an artistic PNW palette is used.
import * as THREE from 'three';
import { mulberry, polyArea, inPoly } from './util.js';
import { SU } from './shared.js';

const OVERHANG = 0.45;
const STOREY = 2.75;
const WALL_COLOURS = ['#8e9a9f', '#b9ad95', '#7f8c7a', '#d9d6cc', '#9c8f7e', '#6f7e8a', '#c2b8a3', '#a7a89b', '#5f6b64', '#cfc5b1'];
const DIRS = { north: [0, 1], south: [0, -1], east: [1, 0], west: [-1, 0], ne: [0.707, 0.707], nw: [-0.707, 0.707], se: [0.707, -0.707], sw: [-0.707, -0.707] };

export const facadeUniforms = { uSeason: SU.uSeason, uNoise: SU.uNoise };

function srgb(hex) { const c = new THREE.Color(hex); return [c.r, c.g, c.b]; }   // Color() converts hex (sRGB) to linear

function ccw(poly) {
  let p = poly.slice();
  if (p.length > 2 && p[0][0] === p[p.length - 1][0] && p[0][1] === p[p.length - 1][1]) p.pop();
  if (polyArea(p) < 0) p.reverse();
  // drop near-duplicate / collinear points
  const out = [];
  for (let i = 0; i < p.length; i++) {
    const a = p[(i + p.length - 1) % p.length], b = p[i], c = p[(i + 1) % p.length];
    if (Math.hypot(b[0] - a[0], b[1] - a[1]) < 0.15) continue;
    const cr = (b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0]);
    if (Math.abs(cr) < 0.02 * Math.hypot(b[0] - a[0], b[1] - a[1]) * Math.hypot(c[0] - b[0], c[1] - b[1])) continue;
    out.push(b);
  }
  return out.length >= 3 ? out : p;
}

function edgeNormal(a, b) { const dx = b[0] - a[0], dy = b[1] - a[1], l = Math.hypot(dx, dy) || 1; return [dy / l, -dx / l]; } // outward for CCW

function offsetPoly(p, o) {
  const n = p.length, out = [];
  for (let i = 0; i < n; i++) {
    const a = p[(i + n - 1) % n], b = p[i], c = p[(i + 1) % n];
    const n1 = edgeNormal(a, b), n2 = edgeNormal(b, c);
    let mx = n1[0] + n2[0], my = n1[1] + n2[1];
    const d = 1 + n1[0] * n2[0] + n1[1] * n2[1];
    const k = d > 0.25 ? o / d : o / 0.25;
    out.push([b[0] + mx * k, b[1] + my * k]);
  }
  return out;
}

function segDist(px, py, a, b) {
  const dx = b[0] - a[0], dy = b[1] - a[1];
  const t = Math.max(0, Math.min(1, ((px - a[0]) * dx + (py - a[1]) * dy) / (dx * dx + dy * dy || 1)));
  return Math.hypot(px - a[0] - dx * t, py - a[1] - dy * t);
}
function nearestOnPoly(px, py, poly) {
  let best = Infinity, bx = px, by = py;
  for (let i = 0; i < poly.length; i++) {
    const a = poly[i], b = poly[(i + 1) % poly.length];
    const dx = b[0] - a[0], dy = b[1] - a[1];
    const t = Math.max(0, Math.min(1, ((px - a[0]) * dx + (py - a[1]) * dy) / (dx * dx + dy * dy || 1)));
    const qx = a[0] + dx * t, qy = a[1] + dy * t, d = Math.hypot(px - qx, py - qy);
    if (d < best) { best = d; bx = qx; by = qy; }
  }
  return [bx, by];
}

// one building -> arrays appended to the shared buffers
function building(spec, terrain, B, rnd) {
  const fp = ccw(spec.fp);
  if (fp.length < 3) return;
  const n = fp.length;
  // ground under the footprint
  let gMin = Infinity, gSum = 0, gc = 0;
  for (let i = 0; i < n; i++) {
    const a = fp[i], b = fp[(i + 1) % n];
    for (let t = 0; t < 1; t += 0.25) { const z = terrain.height(a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t); gMin = Math.min(gMin, z); gSum += z; gc++; }
  }
  const gMed = spec.ground?.median ?? gSum / gc;
  gMin = Math.min(gMin, spec.ground?.min ?? gMin);
  const floorZ = gMed + 0.45;
  const eaveZ = gMed + spec.eaveH;
  const ridgeZ = gMed + spec.ridgeH;
  const tanP = Math.tan(THREE.MathUtils.degToRad(spec.pitchDeg));
  // gable edges: side-gable roofs skip the edges across the ridge (the walls there rise to the roof)
  const form = (spec.roofForm || '').toLowerCase();
  const isGable = /gable/.test(form) && !/hip/.test(form);
  let rdir = null;
  if (spec.ridgeBearing != null) { const b = THREE.MathUtils.degToRad(spec.ridgeBearing); rdir = [Math.sin(b), Math.cos(b)]; }
  const roofPoly = offsetPoly(fp, OVERHANG);
  const eaveEdges = [];
  for (let i = 0; i < n; i++) {
    const a = roofPoly[i], b = roofPoly[(i + 1) % n];
    const dx = b[0] - a[0], dy = b[1] - a[1], l = Math.hypot(dx, dy) || 1;
    const across = rdir && Math.abs((dx * rdir[0] + dy * rdir[1]) / l) < 0.35;
    if (isGable && across) continue;
    eaveEdges.push([a, b]);
  }
  if (!eaveEdges.length) for (let i = 0; i < n; i++) eaveEdges.push([roofPoly[i], roofPoly[(i + 1) % n]]);
  const baseZ = eaveZ - OVERHANG * tanP;
  const roofZ = (x, y) => {
    let d = Infinity;
    for (const [a, b] of eaveEdges) d = Math.min(d, segDist(x, y, a, b));
    return Math.min(ridgeZ, baseZ + d * tanP);
  };

  const wallCol = srgb(spec.wallHex || WALL_COLOURS[Math.floor(rnd() * WALL_COLOURS.length)]);
  const trimCol = srgb(spec.trimHex || (rnd() < 0.7 ? '#e9e6de' : '#3b3a38'));
  const roofCol = srgb(spec.roofHex || '#8f8e88');
  const seed = rnd();

  // ------------------------------------------------ walls (subdivided so the top follows the roof at gable ends)
  let perim = 0;
  const W = B.wall;
  for (let i = 0; i < n; i++) {
    const a = fp[i], b = fp[(i + 1) % n];
    const len = Math.hypot(b[0] - a[0], b[1] - a[1]);
    const [nx, ny] = edgeNormal(a, b);
    const doorU = spec.doorEdge === i ? spec.doorU ?? len / 2 : -1;
    const garU = spec.garageEdge === i ? len / 2 : -1;
    const k = Math.max(1, Math.ceil(len / 0.8));
    for (let s = 0; s < k; s++) {
      const t0 = s / k, t1 = (s + 1) / k;
      const x0 = a[0] + (b[0] - a[0]) * t0, y0 = a[1] + (b[1] - a[1]) * t0;
      const x1 = a[0] + (b[0] - a[0]) * t1, y1 = a[1] + (b[1] - a[1]) * t1;
      // roof height just inside the wall line (gable ends rise; hips stay at the eave)
      const z0 = Math.max(eaveZ, roofZ(x0 - nx * 0.02, y0 - ny * 0.02) - 0.12), z1 = Math.max(eaveZ, roofZ(x1 - nx * 0.02, y1 - ny * 0.02) - 0.12);
      const zb = gMin - 0.6;
      const quad = [[x0, y0, zb, t0 * len], [x1, y1, zb, t1 * len], [x1, y1, z1, t1 * len], [x0, y0, z0, t0 * len]];
      for (const id of [0, 1, 2, 0, 2, 3]) {
        const [x, y, z, u] = quad[id];
        W.pos.push(x, z, -y); W.nrm.push(nx, 0, -ny); W.uv.push(u, z - floorZ);
        W.col.push(...wallCol); W.seg.push(len, spec.floors ?? 1, doorU, garU); W.aux.push(seed + i * 0.137, spec.garageW || 4.9, 0);
      }
    }
    perim += len;
  }
  // fascia (vertical band along the roof edge) + soffit (underside between wall top and fascia), trim colour
  for (let i = 0; i < n; i++) {
    const a = fp[i], b = fp[(i + 1) % n], ra = roofPoly[i], rb = roofPoly[(i + 1) % n];
    const len = Math.hypot(rb[0] - ra[0], rb[1] - ra[1]);
    const [nx, ny] = edgeNormal(ra, rb);
    const k = Math.max(1, Math.ceil(len / 0.8));
    for (let s = 0; s < k; s++) {
      const t0 = s / k, t1 = (s + 1) / k;
      const P = (p, q, t) => [p[0] + (q[0] - p[0]) * t, p[1] + (q[1] - p[1]) * t];
      const o0 = P(ra, rb, t0), o1 = P(ra, rb, t1), w0 = P(a, b, t0), w1 = P(a, b, t1);
      const zt0 = roofZ(o0[0], o0[1]), zt1 = roofZ(o1[0], o1[1]);
      const fz0 = zt0 - 0.2, fz1 = zt1 - 0.2;
      const wz0 = Math.max(eaveZ, roofZ(w0[0] - nx * 0.02, w0[1] - ny * 0.02) - 0.12), wz1 = Math.max(eaveZ, roofZ(w1[0] - nx * 0.02, w1[1] - ny * 0.02) - 0.12);
      const push = (verts, nn) => {
        for (const id of [0, 1, 2, 0, 2, 3]) {
          const [x, y, z] = verts[id];
          W.pos.push(x, z, -y); W.nrm.push(nn[0], nn[1], nn[2]); W.uv.push(0, 0); W.col.push(...trimCol); W.seg.push(0, -1, -1, -1); W.aux.push(0, 0, 0);
        }
      };
      push([[o0[0], o0[1], fz0], [o1[0], o1[1], fz1], [o1[0], o1[1], zt1 + 0.03], [o0[0], o0[1], zt0 + 0.03]], [nx, 0, -ny]);
      push([[w0[0], w0[1], wz0], [w1[0], w1[1], wz1], [o1[0], o1[1], fz1], [o0[0], o0[1], fz0]], [0, -1, 0]);
    }
  }

  // ------------------------------------------------ roof height field on a grid aligned with the longest edge
  let li = 0, ll = 0;
  for (let i = 0; i < n; i++) { const a = fp[i], b = fp[(i + 1) % n], l = Math.hypot(b[0] - a[0], b[1] - a[1]); if (l > ll) { ll = l; li = i; } }
  const ea = fp[li], eb = fp[(li + 1) % n];
  const ax = [(eb[0] - ea[0]) / ll, (eb[1] - ea[1]) / ll], ay = [-ax[1], ax[0]];
  let umin = Infinity, umax = -Infinity, vmin = Infinity, vmax = -Infinity;
  for (const p of roofPoly) { const u = p[0] * ax[0] + p[1] * ax[1], v = p[0] * ay[0] + p[1] * ay[1]; umin = Math.min(umin, u); umax = Math.max(umax, u); vmin = Math.min(vmin, v); vmax = Math.max(vmax, v); }
  const step = spec.coarse ? 0.9 : 0.4;
  const nu = Math.ceil((umax - umin) / step) + 1, nv = Math.ceil((vmax - vmin) / step) + 1;
  const gx = new Float32Array(nu * nv), gy = new Float32Array(nu * nv), inside = new Uint8Array(nu * nv);
  for (let j = 0; j < nv; j++) for (let i = 0; i < nu; i++) {
    const u = umin + i * step, v = vmin + j * step, k = j * nu + i;
    gx[k] = u * ax[0] + v * ay[0]; gy[k] = u * ax[1] + v * ay[1];
    inside[k] = inPoly(gx[k], gy[k], roofPoly) ? 1 : 0;
  }
  const R = B.roof;
  const vtx = new Map();
  const vid = (k) => {
    if (vtx.has(k)) return vtx.get(k);
    let x = gx[k], y = gy[k];
    if (!inside[k]) [x, y] = nearestOnPoly(x, y, roofPoly);
    const z = roofZ(x, y);
    const e = 0.06;
    const dzx = (roofZ(x + e, y) - roofZ(x - e, y)) / (2 * e), dzy = (roofZ(x, y + e) - roofZ(x, y - e)) / (2 * e);
    const nl = Math.hypot(dzx, dzy, 1);
    const id = R.pos.length / 3;
    R.pos.push(x, z + 0.03, -y); R.nrm.push(-dzx / nl, 1 / nl, dzy / nl); R.col.push(...roofCol); R.uv.push(x, y);
    vtx.set(k, id);
    return id;
  };
  for (let j = 0; j < nv - 1; j++) for (let i = 0; i < nu - 1; i++) {
    const a = j * nu + i, b = a + 1, c = a + nu, d = c + 1;
    if (!(inside[a] | inside[b] | inside[c] | inside[d])) continue;
    const A = vid(a), Bv = vid(b), C = vid(c), D = vid(d);
    R.idx.push(A, Bv, D, A, D, C);
  }
  B.colliders.push({ name: spec.name, kind: 'house', count: 0 });
  return { eaveZ, ridgeZ, gMed };
}

function newBuf() { return { wall: { pos: [], nrm: [], uv: [], col: [], seg: [], aux: [] }, roof: { pos: [], nrm: [], col: [], uv: [], idx: [] }, colliders: [] }; }

function facadeMaterial() {
  const m = new THREE.MeshStandardMaterial({ vertexColors: true, roughness: 0.8, metalness: 0 });
  m.name = 'CC_Facade';
  m.onBeforeCompile = (sh) => {
    Object.assign(sh.uniforms, facadeUniforms);
    sh.vertexShader = sh.vertexShader
      .replace('#include <common>', '#include <common>\nattribute vec4 aSeg; attribute vec3 aAux; varying vec4 vSeg; varying vec3 vAux; varying vec2 vUvF;')
      .replace('#include <uv_vertex>', '#include <uv_vertex>\nvSeg = aSeg; vAux = aAux; vUvF = uv;');
    sh.fragmentShader = sh.fragmentShader
      .replace('#include <common>', `#include <common>
varying vec4 vSeg; varying vec3 vAux; varying vec2 vUvF;
uniform float uSeason; uniform sampler2D uNoise;
float fHash(float n) { return fract(sin(n) * 43758.5453); }
`)
      .replace('#include <map_fragment>', `
float fRough = 0.82, fMetal = 0.0, glass = 0.0;
if (vSeg.y > -0.5) {
  float u = vUvF.x, v = vUvF.y, len = vSeg.x, floors = vSeg.y;
  float sd = floor(vAux.x * 97.0 + 0.5);   // quantised: interpolated constants are not bit-exact
  vec3 base = diffuseColor.rgb;
  // lap siding: 0.2 m courses, shadow line under each board
  float c = fract(v / 0.2);
  base *= 0.82 + 0.18 * smoothstep(0.0, 0.12, c);
  base *= 0.94 + 0.08 * texture2D(uNoise, vec2(u * 0.3, v * 0.05)).r;
  if (v < 0.0) base = vec3(0.23, 0.22, 0.2) * (0.85 + 0.2 * texture2D(uNoise, vec2(u, v) * 0.7).g); // concrete stem wall
  vec3 col = base;
  float trim = 0.0;
  // windows: evenly spaced per wall segment, per storey (sill 0.95 m, head 2.25 m), some skipped
  if (len > 2.4 && v > 0.0) {
    float cnt = max(1.0, floor(len / 3.4));
    float sp = len / cnt;
    float k = floor(u / sp);
    float lu = u - (k + 0.5) * sp;
    float fl = floor(v / ${STOREY.toFixed(2)});
    float lv = v - fl * ${STOREY.toFixed(2)};
    float keep = step(0.28, fHash(k * 7.13 + fl * 3.7 + sd * 1.37));
    float ww = 0.55 + 0.25 * step(0.6, fHash(k * 1.3 + sd * 0.71));
    if (fl < floors && keep > 0.5) {
      float inW = step(abs(lu), ww) * step(0.95, lv) * step(lv, 2.25);
      float inT = step(abs(lu), ww + 0.09) * step(0.86, lv) * step(lv, 2.34);
      trim = max(trim, inT - inW);
      if (inW > 0.5) {
        glass = 1.0;
        float mull = step(abs(lu), 0.025) + step(abs(lv - 1.6), 0.02);
        // dark interior seen through glass, a curtain / blind on some windows
        vec3 inside = vec3(0.03, 0.032, 0.035) + vec3(0.1, 0.09, 0.07) * step(0.55, fHash(k * 3.1 + fl + sd)) * smoothstep(2.25, 1.7, lv);
        col = mix(inside, vec3(0.9), min(mull, 1.0));
        if (mull > 0.5) glass = 0.0;
      }
    }
  }
  // garage door (sectional panels) and front door
  if (vSeg.w >= 0.0) {
    float gu = u - vSeg.w, gw = vAux.y * 0.5;
    if (abs(gu) < gw && v < 2.15) { col = vec3(0.78, 0.77, 0.74) * (0.85 + 0.15 * smoothstep(0.0, 0.05, fract(v / 0.53))); glass = 0.0; trim = 0.0; }
    else if (abs(gu) < gw + 0.12 && v < 2.27) trim = 1.0;
  }
  if (vSeg.z >= 0.0) {
    float du = u - vSeg.z;
    if (abs(du) < 0.48 && v < 2.05) { col = vec3(0.16, 0.06, 0.04) * (0.85 + 0.15 * step(0.08, abs(fract(v / 0.5) - 0.5))); glass = 0.0; trim = 0.0; if (abs(du + 0.33) < 0.035 && abs(v - 1.0) < 0.035) col = vec3(0.7, 0.6, 0.3); }
    else if (abs(du) < 0.6 && v < 2.17) trim = 1.0;
  }
  col = mix(col, vec3(0.86, 0.85, 0.81), clamp(trim, 0.0, 1.0));
  diffuseColor.rgb = col;
  fRough = mix(0.8, 0.12, glass);
}
`)
      .replace('#include <roughnessmap_fragment>', 'float roughnessFactor = fRough;')
      .replace('#include <lights_fragment_begin>', `
#include <lights_fragment_begin>
`);
  };
  m.customProgramCacheKey = () => 'cc-facade';
  return m;
}

function roofMaterial() {
  const m = new THREE.MeshStandardMaterial({ vertexColors: true, roughness: 0.9, metalness: 0 });
  m.name = 'CC_Roof';
  m.onBeforeCompile = (sh) => {
    Object.assign(sh.uniforms, facadeUniforms);
    sh.vertexShader = sh.vertexShader
      .replace('#include <common>', '#include <common>\nvarying vec2 vRuv; varying vec3 vRn;')
      .replace('#include <uv_vertex>', '#include <uv_vertex>\nvRuv = uv; vRn = normal;');
    sh.fragmentShader = sh.fragmentShader
      .replace('#include <common>', '#include <common>\nvarying vec2 vRuv; varying vec3 vRn; uniform float uSeason; uniform sampler2D uNoise;')
      .replace('#include <map_fragment>', `
{
  // composition shingles: courses ~0.14 m along the slope direction, tab joints, granule noise, weathering
  vec2 dn = normalize(vRn.xz + 1e-4);
  vec2 p = vec2(vRuv.x, vRuv.y);
  float along = dot(p, vec2(dn.x, -dn.y));
  float across = dot(p, vec2(dn.y, dn.x));
  float course = floor(along / 0.143);
  float row = fract(along / 0.143);
  float tab = fract((across + course * 0.17) / 0.33);
  float sh = (0.78 + 0.22 * smoothstep(0.0, 0.18, row)) * (0.9 + 0.1 * step(0.04, tab));
  float gr = texture2D(uNoise, p * 2.3).r, wx = texture2D(uNoise, p * 0.11).b;
  vec3 c = diffuseColor.rgb * sh * (0.85 + 0.25 * gr) * (0.85 + 0.25 * wx);
  c = mix(c, c * vec3(0.8, 0.9, 0.75), smoothstep(0.62, 0.8, texture2D(uNoise, p * 0.05).a) * 0.6); // moss streaks
  float slopeUp = vRn.y;
  float snow = uSeason * smoothstep(0.55, 0.7, slopeUp + 0.15 * (texture2D(uNoise, p * 0.4).g - 0.5));
  diffuseColor.rgb = mix(c, vec3(0.88, 0.9, 0.94) * (0.95 + 0.05 * gr), snow);
}
`);
  };
  m.customProgramCacheKey = () => 'cc-roof';
  return m;
}

// build all buildings into two merged meshes + a collider geometry; returns { group, colliders: [{geom, info}] }
export function buildHouses(data, terrain, { frontDoor = null } = {}) {
  const B = newBuf();
  const colliderList = [];
  const rnd = mulberry(3905);
  const meta = [];
  const startVert = () => ({ w: B.wall.pos.length, r: B.roof.pos.length, ri: B.roof.idx.length });
  const addCollider = (name, kind, s0) => {
    // walls (non-indexed) + roof (indexed) of this building -> one collider geometry
    const wp = B.wall.pos.slice(s0.w);
    const rp = B.roof.pos.slice(s0.r);
    const ri = B.roof.idx.slice(s0.ri).map((i) => i - s0.r / 3);
    const pos = new Float32Array(wp.length + rp.length);
    pos.set(wp, 0); pos.set(rp, wp.length);
    const idx = [];
    for (let i = 0; i < wp.length / 3; i++) idx.push(i);
    for (const i of ri) idx.push(i + wp.length / 3);
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.BufferAttribute(pos, 3));
    g.setIndex(idx);
    colliderList.push({ geom: g, info: { name, kind, walkable: false, collide: true } });
  };
  for (const h of data.houses) {
    const fp = ccw(h.fp);
    const spec = { ...h, fp, name: `House ${h.number}` };
    // garage door: the edge whose outward normal best matches the "faces <dir>" note (edges >= 4.5 m)
    const m = /fac\w*\s+(north|south|east|west|ne|nw|se|sw)\b/i.exec(h.garage || '');
    if (m) {
      const d = DIRS[m[1].toLowerCase()];
      let best = -1, bs = 0.5;
      for (let i = 0; i < fp.length; i++) {
        const a = fp[i], b = fp[(i + 1) % fp.length], l = Math.hypot(b[0] - a[0], b[1] - a[1]);
        if (l < 4.5) continue;
        const nn = edgeNormal(a, b), s = nn[0] * d[0] + nn[1] * d[1] + l * 0.01;
        if (s > bs) { bs = s; best = i; }
      }
      if (best >= 0) { spec.garageEdge = best; const a = fp[best], b = fp[(best + 1) % fp.length]; spec.garageW = Math.min(4.9, Math.hypot(b[0] - a[0], b[1] - a[1]) - 1.2); }
    }
    if (frontDoor && frontDoor.number === h.number) {
      // door on the edge closest to the given point
      let best = 0, bd = Infinity;
      for (let i = 0; i < fp.length; i++) {
        const a = fp[i], b = fp[(i + 1) % fp.length];
        if (i === spec.garageEdge) continue;
        const d = segDist(frontDoor.x, frontDoor.y, a, b);
        if (d < bd && Math.hypot(b[0] - a[0], b[1] - a[1]) > 2) { bd = d; best = i; }
      }
      spec.doorEdge = best;
      const a = fp[best], b = fp[(best + 1) % fp.length], L = Math.hypot(b[0] - a[0], b[1] - a[1]);
      const t = Math.max(0.15, Math.min(0.85, ((frontDoor.x - a[0]) * (b[0] - a[0]) + (frontDoor.y - a[1]) * (b[1] - a[1])) / (L * L)));
      spec.doorU = t * L;
    }
    const s0 = startVert();
    const info = building(spec, terrain, B, rnd);
    addCollider(spec.name, 'house', s0);
    meta.push({ number: h.number, ...info });
  }
  for (const c of data.context_buildings) {
    const fl = c.floors || 1;
    const eaveH = fl * STOREY + 0.45, area = Math.abs(polyArea(c.fp));
    const w = Math.sqrt(area) * 0.6;
    const spec = { fp: c.fp, floors: Math.ceil(fl), eaveH, ridgeH: eaveH + Math.min(w / 2, 6) * 0.5, pitchDeg: 26.6, roofForm: 'hip', roofHex: ['#7d7c78', '#8f8a80', '#6f6c69', '#9a968c', '#5d5c5b'][Math.floor(rnd() * 5)], coarse: true, name: c.type || 'Building' };
    const s0 = startVert();
    building(spec, terrain, B, rnd);
    addCollider('Context building', 'building', s0);
  }
  const W = B.wall;
  const wg = new THREE.BufferGeometry();
  wg.setAttribute('position', new THREE.Float32BufferAttribute(W.pos, 3));
  wg.setAttribute('normal', new THREE.Float32BufferAttribute(W.nrm, 3));
  wg.setAttribute('uv', new THREE.Float32BufferAttribute(W.uv, 2));
  wg.setAttribute('color', new THREE.Float32BufferAttribute(W.col, 3));
  wg.setAttribute('aSeg', new THREE.Float32BufferAttribute(W.seg, 4));
  wg.setAttribute('aAux', new THREE.Float32BufferAttribute(W.aux, 3));
  const R = B.roof;
  const rg = new THREE.BufferGeometry();
  rg.setAttribute('position', new THREE.Float32BufferAttribute(R.pos, 3));
  rg.setAttribute('normal', new THREE.Float32BufferAttribute(R.nrm, 3));
  rg.setAttribute('uv', new THREE.Float32BufferAttribute(R.uv, 2));
  rg.setAttribute('color', new THREE.Float32BufferAttribute(R.col, 3));
  rg.setIndex(R.idx);
  const group = new THREE.Group(); group.name = 'Houses';
  const walls = new THREE.Mesh(wg, facadeMaterial()); walls.name = 'HouseWalls';
  const roofs = new THREE.Mesh(rg, roofMaterial()); roofs.name = 'HouseRoofs';
  for (const o of [walls, roofs]) { o.castShadow = o.receiveShadow = true; group.add(o); }
  return { group, colliders: colliderList, meta };
}
