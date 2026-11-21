#!/usr/bin/env node
// Build step for the Higashiyama Walk web explorer.
//
//   cd web && npm install && node build.mjs
//
// 1. Picks the world GLB: assets/world_art.glb (art pass) if present, else assets/world.glb (blockout).
// 2. Picks assets/pagoda.glb (hero pagoda, world coordinates) if present.
// 3. Normalises vertex colours (keeps the informative COLOR_n set as COLOR_0, repairs the blockout's
//    double sRGB->linear conversion of "plateau_rgb"), then dedup + prune (extras kept) + meshopt
//    (reorder + quantize + EXT_meshopt_compression) into dist/.
// 4. Writes dist/manifest.json (what the page loads) and derives assets/minimap.json from
//    data/processed/{buildings,streets,features}.json; copies data/processed/surface_mask.png to assets/.
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { NodeIO } from '@gltf-transform/core';
import { ALL_EXTENSIONS } from '@gltf-transform/extensions';
import { dedup, prune, meshopt, joinPrimitives } from '@gltf-transform/functions';
import { MeshoptEncoder, MeshoptDecoder } from 'meshoptimizer';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.dirname(HERE);
const ASSETS = path.join(HERE, 'assets');
const DIST = path.join(HERE, 'dist');
const PROC = path.join(ROOT, 'data', 'processed');
const MAX_BIN = 15 * 1024 * 1024;

fs.mkdirSync(DIST, { recursive: true });
await MeshoptEncoder.ready;
await MeshoptDecoder.ready;
const io = new NodeIO().registerExtensions(ALL_EXTENSIONS).registerDependencies({
  'meshopt.encoder': MeshoptEncoder,
  'meshopt.decoder': MeshoptDecoder,
});

const mb = (n) => (n / 1048576).toFixed(2) + ' MB';

// ---------------------------------------------------------------- vertex colours
function colourStats(acc) {
  const n = acc.getCount();
  const el = [];
  let sum = 0, sumSq = 0, cnt = 0;
  const step = Math.max(1, Math.floor(n / 64));
  for (let i = 0; i < n; i += step) {
    acc.getElement(i, el);
    const l = (el[0] + el[1] + el[2]) / 3;
    sum += l; sumSq += l * l; cnt++;
  }
  const mean = sum / cnt;
  return { mean, var: sumSq / cnt - mean * mean };
}

function normaliseColours(doc) {
  const root = doc.getRoot();
  let renamed = 0, fixed = 0;
  // pass 1: choose the informative colour set per primitive and gather statistics on building walls/roofs
  const chosen = [];
  for (const mesh of root.listMeshes()) {
    for (const prim of mesh.listPrimitives()) {
      const sets = prim.listSemantics().filter((s) => /^COLOR_\d+$/.test(s));
      if (!sets.length) continue;
      let best = sets[0], bestScore = -1;
      for (const s of sets) {
        const st = colourStats(prim.getAttribute(s));
        // a constant-white set (Blender's default "Color" layer) carries no information
        const score = st.var + (Math.abs(st.mean - 1) > 1e-3 ? 1e-6 : 0);
        if (score > bestScore) { best = s; bestScore = score; }
      }
      if (best !== 'COLOR_0') {
        const acc = prim.getAttribute(best);
        for (const s of sets) prim.setAttribute(s, null);
        prim.setAttribute('COLOR_0', acc);
        renamed++;
      } else {
        for (const s of sets) if (s !== 'COLOR_0') prim.setAttribute(s, null);
      }
      chosen.push(prim);
    }
  }
  // pass 2: detect the double-linearised blockout colours (mean linear luminance of PLATEAU facades
  // implausibly dark, < 0.03) and re-encode once (linear->sRGB transfer) so the stored linear values are right.
  const means = [];
  for (const prim of chosen) {
    const mat = prim.getMaterial();
    if (!mat || !/roof|wall/i.test(mat.getName())) continue;
    means.push(colourStats(prim.getAttribute('COLOR_0')).mean);
  }
  means.sort((a, b) => a - b);
  const n = means.length;
  const meanLum = n ? means[n >> 1] : 1;
  const needFix = n > 0 && meanLum < 0.03;
  if (needFix) {
    const enc = (c) => (c <= 0.0031308 ? c * 12.92 : 1.055 * Math.pow(c, 1 / 2.4) - 0.055);
    const seen = new Set();
    for (const prim of chosen) {
      const acc = prim.getAttribute('COLOR_0');
      if (seen.has(acc)) continue;
      seen.add(acc);
      const src = acc.getArray();
      const comps = acc.getElementSize();
      const out = new Float32Array(acc.getCount() * comps);
      const el = [];
      for (let i = 0; i < acc.getCount(); i++) {
        acc.getElement(i, el);
        for (let k = 0; k < comps; k++) out[i * comps + k] = k < 3 ? enc(el[k]) : el[k];
      }
      void src;
      acc.setArray(out).setNormalized(false);
      fixed++;
    }
  }
  return { renamed, fixed, medianLinearLuminanceBefore: +meanLum.toFixed(5), reencoded: needFix };
}

// ---------------------------------------------------------------- join small static meshes by section
// 1,268 PLATEAU buildings x 3 material slots would mean ~3,800 primitives (and ~5 MB of accessor JSON).
// Buildings (B_*) and barriers (Barrier_*) are joined per 100 m section and material; every source object's
// name + extras (plateau_id, osm_id, height ...) are kept in the joined node's extras.members, and the
// per-vertex _MEMBER attribute (index into members) keeps every triangle traceable to its source object.
function joinBySection(doc) {
  const root = doc.getRoot();
  const scene = root.getDefaultScene() || root.listScenes()[0];
  const groups = new Map(); // nodeKey -> { members, byMat: Map(matKey -> prims) }
  let joinedNodes = 0;
  const IDENT = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1];
  for (const node of root.listNodes()) {
    const nm = node.getName();
    const kind = /^B_/.test(nm) ? 'Buildings' : /^Barrier_/.test(nm) ? 'Barriers' : null;
    const mesh = node.getMesh();
    if (!kind || !mesh || node.listChildren().length) continue;
    const wm = node.getWorldMatrix();
    if (wm.some((v, i) => Math.abs(v - IDENT[i]) > 1e-9)) continue; // only identity-transformed objects
    let mn = [Infinity, Infinity, Infinity], mx = [-Infinity, -Infinity, -Infinity];
    for (const prim of mesh.listPrimitives()) {
      const a = prim.getAttribute('POSITION');
      const lo = a.getMin([]), hi = a.getMax([]);
      for (let k = 0; k < 3; k++) { mn[k] = Math.min(mn[k], lo[k]); mx[k] = Math.max(mx[k], hi[k]); }
    }
    const cx = (mn[0] + mx[0]) / 2, cz = (mn[2] + mx[2]) / 2;
    const sx = Math.max(0, Math.min(5, Math.floor((cx + 300) / 100)));
    const sz = Math.max(0, Math.min(5, Math.floor((cz + 300) / 100)));
    const key = `${kind}_s${sx}${sz}`;
    if (!groups.has(key)) groups.set(key, { kind, members: [], byMat: new Map() });
    const g = groups.get(key);
    const mi = g.members.length;
    g.members.push({ name: nm, ...node.getExtras() });
    for (const prim of mesh.listPrimitives()) {
      const pos = prim.getAttribute('POSITION');
      const n = pos.getCount();
      const ids = new Uint16Array(n).fill(mi);
      prim.setAttribute('_MEMBER', doc.createAccessor().setType('SCALAR').setArray(ids).setBuffer(pos.getBuffer()));
      const sig = prim.listSemantics().sort().join(',') + '|' + (prim.getIndices() ? prim.getIndices().getComponentType() : 'n');
      const mk = (prim.getMaterial() ? prim.getMaterial().getName() : '') + '|' + sig;
      if (!g.byMat.has(mk)) g.byMat.set(mk, []);
      g.byMat.get(mk).push(prim);
    }
    node.dispose();
    joinedNodes++;
  }
  for (const [key, g] of groups) {
    const mesh = doc.createMesh(key);
    for (const prims of g.byMat.values()) {
      let out;
      if (prims.length === 1) out = prims[0];
      else { out = joinPrimitives(prims); out.setMaterial(prims[0].getMaterial()); }
      mesh.addPrimitive(out);
    }
    const node = doc.createNode(key).setMesh(mesh).setExtras({
      joined: true, kind: g.kind, collide: true, members: g.members,
    });
    scene.addChild(node);
  }
  return { joinedNodes, joinedGroups: groups.size };
}

async function optimise(srcName, dstName, { colours }) {
  const src = path.join(ASSETS, srcName);
  const dst = path.join(DIST, dstName);
  const t0 = Date.now();
  const doc = await io.read(src);
  const info = colours ? normaliseColours(doc) : null;
  const joinInfo = colours ? joinBySection(doc) : null;
  await doc.transform(
    dedup(),
    prune({ keepLeaves: true, keepExtras: true, keepAttributes: false }),
    meshopt({ encoder: MeshoptEncoder, level: 'high', quantizePosition: 16, quantizeNormal: 8, quantizeColor: 8 }),
  );
  await io.write(dst, doc);
  const bytes = fs.statSync(dst).size;
  console.log(`  ${srcName} (${mb(fs.statSync(src).size)}) -> dist/${dstName} (${mb(bytes)}) in ${((Date.now() - t0) / 1000).toFixed(1)} s`);
  if (bytes > MAX_BIN) console.warn(`  WARNING: dist/${dstName} exceeds the 15 MB per-file hosting limit`);
  return { file: dstName, source: 'assets/' + srcName, bytes, sourceBytes: fs.statSync(src).size, colours: info, join: joinInfo };
}

// ---------------------------------------------------------------- GLBs
const manifest = { generated: new Date().toISOString(), world: null, pagoda: null };
const worldSrc = fs.existsSync(path.join(ASSETS, 'world_art.glb')) ? 'world_art.glb' : 'world.glb';
if (!fs.existsSync(path.join(ASSETS, worldSrc))) {
  console.error('no assets/world.glb or assets/world_art.glb');
  process.exit(1);
}
console.log('GLB optimisation');
// remove stale outputs from a previous build that picked another source
for (const f of ['world.glb', 'world_art.glb', 'pagoda.glb', 'backdrop.glb', 'world.glb.b64.txt', 'world_art.glb.b64.txt', 'pagoda.glb.b64.txt', 'backdrop.glb.b64.txt']) {
  const p = path.join(DIST, f);
  if (fs.existsSync(p)) fs.rmSync(p);
}
manifest.world = await optimise(worldSrc, worldSrc, { colours: true });
manifest.world.kind = worldSrc === 'world_art.glb' ? 'art' : 'blockout';
if (fs.existsSync(path.join(ASSETS, 'pagoda.glb'))) {
  manifest.pagoda = await optimise('pagoda.glb', 'pagoda.glb', { colours: false });
  manifest.pagoda.hides = 'LM_Yasaka_Pagoda_PLATEAU_LOD2';
} else {
  console.log('  assets/pagoda.glb not present: PLATEAU LOD2 pagoda is shown');
}
if (fs.existsSync(path.join(ASSETS, 'backdrop.glb'))) {
  manifest.backdrop = await optimise('backdrop.glb', 'backdrop.glb', { colours: false });
  manifest.backdrop.note = 'distant Kyoto massing + Higashiyama hills: render only, no collision';
} else {
  console.log('  assets/backdrop.glb not present: sky-painted hills only');
}

// ---------------------------------------------------------------- minimap.json
function dp(pts, tol) {
  if (pts.length < 3) return pts;
  const keep = new Uint8Array(pts.length);
  keep[0] = keep[pts.length - 1] = 1;
  const stack = [[0, pts.length - 1]];
  while (stack.length) {
    const [a, b] = stack.pop();
    const [ax, ay] = pts[a], [bx, by] = pts[b];
    const dx = bx - ax, dy = by - ay, L = Math.hypot(dx, dy) || 1e-9;
    let md = -1, mi = -1;
    for (let i = a + 1; i < b; i++) {
      const d = Math.abs((pts[i][0] - ax) * dy - (pts[i][1] - ay) * dx) / L;
      if (d > md) { md = d; mi = i; }
    }
    if (md > tol) { keep[mi] = 1; stack.push([a, mi], [mi, b]); }
  }
  return pts.filter((_, i) => keep[i]);
}
function dpRing(pts, tol) {
  // closed ring: split at the vertex farthest from the first one, simplify both halves
  let fi = 0, fd = -1;
  for (let i = 1; i < pts.length; i++) {
    const d = Math.hypot(pts[i][0] - pts[0][0], pts[i][1] - pts[0][1]);
    if (d > fd) { fd = d; fi = i; }
  }
  const a = dp(pts.slice(0, fi + 1), tol), b = dp(pts.slice(fi), tol);
  return a.concat(b.slice(1));
}
const r1 = (v) => Math.round(v * 10) / 10;
const near = (x, y, m = 215) => Math.abs(x) < m && Math.abs(y) < m;

const BLD = JSON.parse(fs.readFileSync(path.join(PROC, 'buildings.json'), 'utf8'));
const STR = JSON.parse(fs.readFileSync(path.join(PROC, 'streets.json'), 'utf8'));
const FEA = JSON.parse(fs.readFileSync(path.join(PROC, 'features.json'), 'utf8'));
const mm = {
  source: 'Derived from data/processed (PLATEAU 2025 footprints, OSM streets/steps/barriers). Local metres: x east, y north.',
  boundary: [-200, -200, 200, 200],
  buildings: [],
  streets: [],
  barriers: [],
};
for (const b of BLD.buildings) {
  const [cx, cy] = b.centroid;
  if (!near(cx, cy, 225)) continue;
  const ring = dpRing(b.footprint, 0.4).map(([x, y]) => [r1(x), r1(y)]);
  if (ring.length >= 4) mm.buildings.push(ring.flat());
}
for (const s of STR.streets) {
  if (!s.coords.some(([x, y]) => near(x, y))) continue;
  mm.streets.push({
    id: s.osm_id, hw: s.highway, name: s.name || null, w: +(s.width_m || 3).toFixed(1),
    sf: s.surface || null, pts: dp(s.coords, 0.3).map(([x, y]) => [r1(x), r1(y)]).flat(),
  });
}
for (const b of FEA.barriers) {
  if (!b.coords || b.coords.length < 2 || !b.coords.some(([x, y]) => near(x, y))) continue;
  mm.barriers.push(dp(b.coords, 0.3).map(([x, y]) => [r1(x), r1(y)]).flat());
}
fs.writeFileSync(path.join(ASSETS, 'minimap.json'), JSON.stringify(mm));
console.log(`assets/minimap.json: ${mm.buildings.length} footprints, ${mm.streets.length} streets, ${mm.barriers.length} barriers, ${(fs.statSync(path.join(ASSETS, 'minimap.json')).size / 1024).toFixed(0)} KB`);

fs.copyFileSync(path.join(PROC, 'surface_mask.png'), path.join(ASSETS, 'surface_mask.png'));
console.log('assets/surface_mask.png copied');

manifest.minimap = 'assets/minimap.json';
// optional inputs from other agents: listed only when present, so the page never requests missing files
for (const p of ['assets/tex/facade_atlas.json', 'assets/facade_atlas.json']) {
  if (fs.existsSync(path.join(HERE, p))) { manifest.textures = p; break; }
}
if (fs.existsSync(path.join(ASSETS, 'renders', 'renders.json'))) manifest.renders = 'assets/renders/renders.json';
console.log(`textures: ${manifest.textures || 'procedural (no facade_atlas.json)'}; renders: ${manifest.renders || 'none'}`);
// Artifact hosting serves no .glb type: also ship each GLB as base64 text (served as .txt);
// the page decodes it (src/world.js) and still accepts plain .glb when served locally.
for (const k of ['world', 'pagoda', 'backdrop']) {
  if (!manifest[k]) continue;
  const b64Name = manifest[k].file + '.b64.txt';
  fs.writeFileSync(path.join(DIST, b64Name), fs.readFileSync(path.join(DIST, manifest[k].file)).toString('base64'));
  manifest[k].glb = manifest[k].file;
  manifest[k].file = b64Name;
}
manifest.surfaceMask = { file: 'assets/surface_mask.png', extent: [-300, 300, -300, 300], channels: 'R asphalt, G granite paving, B gravel, else soil' };
fs.writeFileSync(path.join(DIST, 'manifest.json'), JSON.stringify(manifest, null, 2));
console.log('dist/manifest.json written');

// ---------------------------------------------------------------- artifact.html
// The artifact host wraps the page in its own document skeleton: artifact.html = index.html without the
// doctype / html / head / body wrapper lines. Regenerated on every build so the two never drift apart.
{
  const WRAP = /^\s*(<!doctype html>|<html\b[^>]*>|<\/html>|<head>|<\/head>|<body>|<\/body>|<meta charset="utf-8">)\s*$/i;
  const src = fs.readFileSync(path.join(HERE, 'index.html'), 'utf8');
  const out = src.split('\n').filter((l) => !WRAP.test(l)).join('\n');
  fs.writeFileSync(path.join(HERE, 'artifact.html'), out);
  console.log('artifact.html regenerated from index.html');
}
