#!/usr/bin/env node
// Build step for the Canby Court web experience.
//
//   cd canby-court/web && npm install && node build.mjs
//
// 1. Terrain: data/processed/terrain/heightmap_u16.png (0.5 m DTM) -> dist/terrain.u16.b64.txt (raw little-endian
//    uint16, base64 text because the artifact host serves .txt but no binary types).
// 2. Surface classes: data/processed/groundcover/classes_0p3m.tif -> assets/surface.png (RGB weights:
//    R asphalt, G concrete, B lawn, remainder = planting beds / soil), used by the placeholder ground shader.
// 3. World data: houses, context buildings, trees, hedges, road, sled run + kickers -> assets/world_data.json
//    (placeholder world, minimap, places, sled game).
// 4. GLBs (when present): assets/world_summer.glb, world_winter.glb, character.glb, sled.glb ->
//    dedup + prune + meshopt (+ webp textures <= 2048) -> dist/*.glb.b64.txt. Writes dist/manifest.json.
// 5. artifact.html = index.html without the html/head/body wrapper (the artifact host adds it).
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import sharp from 'sharp';
import { NodeIO } from '@gltf-transform/core';
import { ALL_EXTENSIONS } from '@gltf-transform/extensions';
import { dedup, prune, meshopt, textureCompress } from '@gltf-transform/functions';
import { MeshoptEncoder, MeshoptDecoder } from 'meshoptimizer';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.dirname(HERE);                       // canby-court/
const ASSETS = path.join(HERE, 'assets');
const DIST = path.join(HERE, 'dist');
const PROC = path.join(ROOT, 'data', 'processed');
const GAME = path.join(ROOT, 'data', 'game');
const MAX_FILE = 15 * 1024 * 1024;
const mb = (n) => (n / 1048576).toFixed(2) + ' MB';
const r2 = (v) => Math.round(v * 100) / 100;
const readJSON = (p) => JSON.parse(fs.readFileSync(p, 'utf8'));

fs.mkdirSync(DIST, { recursive: true });
fs.mkdirSync(ASSETS, { recursive: true });
const manifest = { generated: new Date().toISOString(), worlds: {}, character: null, sled: null };

// ---------------------------------------------------------------- 1. terrain
const TJ = readJSON(path.join(PROC, 'terrain.json')).dtm;
{
  const hmPath = path.join(ROOT, TJ.heightmap_png.file);
  // grey16 keeps the full 16-bit range (the default pipeline converts to 8-bit sRGB first)
  const { data, info } = await sharp(hmPath).toColourspace('grey16').raw({ depth: 'ushort' }).toBuffer({ resolveWithObject: true });
  const src = new Uint16Array(data.buffer, data.byteOffset, data.length / 2);
  const n = info.width * info.height;
  const out = Buffer.alloc(n * 2);
  for (let i = 0; i < n; i++) out.writeUInt16LE(src[i * info.channels], i * 2);
  fs.writeFileSync(path.join(DIST, 'terrain.u16.b64.txt'), out.toString('base64'));
  const [x0, y0, x1, y1] = TJ.bounds_local;
  manifest.terrain = {
    file: 'dist/terrain.u16.b64.txt', width: info.width, height: info.height, res: TJ.resolution_m,
    bounds: [x0, y0, x1, y1], zMin: TJ.heightmap_png.z_min, zMax: TJ.heightmap_png.z_max,
    decode: 'z = zMin + v/65535*(zMax-zMin); uint16 LE, row 0 = north edge (y1), column 0 = west edge (x0); pixel centres at x0+(c+0.5)*res',
    source: '3DEP 2006 bare earth (data/processed/terrain.json)',
  };
  console.log(`terrain ${info.width}x${info.height} -> dist/terrain.u16.b64.txt (${mb(fs.statSync(path.join(DIST, 'terrain.u16.b64.txt')).size)})`);
}

// ---------------------------------------------------------------- 2. surface classes
{
  const { data, info } = await sharp(path.join(PROC, 'groundcover', 'classes_0p3m.tif')).raw().toBuffer({ resolveWithObject: true });
  const W = info.width, H = info.height, ch = info.channels;
  const rgb = Buffer.alloc(W * H * 3);
  // R asphalt (street + dark drives), G concrete (sidewalk, concrete drives/patios), B lawn, rest planting beds / canopy / soil
  for (let i = 0; i < W * H; i++) {
    const c = data[i * ch];
    let r = 0, g = 0, b = 0;
    if (c === 2 || c === 5) r = 255;
    else if (c === 3 || c === 4) g = 255;
    else if (c === 6) b = 255;
    else if (c === 1) b = 160;           // under buildings: mostly lawn-ish (only visible at pads / eaves)
    rgb[i * 3] = r; rgb[i * 3 + 1] = g; rgb[i * 3 + 2] = b;
  }
  await sharp(rgb, { raw: { width: W, height: H, channels: 3 } }).blur(0.7).png({ compressionLevel: 9 }).toFile(path.join(ASSETS, 'surface.png'));
  const leg = readJSON(path.join(PROC, 'groundcover', 'legend.json'));
  manifest.surface = {
    file: 'assets/surface.png', width: W, height: H, res: leg.resolution_m, bounds: TJ.bounds_local,
    channels: 'R asphalt (street, dark drives), G concrete (sidewalks, drives, patios), B lawn, remainder planting beds / canopy / soil',
    source: 'data/processed/groundcover (observed classification, ~70-85 % accuracy)',
  };
  console.log(`surface ${W}x${H} -> assets/surface.png (${(fs.statSync(path.join(ASSETS, 'surface.png')).size / 1024).toFixed(0)} KB)`);
}

// ---------------------------------------------------------------- 3. world data
{
  const B = readJSON(path.join(PROC, 'boundary.json'));
  const HO = readJSON(path.join(PROC, 'houses.json'));
  const CB = readJSON(path.join(PROC, 'context_buildings.json'));
  const TR = readJSON(path.join(PROC, 'trees.json'));
  const SL = readJSON(path.join(PROC, 'sledding.json'));
  const J = readJSON(path.join(GAME, 'jumps.json'));
  const ctx = B.context.bounds_local;
  const inBox = (x, y, m = 0) => x > ctx[0] - m && x < ctx[2] + m && y > ctx[1] - m && y < ctx[3] + m;
  const ring = (pts) => pts.map(([x, y]) => [r2(x), r2(y)]);
  const val = (o) => (o && typeof o === 'object' && 'value' in o ? o.value : o);
  const houses = HO.houses.map((h) => ({
    number: h.number, address: h.address,
    fp: ring(val(h.footprint_local)),
    centroid: h.centroid_local,
    floors: h.assessor?.floors ?? 1,
    year: h.assessor?.year_built ?? null,
    ground: { min: h.ground?.z_ring_min, max: h.ground?.z_ring_max, median: h.ground?.z_ring_median },
    eaveH: val(h.roof?.eave_height_above_grade_m) ?? 5.5,
    ridgeH: val(h.roof?.ridge_height_above_grade_m) ?? 8.5,
    pitchDeg: h.roof?.pitch?.deg ?? 26.6,
    ridgeBearing: val(h.roof?.ridge_bearing_deg) ?? null,
    roofForm: val(h.roof?.form) || '',
    roofHex: h.roof?.colour?.ortho_cob2022_core?.sunlit_planes_hex || h.roof?.colour?.ortho_wc2024_core?.sunlit_planes_hex || '#9a9a96',
    garage: val(h.garage) || '',
  }));
  const context = CB.buildings
    .filter((b) => b.footprint_local.some(([x, y]) => inBox(x, y, 25)))
    .map((b) => ({ fp: ring(b.footprint_local), floors: b.floors || 1, year: b.year_built || null, type: b.bldg_type || '' }));
  const trees = TR.trees.filter((t) => inBox(t.x, t.y, 30)).map((t) => ({
    id: t.id, x: t.x, y: t.y, h: t.height_m, r: t.crown_radius_m, type: t.type, evergreen: !!t.evergreen, species: t.species_guess || '',
  }));
  const hedges = TR.hedges.map((h) => ({ id: h.id, pts: h.points, w: h.width_m || 1, h: h.height_m_est || 1.5, kind: h.kind || '' }));
  // door / garage-door positions from the scene agent (blender/scene_meta.json), when present
  const metaPath = path.join(ROOT, 'blender', 'scene_meta.json');
  if (fs.existsSync(metaPath)) {
    try {
      const SM = readJSON(metaPath);
      for (const h of houses) {
        const m = SM.houses && SM.houses[String(h.number)];
        if (!m || !m.doors) continue;
        h.doors = [...(m.doors.door || []), ...(m.doors.garage || [])].map((d) => ({ kind: d.kind, c: d.center.map(r2), n: d.normal.map((v) => +v.toFixed(3)), w: +d.width.toFixed(2), z: d.z }));
      }
      console.log('  doors from blender/scene_meta.json');
    } catch (e) { console.warn('  scene_meta.json unreadable', e.message); }
  }
  const wd = {
    note: 'Derived from canby-court/data (see README). Local metres: x east, y north, z NAVD88. three.js: (x, z, -y).',
    origin: B.origin, context: ctx, core: B.core.local.coordinates[0].map(([x, y]) => [r2(x), r2(y)]),
    road: { centerline: B.canby_ct_centerline_local.coordinates.map(([x, y]) => [r2(x), r2(y)]), poly: B.canby_ct_road_local.coordinates[0].map(([x, y]) => [r2(x), r2(y)]) },
    houses, context_buildings: context, trees, hedges,
    sled: {
      run: SL.recommended_run && { length_m: SL.recommended_run.length_m, drop_m: SL.recommended_run.drop_m, avg_gradient_pct: SL.recommended_run.avg_gradient_pct, max_gradient_pct_5m: SL.recommended_run.max_gradient_pct_5m },
      path: J.run_path_local, start: J.start, jumps: J.jumps, berm: J.runout_berm, artistic: true, note: J.note,
    },
  };
  fs.writeFileSync(path.join(ASSETS, 'world_data.json'), JSON.stringify(wd));
  console.log(`assets/world_data.json: ${houses.length} houses, ${context.length} context buildings, ${trees.length} trees, ${hedges.length} hedges, ${J.jumps.length} kickers (${(fs.statSync(path.join(ASSETS, 'world_data.json')).size / 1024).toFixed(0)} KB)`);
  manifest.worldData = 'assets/world_data.json';
}

// ---------------------------------------------------------------- 4. GLBs
await MeshoptEncoder.ready;
await MeshoptDecoder.ready;
const io = new NodeIO().registerExtensions(ALL_EXTENSIONS).registerDependencies({
  'meshopt.encoder': MeshoptEncoder, 'meshopt.decoder': MeshoptDecoder,
});

// GLB with its images kept EXTERNAL (uri relative to assets/, e.g. "tex/x.jpg"): optimise geometry only, then put
// the original URIs back into the written GLB's JSON (images are fetched by the page next to the GLB).
const TINY_PNG = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==', 'base64');
function patchGLBImages(glb, uris) {
  const dv = new DataView(glb.buffer, glb.byteOffset, glb.byteLength);
  const jsonLen = dv.getUint32(12, true);
  const json = JSON.parse(Buffer.from(glb.buffer, glb.byteOffset + 20, jsonLen).toString('utf8'));
  const rest = Buffer.from(glb.buffer, glb.byteOffset + 20 + jsonLen, glb.byteLength - 20 - jsonLen);
  (json.images || []).forEach((im, i) => { if (uris[i]) { delete im.bufferView; im.uri = uris[i]; } });
  let js = Buffer.from(JSON.stringify(json), 'utf8');
  const pad = (4 - (js.length % 4)) % 4;
  js = Buffer.concat([js, Buffer.alloc(pad, 0x20)]);
  const head = Buffer.alloc(20);
  head.writeUInt32LE(0x46546c67, 0); head.writeUInt32LE(2, 4); head.writeUInt32LE(20 + js.length + rest.length, 8);
  head.writeUInt32LE(js.length, 12); head.writeUInt32LE(0x4e4f534a, 16);
  return { glb: Buffer.concat([head, js, rest]), images: (json.images || []).map((im) => im.uri).filter(Boolean) };
}

async function optimise(srcName, { texSize = 2048, externalImages = false } = {}) {
  const src = path.join(ASSETS, srcName);
  const glb = path.join(DIST, srcName);
  const t0 = Date.now();
  const doc = await io.read(src);
  const b64 = srcName + '.b64.txt';
  const exts = doc.getRoot().listExtensionsUsed().map((e) => e.extensionName);
  if (exts.includes('EXT_meshopt_compression')) {
    // already optimised by its producer (meshopt + webp): ship the bytes unchanged (no second lossy pass)
    fs.writeFileSync(path.join(DIST, b64), fs.readFileSync(src).toString('base64'));
    const bytes = fs.statSync(path.join(DIST, b64)).size;
    const anims = doc.getRoot().listAnimations().map((a) => a.getName());
    console.log(`  ${srcName} (${mb(fs.statSync(src).size)}, already meshopt) -> dist/${b64} (${mb(bytes)})${anims.length ? ' clips: ' + anims.join(',') : ''}`);
    return { file: 'dist/' + b64, source: 'assets/' + srcName, bytes, sourceBytes: fs.statSync(src).size, passthrough: true, clips: anims.length ? anims : undefined };
  }
  const steps = [dedup(), prune({ keepLeaves: true, keepExtras: true, keepAttributes: false })];
  if (!externalImages && doc.getRoot().listTextures().length) {
    steps.push(textureCompress({ encoder: sharp, targetFormat: 'webp', resize: [texSize, texSize], quality: 88 }));
  }
  steps.push(meshopt({ encoder: MeshoptEncoder, level: 'medium', quantizePosition: 16, quantizeNormal: 10, quantizeTexcoord: 14 }));
  await doc.transform(...steps);
  let out, images = [];
  if (externalImages) {
    const uris = doc.getRoot().listTextures().map((t) => t.getURI());
    for (const t of doc.getRoot().listTextures()) t.setImage(new Uint8Array(TINY_PNG)).setMimeType('image/png');
    const r = patchGLBImages(Buffer.from(await io.writeBinary(doc)), uris);
    out = r.glb; images = r.images;
    const missing = images.filter((u) => !fs.existsSync(path.join(ASSETS, u)));
    if (missing.length) console.warn(`  WARNING: ${srcName} references missing images: ${missing.join(', ')}`);
  } else {
    out = Buffer.from(await io.writeBinary(doc));
  }
  fs.writeFileSync(path.join(DIST, b64), out.toString('base64'));
  const bytes = fs.statSync(path.join(DIST, b64)).size;
  const anims = doc.getRoot().listAnimations().map((a) => a.getName());
  console.log(`  ${srcName} (${mb(fs.statSync(src).size)}) -> dist/${b64} (${mb(bytes)}, ${images.length} external images) in ${((Date.now() - t0) / 1000).toFixed(1)} s${anims.length ? ' clips: ' + anims.join(',') : ''}`);
  if (bytes > MAX_FILE) console.warn(`  WARNING: dist/${b64} exceeds the 15 MB per-file hosting limit`);
  void glb;
  return { file: 'dist/' + b64, source: 'assets/' + srcName, bytes, sourceBytes: fs.statSync(src).size, clips: anims.length ? anims : undefined, resourcePath: externalImages ? 'assets/' : undefined, images: images.length ? images.map((u) => 'assets/' + u) : undefined };
}

for (const f of fs.readdirSync(DIST)) if (/\.glb(\.b64\.txt)?$/.test(f)) fs.rmSync(path.join(DIST, f));
console.log('GLBs');
for (const season of ['summer', 'winter']) {
  const f = `world_${season}.glb`;
  if (fs.existsSync(path.join(ASSETS, f))) manifest.worlds[season] = await optimise(f, { externalImages: true });
  else console.log(`  assets/${f} not present: procedural placeholder world (from data/processed) for ${season}`);
}
if (fs.existsSync(path.join(ASSETS, 'character.glb'))) manifest.character = await optimise('character.glb', { texSize: 1024 });
else console.log('  assets/character.glb not present: placeholder figure');
if (fs.existsSync(path.join(ASSETS, 'sled.glb'))) manifest.sled = await optimise('sled.glb', { texSize: 512 });
else console.log('  assets/sled.glb not present: sled from character.glb (node "Sled") or a placeholder sled');

// ground texture sets from the scene agent's library (assets/tex/library.json) for the placeholder ground shader
{
  const libPath = path.join(ASSETS, 'tex', 'library.json');
  const want = { lawn: 'lawn_grass', asphalt: 'asphalt_street', concrete: 'concrete_drive', bed: 'bark_mulch', snow: 'snow_fresh', snowPacked: 'snow_packed', roof: 'roof_arch_shingle', siding: 'siding_lap_fibercement' };
  if (fs.existsSync(libPath)) {
    const lib = readJSON(libPath).sets || {};
    const out = {};
    for (const [k, name] of Object.entries(want)) {
      const set = lib[name];
      if (!set || !set.files || !set.files.albedo || !set.files.normal) continue;
      if (!fs.existsSync(path.join(ASSETS, 'tex', set.files.albedo)) || !fs.existsSync(path.join(ASSETS, 'tex', set.files.normal))) continue;
      out[k] = { albedo: 'assets/tex/' + set.files.albedo, normal: 'assets/tex/' + set.files.normal, size: set.size_m[0] };
    }
    if (Object.keys(out).length === Object.keys(want).length) { manifest.groundTex = out; console.log('ground textures: ' + Object.values(want).join(', ')); }
  }
}
// leaf-card atlas (scene agent) for the placeholder trees
if (manifest.groundTex && fs.existsSync(path.join(ASSETS, 'tex', 'foliage_atlas.json')) && fs.existsSync(path.join(ASSETS, 'tex', 'foliage_atlas_albedo.png'))) {
  manifest.foliage = { json: 'assets/tex/foliage_atlas.json', albedo: 'assets/tex/foliage_atlas_albedo.png' };
  console.log('foliage atlas: assets/tex/foliage_atlas_albedo.png');
}
// optional: scene contract notes (kicker names etc.)
const sceneDoc = path.join(ROOT, 'docs', 'scene.md');
manifest.sceneDoc = fs.existsSync(sceneDoc) ? 'canby-court/docs/scene.md (present at build time)' : null;
fs.writeFileSync(path.join(DIST, 'manifest.json'), JSON.stringify(manifest, null, 2));
console.log('dist/manifest.json written');

// ---------------------------------------------------------------- 5. artifact.html
{
  const WRAP = /^\s*(<!doctype html>|<html\b[^>]*>|<\/html>|<head>|<\/head>|<body>|<\/body>|<meta charset="utf-8">)\s*$/i;
  const src = fs.readFileSync(path.join(HERE, 'index.html'), 'utf8');
  fs.writeFileSync(path.join(HERE, 'artifact.html'), src.split('\n').filter((l) => !WRAP.test(l)).join('\n'));
  console.log('artifact.html regenerated from index.html');
}

// ---------------------------------------------------------------- publish list
{
  const list = ['index.html', 'artifact.html', 'style.css', ...fs.readdirSync(path.join(HERE, 'src')).filter((f) => f.endsWith('.js')).map((f) => 'src/' + f),
    'dist/manifest.json', manifest.terrain.file, 'assets/surface.png', 'assets/world_data.json'];
  for (const k of ['summer', 'winter']) if (manifest.worlds[k]) list.push(manifest.worlds[k].file);
  const imgs = new Set();
  for (const k of ['summer', 'winter']) for (const u of (manifest.worlds[k] && manifest.worlds[k].images) || []) imgs.add(u);
  list.push(...[...imgs].filter((u) => !list.includes(u)).sort());
  const placeholderUsed = !(manifest.worlds.summer && manifest.worlds.winter);
  if (manifest.groundTex && placeholderUsed) for (const t of Object.values(manifest.groundTex)) list.push(t.albedo, t.normal);
  if (manifest.foliage && placeholderUsed) list.push(manifest.foliage.json, manifest.foliage.albedo);
  if (manifest.character) list.push(manifest.character.file);
  if (manifest.sled) list.push(manifest.sled.file);
  let total = 0;
  const rows = list.map((f) => { const s = fs.existsSync(path.join(HERE, f)) ? fs.statSync(path.join(HERE, f)).size : 0; total += f === 'artifact.html' ? 0 : s; return `${f}\t${(s / 1024).toFixed(0)} KB`; });
  fs.writeFileSync(path.join(DIST, 'publish.txt'), rows.join('\n') + `\nTOTAL (index.html variant)\t${mb(total)}\n`);
  console.log(`publish list -> dist/publish.txt (${list.length} files, ${mb(total)})`);
}
