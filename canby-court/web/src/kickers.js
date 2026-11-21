// Sled run features from data/game/jumps.json (ARTISTIC additions on the measured run): three snow kickers and the
// run-out berm with hay bales. Geometry drapes on the DTM. Kicker convention used here (placeholder world):
//   centre_local = middle of the ramp; the ramp rises along heading_deg (math angle, CCW from east) over
//   ramp_length_m to lip_height_m above the run surface, with the lip angle lip_angle_deg measured against the run
//   surface (profile h(s) = H (s/L)^k, k = L tan(angle) / H), then a steep back face. width_m = flat top width.
// jumpMeta() is used by the game in every case (also when the kickers come from world_winter.glb).
import * as THREE from 'three';
import { SU } from './shared.js';

const BACK_DEG = 40;

export function jumpMeta(jumps, terrain = null) {
  return jumps.map((j) => {
    const a = THREE.MathUtils.degToRad(j.heading_deg);
    const dir = [Math.cos(a), Math.sin(a)];
    const [cx, cy] = j.center_local;
    const L = j.ramp_length_m;
    return {
      id: j.id, label: j.id.includes('big') ? 'Big kicker' : j.id.includes('mid') ? 'Mid kicker' : 'Starter kicker',
      dir, center: [cx, cy], L, H: j.lip_height_m, angle: j.lip_angle_deg, width: j.width_m, landing: j.landing_length_m,
      start: [cx - dir[0] * L / 2, cy - dir[1] * L / 2],
      lip: [cx + dir[0] * L / 2, cy + dir[1] * L / 2],
      arc: j.arc_m,
      // run-surface grade (rad, + = downhill) across the lip, used to launch along the lip angle
      grade: terrain ? Math.atan((terrain.height(cx + dir[0] * (L / 2 - 2), cy + dir[1] * (L / 2 - 2)) - terrain.height(cx + dir[0] * (L / 2 + 2), cy + dir[1] * (L / 2 + 2))) / 4) : 0,
    };
  });
}

function profile(j, s) {
  // s from ramp start along heading; returns height above the run surface (full width)
  const L = j.L, H = j.H;
  const k = Math.max(1.05, L * Math.tan(THREE.MathUtils.degToRad(j.angle)) / H);
  if (s <= 0) return 0;
  if (s <= L) return H * Math.pow(s / L, k);
  const back = H / Math.tan(THREE.MathUtils.degToRad(BACK_DEG));
  if (s <= L + back) return H * (1 - (s - L) / back);
  return 0;
}

function snowMaterial() {
  const m = new THREE.MeshStandardMaterial({ color: 0xffffff, roughness: 0.55, metalness: 0 });
  m.name = 'CC_SnowFeature';
  m.onBeforeCompile = (sh) => {
    sh.uniforms.uNoise = SU.uNoise;
    sh.vertexShader = sh.vertexShader.replace('#include <common>', '#include <common>\nvarying vec3 vWK;')
      .replace('#include <worldpos_vertex>', '#include <worldpos_vertex>\nvWK = (modelMatrix * vec4(transformed, 1.0)).xyz;');
    sh.fragmentShader = sh.fragmentShader.replace('#include <common>', '#include <common>\nvarying vec3 vWK; uniform sampler2D uNoise;')
      .replace('#include <map_fragment>', `
vec4 kn = texture2D(uNoise, vWK.xz * 0.9);
diffuseColor.rgb *= vec3(0.8, 0.82, 0.87) * (0.93 + 0.1 * kn.r);`);
  };
  m.customProgramCacheKey = () => 'cc-snowfeature';
  return m;
}

export function buildRunFeatures(sled, terrain) {
  const group = new THREE.Group(); group.name = 'SledRunFeatures';
  const meta = jumpMeta(sled.jumps, terrain);
  const geos = [];
  // ---- kickers: grid over (s, w); sides fall away at 45 degrees
  for (const j of meta) {
    const back = j.H / Math.tan(THREE.MathUtils.degToRad(BACK_DEG));
    const S = j.L + back, half = j.width / 2, side = j.H * 1.1 + 0.3;
    const ns = 36, nw = 14;
    const pos = [], idx = [];
    for (let a = 0; a <= ns; a++) {
      const s = -0.4 + (S + 0.8) * (a / ns);
      const ph = profile(j, s);
      for (let b = 0; b <= nw; b++) {
        const w = -(half + side) + 2 * (half + side) * (b / nw);
        const over = Math.max(0, Math.abs(w) - half);
        const hh = Math.max(0, ph - over * 1.0);
        const x = j.start[0] + j.dir[0] * s - j.dir[1] * w, y = j.start[1] + j.dir[1] * s + j.dir[0] * w;
        pos.push(x, terrain.height(x, y) + hh - 0.04 + (hh > 0 ? 0.04 : 0), -y);
      }
    }
    for (let a = 0; a < ns; a++) for (let b = 0; b < nw; b++) {
      const i = a * (nw + 1) + b, i2 = i + nw + 1;
      idx.push(i, i2, i + 1, i + 1, i2, i2 + 1);
    }
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3)); g.setIndex(idx);
    g.computeVertexNormals();
    fixUp(g);
    g.userData = { name: 'Kicker_' + j.id, kind: 'kicker' };
    geos.push(g);
  }
  // ---- berm: smooth mound across the run
  {
    const b = sled.berm;
    const a = THREE.MathUtils.degToRad(b.heading_deg), d = [Math.cos(a), Math.sin(a)];
    const [cx, cy] = b.center_local, W = b.width_m, Dp = b.depth_m, H = b.height_m;
    const ns = 20, nw = 24, pos = [], idx = [];
    for (let i = 0; i <= ns; i++) {
      const s = -Dp * 0.9 + (Dp * 1.8) * (i / ns);
      const fs = Math.cos(Math.min(1, Math.abs(s) / (Dp * 0.9)) * Math.PI / 2) ** 1.6;
      for (let k = 0; k <= nw; k++) {
        const w = -(W / 2 + 1.5) + (W + 3) * (k / nw);
        const fw = Math.min(1, Math.max(0, (W / 2 + 1.5 - Math.abs(w)) / 2.5));
        const fwS = fw * fw * (3 - 2 * fw);
        const x = cx + d[0] * s - d[1] * w, y = cy + d[1] * s + d[0] * w;
        pos.push(x, terrain.height(x, y) + H * fs * fwS - 0.05, -y);
      }
    }
    for (let i = 0; i < ns; i++) for (let k = 0; k < nw; k++) { const p = i * (nw + 1) + k, q = p + nw + 1; idx.push(p, q, p + 1, p + 1, q, q + 1); }
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3)); g.setIndex(idx);
    g.computeVertexNormals(); fixUp(g);
    g.userData = { name: 'RunoutBerm', kind: 'berm' };
    geos.push(g);
    // hay bales on the uphill face of the berm (padding), straw colour
    const bale = new THREE.BoxGeometry(1.15, 0.42, 0.5, 2, 1, 1);
    const straw = new THREE.MeshStandardMaterial({ color: 0x9c7b3c, roughness: 0.95 });
    straw.name = 'CC_Straw';
    straw.onBeforeCompile = (sh) => {
      sh.uniforms.uNoise = SU.uNoise; sh.uniforms.uSeason = SU.uSeason;
      sh.vertexShader = sh.vertexShader.replace('#include <common>', '#include <common>\nvarying vec3 vWB; varying vec3 vNB;')
        .replace('#include <worldpos_vertex>', '#include <worldpos_vertex>\nvWB = (modelMatrix * instanceMatrix * vec4(transformed, 1.0)).xyz; vNB = mat3(modelMatrix) * mat3(instanceMatrix) * objectNormal;');
      sh.fragmentShader = sh.fragmentShader.replace('#include <common>', '#include <common>\nvarying vec3 vWB; varying vec3 vNB; uniform sampler2D uNoise; uniform float uSeason;')
        .replace('#include <map_fragment>', `
float st = texture2D(uNoise, vec2(vWB.x * 6.0 + vWB.z * 6.0, vWB.y * 0.7)).r;
diffuseColor.rgb *= 0.7 + 0.6 * st;
diffuseColor.rgb = mix(diffuseColor.rgb, vec3(0.85, 0.87, 0.92), smoothstep(0.6, 0.9, normalize(vNB).y) * 0.85);`);
    };
    straw.customProgramCacheKey = () => 'cc-straw';
    const n = 7;
    const im = new THREE.InstancedMesh(bale, straw, n * 2 - 1);
    const M = new THREE.Matrix4(), Q = new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 1, 0), a + Math.PI / 2);
    let c = 0;
    for (let row = 0; row < 2; row++) {
      const m = n - row;
      for (let k = 0; k < m; k++) {
        const w = (k - (m - 1) / 2) * 1.2;
        const s = -Dp * 0.75;
        const x = cx + d[0] * s - d[1] * w, y = cy + d[1] * s + d[0] * w;
        const z = terrain.height(x, y) + 0.21 + row * 0.42 + 0.03;
        const P = new THREE.Vector3(x, z, -y);
        M.compose(P, Q, new THREE.Vector3(1, 1, 1));
        im.setMatrixAt(c++, M);
      }
    }
    im.castShadow = im.receiveShadow = true; im.name = 'HayBales';
    im.computeBoundingSphere();
    group.add(im);
    // bale collider (soft: kind 'hay', walkable top)
    const cp = [], ci = [];
    const bw = n * 1.2 / 2, s0 = -Dp * 0.75 - 0.3, s1 = -Dp * 0.75 + 0.3;
    const corners = [[s0, -bw], [s1, -bw], [s1, bw], [s0, bw]].map(([s, w]) => [cx + d[0] * s - d[1] * w, cy + d[1] * s + d[0] * w]);
    const zb = Math.min(...corners.map(([x, y]) => terrain.height(x, y))) - 0.2, zt = zb + 1.05;
    for (const [x, y] of corners) cp.push(x, zb, -y, x, zt, -y);
    for (let k = 0; k < 4; k++) { const p = k * 2, q = ((k + 1) % 4) * 2; ci.push(p, q, p + 1, q, q + 1, p + 1); }
    ci.push(1, 3, 5, 1, 5, 7);
    const hg = new THREE.BufferGeometry(); hg.setAttribute('position', new THREE.Float32BufferAttribute(cp, 3)); hg.setIndex(ci);
    hg.userData = { name: 'HayBales', kind: 'hay' };
    geos.push(hg);
  }
  const mat = snowMaterial();
  const colliders = [];
  for (const g of geos) {
    if (g.userData.kind !== 'hay') {
      const m = new THREE.Mesh(g, mat); m.name = g.userData.name; m.receiveShadow = true; m.castShadow = true;
      group.add(m);
    }
    colliders.push({ geom: g, info: { name: g.userData.name, kind: g.userData.kind, walkable: g.userData.kind !== 'hay', collide: true } });
  }
  // marker poles with small flags beside each lip (artistic, helps reading the jumps)
  {
    const pole = new THREE.CylinderGeometry(0.02, 0.02, 1.6, 5); pole.translate(0, 0.8, 0);
    const flag = new THREE.PlaneGeometry(0.35, 0.22); flag.translate(0.18, 1.45, 0);
    const pm = new THREE.MeshStandardMaterial({ color: 0x222222, roughness: 0.6 });
    const fm = new THREE.MeshStandardMaterial({ color: 0xd9381e, roughness: 0.7, side: THREE.DoubleSide });
    const ip = new THREE.InstancedMesh(pole, pm, meta.length * 2), iff = new THREE.InstancedMesh(flag, fm, meta.length * 2);
    const M = new THREE.Matrix4();
    let c = 0;
    for (const j of meta) for (const sgn of [-1, 1]) {
      const w = sgn * (j.width / 2 + 1.0);
      const x = j.lip[0] - j.dir[1] * w, y = j.lip[1] + j.dir[0] * w;
      M.makeRotationY(Math.atan2(j.dir[1], j.dir[0]) + Math.PI);
      M.setPosition(x, terrain.height(x, y), -y);
      ip.setMatrixAt(c, M); iff.setMatrixAt(c, M); c++;
    }
    ip.castShadow = iff.castShadow = true;
    ip.computeBoundingSphere(); iff.computeBoundingSphere();
    group.add(ip, iff);
  }
  return { group, colliders, meta };
}

function fixUp(g) {
  // make sure normals face up (winding of the generated grids)
  const n = g.attributes.normal;
  let s = 0;
  for (let i = 0; i < n.count; i++) s += n.getY(i);
  if (s < 0) {
    const ix = g.index.array;
    for (let i = 0; i < ix.length; i += 3) { const t = ix[i + 1]; ix[i + 1] = ix[i + 2]; ix[i + 2] = t; }
    g.computeVertexNormals();
  }
}
