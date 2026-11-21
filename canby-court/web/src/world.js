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
  const { data, terrain, surfTex, trackTex, lite } = ctx;
  const root = new THREE.Group(); root.name = 'PlaceholderWorld';
  const tg = terrain.buildGeometry({ fine: lite ? 1.25 : 1.0, coarse: lite ? 4 : 3 });
  const ground = new THREE.Mesh(tg, groundMaterial(terrain, surfTex, trackTex, { lite }));
  ground.name = 'Terrain'; ground.receiveShadow = true;
  root.add(ground);
  const houses = buildHouses(data, terrain, { frontDoor: { number: 3905, x: -4.6, y: -9.6 } });
  root.add(houses.group);
  const veg = buildVegetation(data, terrain);
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

export async function loadGLBWorld(entry, season, ctx, onProgress) {
  const gltf = await loadGLB(entry.file + '?v=' + encodeURIComponent(ctx.manifest.generated || ''), onProgress);
  const root = gltf.scene; root.name = 'World_' + season;
  root.updateMatrixWorld(true);
  const colliders = [];
  let hasKickers = false;
  const tmp = new THREE.Matrix4();
  root.traverse((o) => {
    const e = extrasOf(o);
    if (/kicker|jump_\d|berm/i.test(o.name) || /kicker|berm/i.test(e.kind || '')) hasKickers = true;
    if (!o.isMesh) return;
    o.castShadow = e.cast_shadow !== false && !/terrain|ground/i.test(e.kind || o.name);
    o.receiveShadow = true;
    // materials: physically based as authored; make sure textures use anisotropy
    const mats = Array.isArray(o.material) ? o.material : [o.material];
    for (const m of mats) {
      for (const k of ['map', 'normalMap', 'roughnessMap', 'metalnessMap', 'aoMap']) if (m[k]) m[k].anisotropy = ctx.lite ? 2 : 8;
      if (m.transparent && m.alphaTest === 0 && m.map) { m.alphaTest = 0.4; m.transparent = false; }
    }
    if (e.collide === false && !e.walkable) return;
    if (e.collide === undefined && e.walkable === undefined && /leaf|foliage|grass|flower|snowflake|decal|glass/i.test(o.name + ' ' + (e.kind || ''))) return;
    const walkable = e.walkable !== undefined ? !!e.walkable : WALK_RE.test(o.name + ' ' + (e.kind || ''));
    const info = { name: o.name, kind: e.kind || '', walkable, collide: true, address: e.address || null };
    const src = o.geometry;
    if (o.isInstancedMesh) {
      const n = Math.min(o.count, 4000);
      for (let i = 0; i < n; i++) {
        o.getMatrixAt(i, tmp);
        const g = new THREE.BufferGeometry();
        g.setAttribute('position', src.attributes.position.clone());
        if (src.index) g.setIndex(src.index.clone());
        g.applyMatrix4(tmp.premultiply(o.matrixWorld));
        colliders.push({ geom: g, info });
      }
    } else if (o.isSkinnedMesh) {
      // skinned props: rest pose
      const g = new THREE.BufferGeometry(); g.setAttribute('position', src.attributes.position.clone()); if (src.index) g.setIndex(src.index.clone());
      g.applyMatrix4(o.matrixWorld); colliders.push({ geom: g, info });
    } else {
      const g = new THREE.BufferGeometry();
      // de-quantize (KHR_mesh_quantization) into float positions in world space
      const p = src.attributes.position, arr = new Float32Array(p.count * 3);
      for (let i = 0; i < p.count; i++) { arr[i * 3] = p.getX(i); arr[i * 3 + 1] = p.getY(i); arr[i * 3 + 2] = p.getZ(i); }
      g.setAttribute('position', new THREE.BufferAttribute(arr, 3));
      if (src.index) g.setIndex(src.index.clone());
      g.applyMatrix4(o.matrixWorld);
      colliders.push({ geom: g, info });
    }
  });
  let run = null;
  if (season === 'winter' && !hasKickers) {
    run = buildRunFeatures(ctx.data.sled, ctx.terrain);
    root.add(run.group);
    colliders.push(...run.colliders);
  }
  const col = buildCollider(colliders);
  return {
    kind: 'glb', root, hasKickers, run,
    setSeason() {}, colliderFor: () => col,
    extras: root.userData || {},
  };
}
