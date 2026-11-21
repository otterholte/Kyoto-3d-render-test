// Placeholder vegetation from data/processed/trees.json: instanced procedural conifers (Douglas-fir / redcedar),
// deciduous trees (leafy in summer, bare branch skeletons in winter), small ornamentals, and hedges along the
// digitised hedge lines. Snow settles on upward-facing needles/branches in winter (shader). Trunks + hedges collide.
import * as THREE from 'three';
import { mergeGeometries } from 'three/addons/utils/BufferGeometryUtils.js';
import { mulberry } from './util.js';
import { SU, SNOW_GLSL } from './shared.js';

function colorize(g, fn) {
  const p = g.attributes.position, c = new Float32Array(p.count * 3);
  for (let i = 0; i < p.count; i++) { const v = fn(p.getX(i), p.getY(i), p.getZ(i)); c[i * 3] = v[0]; c[i * 3 + 1] = v[1]; c[i * 3 + 2] = v[2]; }
  g.setAttribute('color', new THREE.BufferAttribute(c, 3));
  return g;
}
const prep = (g) => { g = g.index ? g.toNonIndexed() : g; for (const k of Object.keys(g.attributes)) if (!['position', 'normal', 'color'].includes(k)) g.deleteAttribute(k); return g; };

// unit conifer: height 1 (base at 0), crown radius 1; trunk visible below 0.18
function coniferGeometry(seed, cedar = false) {
  const rnd = mulberry(seed);
  const parts = [];
  const trunk = new THREE.CylinderGeometry(0.018, 0.035, 0.6, 7, 1, true); trunk.translate(0, 0.3, 0);
  parts.push(colorize(prep(trunk), () => [0.09, 0.06, 0.045]));
  const whorls = 13;
  for (let i = 0; i < whorls; i++) {
    const t = i / whorls;
    const y0 = 0.14 + t * 0.84;
    const rad = Math.pow(1 - t, 0.85) * (0.9 + rnd() * 0.25) + 0.04;
    const h = 0.16 + (1 - t) * 0.06;
    const cone = new THREE.ConeGeometry(rad, h, 11, 2, true);
    const p = cone.attributes.position;
    for (let k = 0; k < p.count; k++) {
      const x = p.getX(k), y = p.getY(k), z = p.getZ(k);
      const a = Math.atan2(z, x);
      const jag = 1 + 0.22 * Math.sin(a * 5 + i * 1.7 + rnd()) * (y < 0 ? 1 : 0.2);
      const droop = y < 0 ? -0.025 * (cedar ? 2 : 1) : 0;
      p.setXYZ(k, x * jag, y + droop + (rnd() - 0.5) * 0.01, z * jag);
    }
    cone.computeVertexNormals();
    cone.rotateY(rnd() * 6.28);
    cone.translate(0, y0 + h / 2, 0);
    const g = prep(cone);
    // fluff the normals upward/outward so the crown shades as a volume, not as layered cones
    const n = g.attributes.normal, pp = g.attributes.position;
    for (let k = 0; k < n.count; k++) {
      const ox = pp.getX(k), oz = pp.getZ(k), l = Math.hypot(ox, oz) || 1;
      const v = new THREE.Vector3(n.getX(k) * 0.5 + (ox / l) * 0.7, n.getY(k) * 0.5 + 0.35, n.getZ(k) * 0.5 + (oz / l) * 0.7).normalize();
      n.setXYZ(k, v.x, v.y, v.z);
    }
    const base = cedar ? [0.05, 0.075, 0.03] : [0.028, 0.06, 0.028];
    parts.push(colorize(g, (x, y, z) => { const r = Math.hypot(x, z) / Math.max(rad, 0.05); const k = 0.55 + 0.6 * r + (rnd() - 0.5) * 0.15; return [base[0] * k, base[1] * k * 1.05, base[2] * k]; }));
  }
  return mergeGeometries(parts);
}

// bare deciduous skeleton (unit height), recursive limbs
function bareGeometry(seed) {
  const rnd = mulberry(seed);
  const parts = [];
  const up = new THREE.Vector3(0, 1, 0);
  const limb = (start, dir, len, r, depth) => {
    const end = start.clone().addScaledVector(dir, len);
    const g = new THREE.CylinderGeometry(r * 0.62, r, len, depth > 2 ? 6 : 4, 1, true);
    g.translate(0, len / 2, 0);
    g.applyQuaternion(new THREE.Quaternion().setFromUnitVectors(up, dir));
    g.translate(start.x, start.y, start.z);
    parts.push(colorize(prep(g), () => [0.075 + rnd() * 0.02, 0.065, 0.055]));
    if (depth <= 0) return;
    const kids = depth > 2 ? 3 : 2 + (rnd() < 0.5 ? 1 : 0);
    for (let i = 0; i < kids; i++) {
      const d = dir.clone();
      const ax = new THREE.Vector3(rnd() - 0.5, 0, rnd() - 0.5).normalize();
      d.applyAxisAngle(ax, 0.45 + rnd() * 0.45);
      d.y = Math.max(d.y, 0.15); d.normalize();
      const s = end.clone().lerp(start, i === 0 ? 0 : rnd() * 0.35);
      limb(s, d, len * (0.62 + rnd() * 0.15), r * 0.62, depth - 1);
    }
  };
  limb(new THREE.Vector3(0, 0, 0), new THREE.Vector3(0, 1, 0), 0.36, 0.045, 4);
  return mergeGeometries(parts);
}

// leafy deciduous crown (unit height, radius 1): clustered displaced blobs on a short trunk
function leafyGeometry(seed) {
  const rnd = mulberry(seed);
  const parts = [];
  const trunk = new THREE.CylinderGeometry(0.03, 0.05, 0.45, 7, 1, true); trunk.translate(0, 0.225, 0);
  parts.push(colorize(prep(trunk), () => [0.08, 0.065, 0.05]));
  const blobs = 9;
  for (let i = 0; i < blobs; i++) {
    const a = rnd() * 6.28, rr = i === 0 ? 0 : 0.35 + rnd() * 0.4;
    const s = i === 0 ? 0.6 : 0.36 + rnd() * 0.2;
    const ico = new THREE.IcosahedronGeometry(1, 2);
    const p = ico.attributes.position;
    for (let k = 0; k < p.count; k++) {
      const v = new THREE.Vector3(p.getX(k), p.getY(k), p.getZ(k));
      const d = 1 + 0.18 * Math.sin(v.x * 7 + i) * Math.sin(v.y * 6 + 1.3 * i) * Math.sin(v.z * 8);
      v.multiplyScalar(d);
      p.setXYZ(k, v.x, v.y, v.z);
    }
    ico.computeVertexNormals();
    ico.scale(s, s * 0.8, s);
    ico.translate(Math.cos(a) * rr, 0.6 + (i === 0 ? 0.1 : rnd() * 0.3), Math.sin(a) * rr);
    const tone = 0.8 + rnd() * 0.4;
    parts.push(colorize(prep(ico), (x, y) => { const k = tone * (0.6 + 0.6 * THREE.MathUtils.clamp((y - 0.35) / 0.65, 0, 1)); return [0.05 * k, 0.1 * k, 0.025 * k]; }));
  }
  return mergeGeometries(parts);
}

function vegMaterial(kind) {
  const m = new THREE.MeshStandardMaterial({ vertexColors: true, roughness: kind === 'bark' ? 0.95 : 0.88, metalness: 0, side: kind === 'bark' ? THREE.FrontSide : THREE.DoubleSide });
  m.name = 'CC_Veg_' + kind;
  m.onBeforeCompile = (sh) => {
    sh.uniforms.uSeason = SU.uSeason; sh.uniforms.uNoise = SU.uNoise;
    sh.vertexShader = sh.vertexShader
      .replace('#include <common>', '#include <common>\nvarying vec3 vWN; varying vec3 vWP;')
      .replace('#include <worldpos_vertex>', `#include <worldpos_vertex>
vec4 wpp = vec4(transformed, 1.0);
#ifdef USE_INSTANCING
wpp = instanceMatrix * wpp;
#endif
vWP = (modelMatrix * wpp).xyz;
vec3 wn0 = objectNormal;
#ifdef USE_INSTANCING
wn0 = mat3(instanceMatrix) * wn0;
#endif
vWN = normalize(mat3(modelMatrix) * wn0);`);
    sh.fragmentShader = sh.fragmentShader
      .replace('#include <common>', `#include <common>\nvarying vec3 vWN; varying vec3 vWP; uniform float uSeason; uniform sampler2D uNoise;\n${SNOW_GLSL}`)
      .replace('#include <color_fragment>', `#include <color_fragment>
float sn = ccSnow(normalize(vWN), vWP, ${kind === 'bark' ? '-0.25' : '0.0'});
diffuseColor.rgb = mix(diffuseColor.rgb, vec3(0.84, 0.87, 0.92), sn * ${kind === 'bark' ? '0.85' : '0.8'});`);
  };
  m.customProgramCacheKey = () => 'cc-veg-' + kind;
  return m;
}

export function buildVegetation(data, terrain) {
  const group = new THREE.Group(); group.name = 'Vegetation';
  const rnd = mulberry(42);
  const variants = {
    conifer: [coniferGeometry(11), coniferGeometry(23), coniferGeometry(37, true)],
    leafy: [leafyGeometry(5), leafyGeometry(9)],
    bare: [bareGeometry(3), bareGeometry(8), bareGeometry(13)],
  };
  const mats = { needle: vegMaterial('needle'), leaf: vegMaterial('leaf'), bark: vegMaterial('bark') };
  const buckets = new Map();     // key -> list of matrices
  const add = (key, m) => { if (!buckets.has(key)) buckets.set(key, []); buckets.get(key).push(m); };
  const colliders = [];
  const trunkPos = [];
  const M = new THREE.Matrix4(), Q = new THREE.Quaternion(), S = new THREE.Vector3(), P = new THREE.Vector3();
  for (const t of data.trees) {
    const z = terrain.height(t.x, t.y) - 0.15;
    const h = Math.max(2.5, t.h || 8), r = Math.max(0.8, t.r || 2.5);
    Q.setFromAxisAngle(new THREE.Vector3(0, 1, 0), rnd() * 6.28);
    P.set(t.x, z, -t.y);
    const conifer = t.type === 'conifer' || t.evergreen;
    if (conifer) {
      const cedar = /cedar/i.test(t.species) && rnd() < 0.5;
      const v = cedar ? 2 : Math.floor(rnd() * 2);
      S.set(r * 1.05, h, r * 1.05);
      add(`conifer${v}`, M.compose(P, Q, S).clone());
    } else {
      const v = Math.floor(rnd() * 3);
      S.set(r * 1.1, h, r * 1.1);
      add(`bare${v}`, M.compose(P, Q, S).clone());
      add(`leafy${v % 2}`, M.compose(P, Q, S).clone());
    }
    trunkPos.push([t.x, t.y, z, conifer ? 0.32 : 0.24]);
  }
  const meshes = { summer: [], winter: [], both: [] };
  for (const [key, list] of buckets) {
    const kind = key.replace(/\d+$/, ''), v = +key.match(/\d+$/)[0];
    const geo = variants[kind][v];
    const mat = kind === 'conifer' ? mats.needle : kind === 'leafy' ? mats.leaf : mats.bark;
    const im = new THREE.InstancedMesh(geo, mat, list.length);
    list.forEach((m, i) => im.setMatrixAt(i, m));
    im.castShadow = true; im.receiveShadow = true;
    im.name = 'Trees_' + key;
    im.computeBoundingSphere();
    group.add(im);
    (kind === 'conifer' ? meshes.both : kind === 'leafy' ? meshes.summer : meshes.winter).push(im);
  }
  // trunk colliders: 8-sided prisms, 3 m tall
  {
    const pos = [], idx = [];
    for (const [x, y, z, r] of trunkPos) {
      const b = pos.length / 3;
      for (let k = 0; k < 8; k++) { const a = k / 8 * Math.PI * 2; pos.push(x + Math.cos(a) * r, z, -(y + Math.sin(a) * r), x + Math.cos(a) * r, z + 3.2, -(y + Math.sin(a) * r)); }
      for (let k = 0; k < 8; k++) { const a = b + k * 2, c = b + ((k + 1) % 8) * 2; idx.push(a, c, a + 1, c, c + 1, a + 1); }
    }
    const g = new THREE.BufferGeometry(); g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3)); g.setIndex(idx);
    colliders.push({ geom: g, info: { name: 'Tree trunk', kind: 'tree', walkable: false, collide: true } });
  }
  // hedges: overlapping ellipsoids along the polylines (columnar arborvitae rows become separate cones)
  {
    const blob = new THREE.IcosahedronGeometry(1, 2);
    const bp = blob.attributes.position;
    for (let k = 0; k < bp.count; k++) { const s = 1 + 0.1 * Math.sin(bp.getX(k) * 9) * Math.sin(bp.getZ(k) * 7); bp.setXYZ(k, bp.getX(k) * s, bp.getY(k) * s, bp.getZ(k) * s); }
    blob.computeVertexNormals();
    const hedgeGeo = colorize(prep(blob), (x, y) => { const k = 0.7 + 0.4 * (y + 1) / 2; return [0.035 * k, 0.075 * k, 0.03 * k]; });
    const col = new THREE.ConeGeometry(1, 1, 10, 3); col.translate(0, 0.5, 0);
    const colGeo = colorize(prep(col), (x, y) => { const k = 0.65 + 0.5 * y; return [0.04 * k, 0.08 * k, 0.03 * k]; });
    const hm = [], cm = [];
    const pos = [], idx = [];
    for (const h of data.hedges) {
      const columnar = /columnar|arborvitae/i.test(h.kind);
      for (let i = 0; i < h.pts.length - 1; i++) {
        const [ax, ay] = h.pts[i], [bx, by] = h.pts[i + 1];
        const L = Math.hypot(bx - ax, by - ay);
        const stepL = columnar ? Math.max(0.9, L / 9) : Math.max(0.5, h.w * 0.6);
        const nS = Math.max(1, Math.round(L / stepL));
        for (let s = 0; s <= nS; s++) {
          const t = s / nS, x = ax + (bx - ax) * t, y = ay + (by - ay) * t;
          const z = terrain.height(x, y);
          Q.setFromAxisAngle(new THREE.Vector3(0, 1, 0), rnd() * 6.28);
          if (columnar) { P.set(x, z - 0.1, -y); S.set(h.w * 0.45, h.h, h.w * 0.45); cm.push(M.compose(P, Q, S).clone()); }
          else { P.set(x, z + h.h * 0.45, -y); S.set(h.w * 0.62, h.h * 0.58, h.w * 0.62); hm.push(M.compose(P, Q, S).clone()); }
        }
        // collider box along the segment
        const nx = -(by - ay) / L * h.w * 0.45, ny = (bx - ax) / L * h.w * 0.45;
        const z0 = Math.min(terrain.height(ax, ay), terrain.height(bx, by)) - 0.3, z1 = z0 + h.h + 0.3;
        const b = pos.length / 3;
        for (const [px, py] of [[ax + nx, ay + ny], [bx + nx, by + ny], [bx - nx, by - ny], [ax - nx, ay - ny]]) pos.push(px, z0, -py, px, z1, -py);
        for (let k = 0; k < 4; k++) { const a = b + k * 2, c = b + ((k + 1) % 4) * 2; idx.push(a, c, a + 1, c, c + 1, a + 1); }
      }
    }
    for (const [geo, list, name] of [[hedgeGeo, hm, 'Hedges'], [colGeo, cm, 'Arborvitae']]) {
      if (!list.length) continue;
      const im = new THREE.InstancedMesh(geo, mats.leaf, list.length);
      list.forEach((m, i) => im.setMatrixAt(i, m));
      im.castShadow = im.receiveShadow = true; im.name = name; im.computeBoundingSphere();
      group.add(im); meshes.both.push(im);
    }
    const g = new THREE.BufferGeometry(); g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3)); g.setIndex(idx);
    colliders.push({ geom: g, info: { name: 'Hedge', kind: 'hedge', walkable: false, collide: true } });
  }
  const setSeason = (s) => {
    for (const m of meshes.summer) m.visible = s === 'summer';
    for (const m of meshes.winter) m.visible = s === 'winter';
  };
  return { group, colliders, setSeason, count: data.trees.length };
}
