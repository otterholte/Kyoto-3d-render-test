// World assembly per season.
//  - GLB world (assets/world_<season>.glb from the scene agent, shipped as dist/*.glb.b64.txt): rendered with its
//    own PBR materials; colliders from node extras (collide / walkable / kind, docs/scene.md).
//  - Placeholder world (until the GLBs land, or if one fails to load): DTM terrain + houses + vegetation from
//    data/processed, sled-run features from data/game/jumps.json.
// Every world gets one MeshBVH over its colliders (position + objId -> objInfo[] for names / walkability).
import * as THREE from 'three';
import { mergeGeometries } from 'three/addons/utils/BufferGeometryUtils.js';
import { MeshBVH } from 'three-mesh-bvh';
import { loadGLB } from './util.js';
import { groundMaterial } from './terrain.js';
import { buildHouses } from './houses.js';
import { buildVegetation } from './vegetation.js';
import { buildRunFeatures } from './kickers.js';

const WALK_RE = /terrain|ground|road|street|drive|walk|path|sidewalk|snow|kicker|jump|berm|deck|step|stair|patio|lawn|porch|landing|ramp/i;

// colliders: [{geom (position, optional index; world space), info}] -> {bvh, colGeom, objInfo}
export function buildCollider(colliders) {
  const objInfo = [];
  const parts = [];
  for (const c of colliders) {
    const id = objInfo.length;
    objInfo.push(c.info);
    const src = c.geom;
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', src.attributes.position.clone());
    const n = src.attributes.position.count;
    g.setAttribute('objId', new THREE.BufferAttribute(new Float32Array(n).fill(id), 1));
    if (src.index) g.setIndex(new THREE.BufferAttribute(Uint32Array.from(src.index.array), 1));
    else g.setIndex(new THREE.BufferAttribute(Uint32Array.from({ length: n }, (_, i) => i), 1));
    parts.push(g);
  }
  const colGeom = mergeGeometries(parts, false);
  const t0 = performance.now();
  const bvh = new MeshBVH(colGeom, { maxLeafTris: 8 });
  return { bvh, colGeom, objInfo, buildMs: Math.round(performance.now() - t0), tris: colGeom.index.count / 3 };
}

// ---------------------------------------------------------------- placeholder world (both seasons share it)
export function buildPlaceholder(ctx) {
  const { data, terrain, surfTex, trackTex, lite, groundLib } = ctx;
  const root = new THREE.Group(); root.name = 'PlaceholderWorld';
  const tg = terrain.buildGeometry({ fine: lite ? 1.25 : 1.0, coarse: lite ? 4 : 3 });
  const gl = groundLib ? Object.fromEntries(Object.entries(groundLib).filter(([k]) => k !== 'roof' && k !== 'siding')) : null;
  const ground = new THREE.Mesh(tg, groundMaterial(terrain, surfTex, trackTex, { lite, lib: gl }));
  ground.name = 'Terrain'; ground.receiveShadow = true;
  root.add(ground);
  const houses = buildHouses(data, terrain, { frontDoor: { number: 3905, x: -7.4, y: -3.3 }, lib: groundLib && groundLib.roof && groundLib.siding ? { roof: groundLib.roof, siding: groundLib.siding } : null });
  root.add(houses.group);
  const veg = buildVegetation(data, terrain, ctx.foliage || null);
  root.add(veg.group);
  const run = buildRunFeatures(data.sled, terrain);
  root.add(run.group);
  const base = [{ geom: tg, info: { name: 'Terrain', kind: 'terrain', walkable: true, collide: true } }, ...houses.colliders, ...veg.colliders];
  const cache = {};
  const colliderFor = (season) => {
    if (!cache[season]) cache[season] = buildCollider(season === 'winter' ? base.concat(run.colliders) : base);
    return cache[season];
  };
  return {
    kind: 'placeholder', root, ground, houses, veg, run, jumps: run.meta,
    setDetail(q) { veg.setCards(q !== 'low'); },
    setSeason(season) {
      veg.setSeason(season);
      run.group.visible = season === 'winter';
    },
    colliderFor,
    shadowCasters: [houses.group, veg.group, run.group],
  };
}

// ---------------------------------------------------------------- GLB world
function extrasOf(o) {
  const e = {};
  const chain = [];
  for (let p = o; p; p = p.parent) chain.unshift(p);
  for (const p of chain) Object.assign(e, p.userData || {});
  return e;
}

// trunk prism / oriented box colliders (cheap stand-ins for leafy or very dense meshes)
function prism(x, y, z, r, h, n = 8) {
  const pos = [], idx = [];
  for (let k = 0; k < n; k++) { const a = k / n * Math.PI * 2; pos.push(x + Math.cos(a) * r, y, z + Math.sin(a) * r, x + Math.cos(a) * r, y + h, z + Math.sin(a) * r); }
  for (let k = 0; k < n; k++) { const a = k * 2, c = ((k + 1) % n) * 2; idx.push(a, c, a + 1, c, c + 1, a + 1); }
  const g = new THREE.BufferGeometry(); g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3)); g.setIndex(idx);
  return g;
}
function obb(mesh) {
  const g = new THREE.BoxGeometry(1, 1, 1);
  const bb = mesh.geometry.boundingBox || (mesh.geometry.computeBoundingBox(), mesh.geometry.boundingBox);
  const size = bb.getSize(new THREE.Vector3()), c = bb.getCenter(new THREE.Vector3());
  g.scale(size.x, size.y, size.z); g.translate(c.x, c.y, c.z);
  g.applyMatrix4(mesh.matrixWorld);
  return g;
}

// world-space float copy of a (possibly quantized) mesh geometry: positions + index only
function worldPositions(mesh) {
  const src = mesh.geometry, p = src.attributes.position, arr = new Float32Array(p.count * 3);
  for (let i = 0; i < p.count; i++) { arr[i * 3] = p.getX(i); arr[i * 3 + 1] = p.getY(i); arr[i * 3 + 2] = p.getZ(i); }
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.BufferAttribute(arr, 3));
  if (src.index) g.setIndex(src.index.clone());
  g.applyMatrix4(mesh.matrixWorld);
  return g;
}

export async function loadGLBWorld(entry, season, ctx, onProgress) {
  const gltf = await loadGLB(entry.file + '?v=' + encodeURIComponent(ctx.manifest.generated || ''), onProgress, entry.resourcePath || '');
  const root = gltf.scene; root.name = 'World_' + season;
  // the page lights the scene itself: drop exported lights / cameras
  const strip = [];
  root.traverse((o) => { if (o.isLight || o.isCamera) strip.push(o); });
  for (const o of strip) o.parent && o.parent.remove(o);
  root.updateMatrixWorld(true);
  const colliders = [];
  let hasKickers = false;
  const meshes = [];
  root.traverse((o) => { if (o.isMesh) meshes.push(o); });
  const trunkDone = new Set();
  for (const o of meshes) {
    const e = extrasOf(o);
    o.userData.cc = e;
    const kind = e.kind || '';
    if (/^Jump_|^Berm_/.test(o.name) || /^Jump_|^Berm_/.test(o.parent && o.parent.name) || /jump|kicker|berm/.test(kind)) hasKickers = true;
    o.castShadow = !/^(ground|terrain|curb|street_detail|house_number|snow|sport_court|patio)$/.test(kind) && !(ctx.lite && kind === 'shrub');
    o.receiveShadow = true;
    const mats = Array.isArray(o.material) ? o.material : [o.material];
    for (const m of mats) {
      for (const k of ['map', 'normalMap', 'roughnessMap', 'metalnessMap', 'aoMap']) if (m[k]) m[k].anisotropy = ctx.lite ? 2 : 8;
      if (m.transparent && m.map && m.alphaTest === 0) { m.alphaTest = 0.4; m.transparent = false; }
    }
    // colliders: walkable surfaces as meshes; trees by their trunk; hedges / shrub-like solids as boxes
    if (e.collide === false && !e.walkable) continue;
    if (e.collide === undefined && e.walkable === undefined) continue;
    const info = { name: o.name, kind, walkable: !!e.walkable, collide: !!e.collide, address: e.address || null };
    if (kind === 'tree') {
      const owner = o.userData.name !== undefined || !o.parent || o.parent === root ? o : o.parent;
      if (trunkDone.has(owner)) continue;
      trunkDone.add(owner);
      const p = new THREE.Vector3().setFromMatrixPosition(o.matrixWorld);
      colliders.push({ geom: prism(p.x, p.y - 0.3, p.z, e.collide_radius || 0.25, 3.2), info });
    } else if (kind === 'hedge' && !e.walkable) {
      colliders.push({ geom: obb(o), info });
    } else {
      colliders.push({ geom: worldPositions(o), info });
    }
  }
  // instance meshes reused >= 4 times (trees, shrubs, hedges ...): one draw call per (geometry, material)
  const groups = new Map();
  for (const o of meshes) {
    if (o.isSkinnedMesh || o.isInstancedMesh || Array.isArray(o.material)) continue;
    const key = o.geometry.uuid + '|' + o.material.uuid;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(o);
  }
  let instanced = 0;
  for (const list of groups.values()) {
    if (list.length < 4) continue;
    const a = list[0];
    // phones: drop shrub instances far outside the Canby Ct core (they are a few pixels there)
    const keep = ctx.lite && a.userData.cc.kind === 'shrub'
      ? list.filter((o) => { const p = new THREE.Vector3().setFromMatrixPosition(o.matrixWorld); return Math.hypot(p.x + 40, p.z - 25) < 85; })
      : list;
    const im = new THREE.InstancedMesh(a.geometry, a.material, Math.max(1, keep.length));
    keep.forEach((o, i) => im.setMatrixAt(i, o.matrixWorld));
    im.count = keep.length;
    im.castShadow = a.castShadow; im.receiveShadow = true; im.name = 'Inst_' + (a.userData.cc.kind || a.name);
    im.userData = { cc: a.userData.cc };
    im.computeBoundingSphere();
    root.add(im);
    for (const o of list) o.parent.remove(o);
    instanced += list.length;
  }
  let run = null;
  if (season === 'winter' && !hasKickers) {
    run = buildRunFeatures(ctx.data.sled, ctx.terrain);
    root.add(run.group);
    colliders.push(...run.colliders);
  }
  const col = buildCollider(colliders);
  col.instanced = instanced;
  return {
    kind: 'glb', root, hasKickers, run, instanced,
    setSeason() {}, setDetail() {}, colliderFor: () => col,
    extras: root.userData || {},
  };
}
