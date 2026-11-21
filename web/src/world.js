// World loading: GLB(s) -> merged, section-culled render meshes with role materials,
// instanced trees, and one BVH collider (terrain, buildings, pagoda, steps, barriers, trunks).
import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { MeshoptDecoder } from 'three/addons/libs/meshopt_decoder.module.js';
import { mergeGeometries } from 'three/addons/utils/BufferGeometryUtils.js';
import { MeshBVH } from 'three-mesh-bvh';
import { makeRoleMaterials } from './materials.js';
import { loadTextureLibrary } from './textures.js';
import { facadeMaterial, roofMaterial, stoneMaterial, groundMaterial, pavingMaterial, leafMaterial, canopyGeometry, styleOf, hashStr } from './pbr.js';

const SECTION = 100; // m

// ---------------------------------------------------------------- helpers
function floatAttr(attr, size = attr.itemSize) {
  const n = attr.count, out = new Float32Array(n * size);
  for (let i = 0; i < n; i++) {
    out[i * size] = attr.getX(i);
    if (size > 1) out[i * size + 1] = attr.getY(i);
    if (size > 2) out[i * size + 2] = attr.getZ(i);
    if (size > 3) out[i * size + 3] = attr.itemSize > 3 ? attr.getW(i) : 1;
  }
  return new THREE.BufferAttribute(out, size);
}

// world-space float copy of a mesh geometry with a fixed attribute set
function worldGeometry(mesh, { normal = true, color = false, uv = false, objId = null, defaultColor = [1, 1, 1] } = {}) {
  const src = mesh.geometry;
  const g = new THREE.BufferGeometry();
  const pos = floatAttr(src.attributes.position, 3);
  pos.applyMatrix4(mesh.matrixWorld);
  g.setAttribute('position', pos);
  if (normal) {
    let nrm;
    if (src.attributes.normal) nrm = floatAttr(src.attributes.normal, 3);
    else { const t = src.clone(); t.computeVertexNormals(); nrm = floatAttr(t.attributes.normal, 3); }
    nrm.applyNormalMatrix(new THREE.Matrix3().getNormalMatrix(mesh.matrixWorld));
    const a = nrm.array;
    for (let i = 0; i < a.length; i += 3) {
      const l = Math.hypot(a[i], a[i + 1], a[i + 2]) || 1;
      a[i] /= l; a[i + 1] /= l; a[i + 2] /= l;
    }
    g.setAttribute('normal', nrm);
  }
  if (color) {
    if (src.attributes.color) g.setAttribute('color', floatAttr(src.attributes.color, 3));
    else {
      const c = new Float32Array(pos.count * 3);
      for (let i = 0; i < pos.count; i++) c.set(defaultColor, i * 3);
      g.setAttribute('color', new THREE.BufferAttribute(c, 3));
    }
  }
  if (uv) {
    g.setAttribute('uv', src.attributes.uv ? floatAttr(src.attributes.uv, 2) : new THREE.BufferAttribute(new Float32Array(pos.count * 2), 2));
  }
  if (objId !== null) {
    const ids = typeof objId === 'function' ? Float32Array.from({ length: pos.count }, (_, i) => objId(i)) : new Float32Array(pos.count).fill(objId);
    g.setAttribute('objId', new THREE.BufferAttribute(ids, 1));
  }
  if (src.index) g.setIndex(new THREE.BufferAttribute(Uint32Array.from(src.index.array), 1));
  else g.setIndex(new THREE.BufferAttribute(Uint32Array.from({ length: pos.count }, (_, i) => i), 1));
  // flip winding if the matrix mirrors
  if (mesh.matrixWorld.determinant() < 0) {
    const ix = g.index.array;
    for (let i = 0; i < ix.length; i += 3) { const t = ix[i + 1]; ix[i + 1] = ix[i + 2]; ix[i + 2] = t; }
  }
  return g;
}

// mergeGeometries needs identical attribute sets: fill missing attributes with defaults instead of letting a
// whole group silently vanish; on a remaining failure return the parts unmerged
const ATTR_DEFAULT = { normal: [0, 1, 0], color: [1, 1, 1], uv: [0, 0], objId: [0] };
export function mergeSafe(list, label) {
  if (list.length === 1) return [list[0]];
  const names = new Set();
  for (const g of list) for (const n of Object.keys(g.attributes)) names.add(n);
  let filled = 0;
  for (const n of names) {
    const ref = list.find((g) => g.attributes[n]);
    const size = ref.attributes[n].itemSize;
    for (const g of list) {
      if (g.attributes[n]) continue;
      const cnt = g.attributes.position.count, d = ATTR_DEFAULT[n] || new Array(size).fill(0);
      const arr = new Float32Array(cnt * size);
      for (let i = 0; i < cnt; i++) for (let k = 0; k < size; k++) arr[i * size + k] = d[k] ?? 0;
      g.setAttribute(n, new THREE.BufferAttribute(arr, size));
      filled++;
    }
  }
  if (filled) console.warn(`merge ${label}: filled ${filled} missing attribute(s) with defaults`);
  const merged = mergeGeometries(list, false);
  if (merged) return [merged];
  console.warn(`merge ${label}: incompatible geometries, kept ${list.length} separate meshes`);
  return list;
}

function roleOf(obj, matName) {
  const n = obj.name || '';
  const pn = nodeOf(obj) !== obj ? nodeOf(obj).name : '';
  const any = (re) => re.test(n) || re.test(pn);
  if (/^Terrain/i.test(n) || /^Terrain/i.test(pn)) return 'terrain';
  if (any(/^LM_Yasaka_Pagoda/i)) return 'pagodaLM';
  if (/^Steps_/i.test(n) || /^Steps_/i.test(pn)) return 'steps';
  if (any(/^Paving_/i)) return 'paving';
  if (/^(Barrier|Barriers)_/i.test(n) || /^(Barrier|Barriers)_/i.test(pn)) return 'barrier';
  if (/^TreeCrown/i.test(n) || /^TreeCrown/i.test(pn)) return 'crown';
  if (/^Tree_/i.test(n) || /^Tree_/i.test(pn)) return 'trunk';
  if (/^(B|Buildings)_/.test(n) || /^(B|Buildings)_/.test(pn)) {
    if (/roof/i.test(matName)) return 'roof';
    if (/plinth|base|found/i.test(matName)) return 'plinth';
    return 'wall';
  }
  return 'other';
}

// GLTFLoader puts node extras on the Object3D; a multi-primitive mesh becomes a Group (the node) of Meshes
function nodeOf(obj) {
  const p = obj.parent;
  const isPrimGroup = p && p.isGroup && p.parent && p.children.length > 1 && p.children.every((c) => c.isMesh);
  return isPrimGroup ? p : obj;
}
// extras of the node and all its ancestors (closest wins), e.g. art trees: Tree_osm* (extras) > Tree_osm*_mesh
function extrasUp(obj) {
  const chain = [];
  for (let o = obj; o && o.parent; o = o.parent) chain.push(o.userData || {});
  return Object.assign({}, ...chain.reverse());
}
function extrasOf(obj) {
  const n = nodeOf(obj);
  return Object.assign({}, n !== obj ? n.userData : {}, obj.userData);
}

async function exists(url) {
  try {
    const r = await fetch(url, { method: 'HEAD', cache: 'no-store' });
    return r.ok;
  } catch { return false; }
}

// ---------------------------------------------------------------- loader
const gltfLoader = new GLTFLoader();
gltfLoader.setMeshoptDecoder(MeshoptDecoder);
// GLB by URL; '*.b64.txt' = GLB shipped as base64 text (static hosts that do not serve .glb)
export function loadGLB(url, onProgress) {
  return new Promise((res, rej) => {
    if (!/\.b64\.txt(\?|$)/.test(url)) { gltfLoader.load(url, res, onProgress, rej); return; }
    const fl = new THREE.FileLoader(); fl.setResponseType('text');
    fl.load(url, (txt) => {
      try {
        let buf;
        if (typeof Uint8Array.fromBase64 === 'function') buf = Uint8Array.fromBase64(txt.trim());
        else {
          const bin = atob(txt.trim()); buf = new Uint8Array(bin.length);
          for (let i = 0; i < bin.length; i++) buf[i] = bin.charCodeAt(i);
        }
        gltfLoader.parse(buf.buffer, '', res, rej);
      } catch (err) { rej(err); }
    }, onProgress, rej);
  });
}

export async function loadWorld(scene, renderer, progress, { lite = false } = {}) {

  progress(0.02, 'Reading manifest…');
  let manifest = null;
  try {
    const r = await fetch('dist/manifest.json', { cache: 'no-store' });
    if (r.ok) manifest = await r.json();
  } catch { /* fall back below */ }
  let worldUrl, pagodaUrl = null, worldKind = 'blockout';
  if (manifest && manifest.world) {
    worldUrl = 'dist/' + manifest.world.file;
    worldKind = manifest.world.kind || worldKind;
    if (manifest.pagoda) pagodaUrl = 'dist/' + manifest.pagoda.file;
  } else {
    // unbuilt checkout: runtime check for the art/hero files
    worldUrl = (await exists('assets/world_art.glb')) ? 'assets/world_art.glb' : 'assets/world.glb';
    worldKind = /art/.test(worldUrl) ? 'art' : 'blockout';
    if (await exists('assets/pagoda.glb')) pagodaUrl = 'assets/pagoda.glb';
  }

  // texture library (procedural generation runs while the GLB downloads)
  const libPromise = loadTextureLibrary(manifest && manifest.textures);
  // cache-bust the big files per build (static hosts often cache aggressively)
  const ver = manifest && manifest.generated ? '?v=' + encodeURIComponent(manifest.generated) : '';
  worldUrl += ver;
  if (pagodaUrl) pagodaUrl += ver;
  const onProg = (a, b, label) => (e) => {
    if (e.total) progress(a + (b - a) * Math.min(1, e.loaded / e.total), `${label} ${(e.loaded / 1048576).toFixed(1)} / ${(e.total / 1048576).toFixed(1)} MB`);
    else progress(a + (b - a) * 0.5, `${label} ${(e.loaded / 1048576).toFixed(1)} MB`);
  };
  const load = (url, a, b, label) => loadGLB(url, onProg(a, b, label));

  // surface mask: on failure fall back to plain ground (1x1 "soil") instead of failing the whole walk
  const maskPromise = new THREE.TextureLoader().loadAsync('assets/surface_mask.png').catch((e) => {
    console.warn('surface_mask.png unavailable, plain ground used', e && e.type ? e.type : e);
    const t = new THREE.DataTexture(new Uint8Array([0, 0, 0, 255]), 1, 1);
    t.needsUpdate = true;
    return t;
  });
  progress(0.05, 'Downloading the district…');
  const gltf = await load(worldUrl, 0.05, 0.62, 'Downloading the district…');
  let hero = null;
  if (pagodaUrl) {
    try { hero = await load(pagodaUrl, 0.62, 0.72, 'Downloading the pagoda…'); } catch (e) { console.warn('pagoda.glb failed', e); }
  }
  progress(0.74, 'Laying the stones…');
  await new Promise((r) => setTimeout(r, 0));
  const maskTex = await maskPromise;

  const lib = await libPromise;
  const M = makeRoleMaterials();
  const groundMat = groundMaterial(lib, maskTex, { lite });
  // physically based role materials (texture library); keys are render-group material keys
  const P = {
    roof: roofMaterial(lib), wall: facadeMaterial(lib), wallUv: facadeMaterial(lib, { glbUv: true }),
    plinth: stoneMaterial(lib.stonewall, { color: 0xb5aea3 }),
    steps: stoneMaterial(lib.stoneStep, { color: 0xe8e4dc }),
    barrier: stoneMaterial(lib.stonewall, { color: 0xd6cfc4 }),
    pavingStone: pavingMaterial(lib.ishidatami), pavingSett: pavingMaterial(lib.sett),
  };
  gltf.scene.updateMatrixWorld(true);

  const groups = new Map();       // render merge groups: role|section -> [geom]
  const collide = [];             // collider geometries
  const objInfo = [];             // objId -> { name, role, walkable }
  const trees = { trunk: [], crown: [] };
  let pagodaLM = null;
  const extraMeshes = [];

  const addObj = (name, role, walkable) => { objInfo.push({ name, role, walkable }); return objInfo.length - 1; };
  const sectionKey = (g) => {
    g.computeBoundingBox();
    const c = g.boundingBox.getCenter(new THREE.Vector3());
    return `${Math.floor((c.x + 300) / SECTION)},${Math.floor((c.z + 300) / SECTION)}`;
  };
  const groupPush = (map, key, item) => { if (!map.has(key)) map.set(key, []); map.get(key).push(item); };
  const ownGroups = new Map();    // material uuid|section -> { mat, geoms }
  const artMeshes = [];           // authored-material meshes: instanced when the mesh is reused, else merged
  const prepMat = (o) => {
    const mat = Array.isArray(o.material) ? o.material[0] : o.material;
    // the art export ships no normals (faceted look): shade flat from screen-space derivatives
    if (!o.geometry.attributes.normal && !mat.flatShading) { mat.flatShading = true; mat.needsUpdate = true; }
    return mat;
  };
  // surveyed geometry with the physically based role materials
  const addRole = (o, role, ex) => {
    let key = role;
    let g;
    if (role === 'wall') {
      const glbUv = !!(o.geometry.attributes.uv && (ex.facade_uv || (Array.isArray(ex.members) && ex.members.some((q) => q.facade_uv))));
      key = glbUv ? 'wallUv' : 'wall';
      g = worldGeometry(o, { normal: true, color: true, uv: glbUv, defaultColor: [0.8, 0.78, 0.72] });
      g.setAttribute('aFac', facadeAttr(o, g, ex));
    } else if (role === 'roof') {
      g = worldGeometry(o, { normal: true, color: true, defaultColor: [0.3, 0.31, 0.33] });
    } else if (role === 'paving') {
      key = /sett|cobble/i.test(ex.surface || '') ? 'pavingSett' : 'pavingStone';
      g = worldGeometry(o, { normal: true });
    } else {
      g = worldGeometry(o, { normal: true });
    }
    if (role !== 'paving') {
      // per-face normals: the facade/roof/stone shaders build their UV frame from them (exact, no speckle)
      g = g.toNonIndexed();
      g.computeVertexNormals();
    }
    groupPush(groups, `${key}|${sectionKey(g)}`, g);
  };

  const addOwn = (o) => {
    const mat = prepMat(o);
    const useColor = !!mat.vertexColors, useUv = !!(mat.map || mat.normalMap || mat.roughnessMap || mat.emissiveMap);
    const g = worldGeometry(o, { normal: !!o.geometry.attributes.normal, color: useColor, uv: useUv });
    const key = `${mat.uuid}|${sectionKey(g)}`;
    if (!ownGroups.has(key)) ownGroups.set(key, { mat, geoms: [] });
    ownGroups.get(key).geoms.push(g);
  };

  gltf.scene.traverse((o) => {
    if (!o.isMesh) return;
    const matName = (o.material && o.material.name) || '';
    const role = roleOf(o, matName);
    const ex = extrasOf(o);
    const nodeName = nodeOf(o).name || o.name;
    const artTree = worldKind !== 'blockout' && /^(Tree|Shrub)/i.test(nodeName) || (worldKind !== 'blockout' && o.parent && /^(Tree|Shrub)/i.test(o.parent.name));
    if (artTree) {
      if (extrasUp(o).collide === true) trees.trunk.push(o);   // trunk collider only
      artMeshes.push(o);
      return;
    }
    if (role === 'trunk' || role === 'crown') { trees[role].push(o); return; }
    if (role === 'pagodaLM') { pagodaLM = pagodaLM || []; pagodaLM.push(o); return; }
    const walkable = role === 'terrain' || role === 'steps' || ex.walkable === true;
    // street furniture of the art kit (benches, pots, signs, lamps) collides so walls of the visible scene match
    // the physical one, even where the export flags the merged kit as collide=false
    const furniture = /^(Kit_|StreetLamp|Lantern_osm)/i.test(nodeName);
    const collides = walkable || furniture || ex.collide === true || ['roof', 'wall', 'plinth', 'barrier'].includes(role);
    if (collides) {
      // joined sections (build.mjs) keep every source object: per-vertex _member -> extras.members[i].name
      const mem = o.geometry.attributes._member;
      let objId = addObj(nodeName, role, walkable);
      if (mem && Array.isArray(ex.members)) {
        const cache = new Map();
        objId = (i) => {
          const k = Math.round(mem.getX(i));
          if (!cache.has(k)) cache.set(k, addObj((ex.members[k] && ex.members[k].name) || nodeName, role, walkable));
          return cache.get(k);
        };
      }
      collide.push(worldGeometry(o, { normal: false, objId }));
    }
    if (role === 'terrain') {
      const g = worldGeometry(o, { normal: true });
      const m = new THREE.Mesh(g, groundMat);
      m.name = 'Terrain';
      m.receiveShadow = true;
      extraMeshes.push(m);
      return;
    }
    // unknown objects and the art kit: keep the authored material, merge per material + section
    if (role === 'other') {
      artMeshes.push(o);
      return;
    }
    addRole(o, role, ex);
  });

  // hero pagoda (world coordinates) replaces the PLATEAU LOD2 one
  const heroMeshes = [];
  let heroInfo = null;
  if (hero) {
    hero.scene.updateMatrixWorld(true);
    const meshes = [];
    hero.scene.traverse((o) => {
      if (o.isMesh) meshes.push(o);
      if (!heroInfo && o.userData && (o.userData.height_m || o.userData.plateau_id)) heroInfo = { name: o.name, ...o.userData };
    });
    // explicit collider meshes (name *COLLIDER* or extras.collider_for) are used for collision and hidden;
    // without them every visible mesh collides
    const isCol = (o) => /collider/i.test(o.name) || /collider/i.test(nodeOf(o).name) || extrasOf(o).collider_for;
    const hasCol = meshes.some(isCol);
    for (const o of meshes) {
      const col = isCol(o);
      if (col || !hasCol) collide.push(worldGeometry(o, { normal: false, objId: addObj('Hero_Pagoda:' + nodeOf(o).name, 'pagoda', false) }));
      if (col) { o.visible = false; continue; }
      o.castShadow = o.receiveShadow = true;
      heroMeshes.push(o);
    }
    scene.add(hero.scene);
  } else if (pagodaLM) {
    for (const o of pagodaLM) {
      const matName = (o.material && o.material.name) || '';
      const role = /roof/i.test(matName) ? 'roof' : /plinth/i.test(matName) ? 'plinth' : 'wall';
      collide.push(worldGeometry(o, { normal: false, objId: addObj('LM_Yasaka_Pagoda_PLATEAU_LOD2', 'pagoda', false) }));
      addRole(o, role, { ...extrasOf(o), storeys: 1, usage: '422' });
    }
  }

  progress(0.8, 'Raising the machiya…');
  await new Promise((r) => setTimeout(r, 0));

  // merged render meshes per role and section
  const root = new THREE.Group();
  root.name = 'World';
  let drawCalls = 0;
  for (const [key, list] of groups) {
    const role = key.split('|')[0];
    for (const g of mergeSafe(list, key)) {
      g.computeBoundingSphere();
      const m = new THREE.Mesh(g, P[role] || M[role] || M.other);
      m.name = 'Merged_' + key;
      m.castShadow = role !== 'plinth' && !/^paving/.test(role);
      m.receiveShadow = true;
      m.matrixAutoUpdate = false;
      root.add(m);
      drawCalls++;
    }
  }
  for (const m of extraMeshes) { root.add(m); drawCalls++; }

  // documented trees: procedural instanced trees (blockout) / trunk colliders (art)
  const leafMat = leafMaterial(lib);
  const treeInfo = buildTrees(root, trees, M, worldKind, collide, addObj, leafMat);
  // authored meshes: instance every geometry+material used >= 4 times (glTF mesh reuse), merge the rest
  const reuse = new Map();
  for (const o of artMeshes) {
    const mat = Array.isArray(o.material) ? o.material[0] : o.material;
    const k = o.geometry.uuid + '|' + mat.uuid;
    if (!reuse.has(k)) reuse.set(k, []);
    reuse.get(k).push(o);
  }
  let instanced = 0;
  const canopy = canopyGeometry(34);
  for (const list of reuse.values()) {
    if (list.length < 4) { list.forEach(addOwn); continue; }
    let mat = prepMat(list[0]);
    let geom = list[0].geometry, colour = null;
    if (/foliage|leaf|crown|canopy/i.test(mat.name || '')) {
      // authored low-poly crown -> alpha leaf-card canopy fitted to its bounds, tinted by its own colour
      geom.computeBoundingBox();
      const bb = geom.boundingBox, c = bb.getCenter(new THREE.Vector3()), sz = bb.getSize(new THREE.Vector3());
      colour = averageColour(geom) || new THREE.Color(0.2, 0.3, 0.12);
      geom = canopy.clone().scale(sz.x * 0.55, sz.y * 0.55, sz.z * 0.55).translate(c.x, c.y, c.z);
      mat = leafMat;
    }
    const im = new THREE.InstancedMesh(geom, mat, list.length);
    if (colour) { list.forEach((_, i) => im.setColorAt(i, colour)); im.userData.noAO = true; }
    list.forEach((o, i) => im.setMatrixAt(i, o.matrixWorld));
    im.castShadow = !mat.transparent; im.receiveShadow = true;
    im.computeBoundingSphere();
    im.name = 'Instanced_' + (list[0].parent ? list[0].parent.name : list[0].name).replace(/\d+.*$/, '');
    root.add(im); drawCalls++; instanced += list.length;
  }
  for (const [key, { mat, geoms }] of ownGroups) for (const g of mergeSafe(geoms, (mat.name || 'material') + '|' + key.split('|')[1])) {
    g.computeBoundingSphere();
    const m = new THREE.Mesh(g, mat);
    m.name = 'MergedOwn_' + (mat.name || '') + '_' + key.split('|')[1];
    const transparent = mat.transparent || mat.alphaTest > 0;
    m.castShadow = !transparent && !/glow|emiss|light/i.test(mat.name || '');
    m.receiveShadow = true;
    m.matrixAutoUpdate = false;
    root.add(m);
    drawCalls++;
  }
  drawCalls += treeInfo.drawCalls;
  scene.add(root);

  progress(0.88, 'Building the collision world…');
  await new Promise((r) => setTimeout(r, 0));
  const colGeom = mergeGeometries(collide.map((g) => {
    // collider needs exactly position + objId
    for (const n of Object.keys(g.attributes)) if (n !== 'position' && n !== 'objId') g.deleteAttribute(n);
    if (!g.attributes.objId) g.setAttribute('objId', new THREE.BufferAttribute(new Float32Array(g.attributes.position.count), 1));
    return g;
  }), false);
  if (!colGeom) throw new Error('could not build the collision world');
  const t0 = performance.now();
  const bvh = new MeshBVH(colGeom, { maxLeafTris: 8 });
  colGeom.boundsTree = bvh;
  const bvhMs = performance.now() - t0;
  const colliderMesh = new THREE.Mesh(colGeom, new THREE.MeshBasicMaterial({ wireframe: true, color: 0xff00ff }));
  colliderMesh.visible = false;
  colliderMesh.name = 'Collider';

  // authored emissive "glow" materials (shop fronts, lamps) follow the time of day
  const glowMats = [];
  root.traverse((o) => {
    const m = o.material;
    if (m && m.emissive && /glow|emiss/i.test(m.name || '') && !glowMats.includes(m)) { m.userData.baseEmissive = m.emissiveIntensity; glowMats.push(m); }
  });

  // vegetation casters (shadow casting is switched per quality level)
  const treeMeshes = root.children.filter((m) => m.isInstancedMesh && /^(Trees_|Instanced_(Tree|Shrub))/i.test(m.name));

  return {
    root, bvh, glowMats, treeMeshes, wetMats: [groundMat, P.pavingStone, P.pavingSett], texSource: lib.source + ` (${lib.ms} ms)`, colGeom, colliderMesh, objInfo, groundMat, materials: M, heroLoaded: !!hero, heroInfo,
    stats: {
      worldUrl, pagodaUrl: hero ? pagodaUrl : null, worldKind, drawCalls, trees: treeInfo.count,
      colliderTris: colGeom.index.count / 3, bvhMs: Math.round(bvhMs), instanced, manifest,
    },
  };
}

// ---------------------------------------------------------------- trees
function mulberry(a) {
  return () => { a |= 0; a = (a + 0x6d2b79f5) | 0; let t = Math.imul(a ^ (a >>> 15), 1 | a); t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
}

// mean vertex colour of a geometry (art crowns carry their species colour in COLOR_0)
function averageColour(g) {
  const c = g.attributes.color;
  if (!c) return null;
  let r = 0, gg = 0, b = 0;
  for (let i = 0; i < c.count; i++) { r += c.getX(i); gg += c.getY(i); b += c.getZ(i); }
  return new THREE.Color(r / c.count, gg / c.count, b / c.count).multiplyScalar(1.6);
}

// per-vertex facade parameters: aFac = (wall base y, storey height, nStoreys * 16 + style, seed)
function facadeAttr(o, g, ex) {
  const pos = g.attributes.position, n = pos.count;
  const mem = o.geometry.attributes._member;
  const members = Array.isArray(ex.members) ? ex.members : [ex];
  const kOf = (i) => (mem ? Math.round(mem.getX(i)) : 0);
  const lo = new Map(), hi = new Map();
  for (let i = 0; i < n; i++) {
    const k = kOf(i), y = pos.getY(i);
    lo.set(k, Math.min(lo.has(k) ? lo.get(k) : Infinity, y));
    hi.set(k, Math.max(hi.has(k) ? hi.get(k) : -Infinity, y));
  }
  // eave = lowest "top" vertex (walls are quads base->eave; gable apexes are higher)
  const eave = new Map();
  for (let i = 0; i < n; i++) {
    const k = kOf(i), y = pos.getY(i);
    if (y > lo.get(k) + 1.6) eave.set(k, Math.min(eave.has(k) ? eave.get(k) : Infinity, y));
  }
  const params = new Map();
  for (const k of lo.keys()) {
    const e = members[k] || ex;
    const base = lo.get(k), top = eave.has(k) ? eave.get(k) : hi.get(k);
    const h = Math.max(2.4, top - base);
    let storeys = Number(e.storeys) || 0;
    if (!storeys) storeys = Math.max(1, Math.round(h / 3.1));
    storeys = Math.min(storeys, Math.max(1, Math.round(h / 2.3)));
    const storeyH = Math.min(4.6, Math.max(2.3, h / storeys));
    const style = styleOf(e, storeys);
    const seed = hashStr(String(e.plateau_id || e.name || k));
    params.set(k, [base, storeyH, storeys * 16 + style, seed]);
  }
  const arr = new Float32Array(n * 4);
  for (let i = 0; i < n; i++) arr.set(params.get(kOf(i)), i * 4);
  return new THREE.BufferAttribute(arr, 4);
}

function buildTrees(root, trees, M, worldKind, collide, addObj, leafMat) {
  let drawCalls = 0;
  const box = new THREE.Box3(), c = new THREE.Vector3(), s = new THREE.Vector3();
  const tmp = new THREE.Object3D();
  const rnd = mulberry(11);
  // trunk colliders (both modes): prism slightly larger than the visible trunk
  for (const o of trees.trunk) {
    box.setFromObject(o); box.getCenter(c); box.getSize(s);
    // art trees are one mesh (trunk + crown): use a fixed trunk radius at the plan centre
    const r = worldKind === 'blockout' ? Math.max(0.12, Math.min(s.x, s.z) / 2) : 0.2;
    const cg = new THREE.CylinderGeometry(r + 0.06, r + 0.06, s.y, 6, 1, false);
    cg.translate(c.x, box.min.y + s.y / 2, c.z);
    cg.deleteAttribute('normal'); cg.deleteAttribute('uv');
    cg.setAttribute('objId', new THREE.BufferAttribute(new Float32Array(cg.attributes.position.count).fill(addObj(o.name, 'trunk', false)), 1));
    collide.push(cg);
  }

  if (worldKind !== 'blockout') return { count: trees.trunk.length, drawCalls };

  // blockout: procedural painterly trees placed on the documented OSM tree positions/sizes
  const autumn = [[0.55, 0.12, 0.05], [0.72, 0.28, 0.06], [0.62, 0.45, 0.08], [0.2, 0.3, 0.1], [0.16, 0.26, 0.09], [0.16, 0.26, 0.09]];
  if (trees.trunk.length) {
    const tg = new THREE.CylinderGeometry(0.75, 1, 1, 7, 1, false);
    tg.translate(0, 0.5, 0);
    const im = new THREE.InstancedMesh(tg, M.trunk, trees.trunk.length);
    trees.trunk.forEach((o, i) => {
      box.setFromObject(o); box.getCenter(c); box.getSize(s);
      const r = Math.max(0.12, Math.min(s.x, s.z) / 2);
      tmp.position.set(c.x, box.min.y, c.z); tmp.scale.set(r, s.y, r); tmp.rotation.set(0, rnd() * 6.28, 0);
      tmp.updateMatrix(); im.setMatrixAt(i, tmp.matrix);
    });
    im.castShadow = true; im.receiveShadow = true;
    im.computeBoundingSphere();
    im.name = 'Trees_trunks';
    root.add(im); drawCalls++;
  }
  if (trees.crown.length) {
    const im = new THREE.InstancedMesh(canopyGeometry(34), leafMat, trees.crown.length);
    im.userData.noAO = true;
    const col = new THREE.Color();
    trees.crown.forEach((o, i) => {
      box.setFromObject(o); box.getCenter(c); box.getSize(s);
      tmp.position.copy(c); tmp.scale.set(s.x / 2, s.y / 2, s.z / 2); tmp.rotation.set(0, rnd() * 6.28, 0);
      tmp.updateMatrix(); im.setMatrixAt(i, tmp.matrix);
      // late-November palette (artistic): some maples turn, others stay green
      const a = autumn[Math.floor(rnd() * autumn.length)];
      col.setRGB(a[0] * 1.4, a[1] * 1.4, a[2] * 1.4);
      im.setColorAt(i, col);
    });
    if (im.instanceColor) im.instanceColor.needsUpdate = true;
    im.castShadow = true; im.receiveShadow = true;
    im.computeBoundingSphere();
    im.name = 'Trees_crowns';
    root.add(im); drawCalls++;
  }
  return { count: trees.crown.length, drawCalls };
}
