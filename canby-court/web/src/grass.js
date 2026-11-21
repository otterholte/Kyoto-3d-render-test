// Summer grass tufts (placeholder world, Medium+): instanced blade clumps on the lawn class (assets/surface.png)
// in a disc around the camera, re-scattered as you move; wind sway and distance fade in the vertex shader.
import * as THREE from 'three';
import { SU } from './shared.js';
import { mulberry } from './util.js';

function clumpGeometry() {
  const rnd = mulberry(77);
  const pos = [], col = [], nrm = [];
  for (let b = 0; b < 9; b++) {
    const a = rnd() * Math.PI * 2, r = rnd() * 0.07, h = 0.09 + rnd() * 0.11, w = 0.012 + rnd() * 0.006;
    const lean = (rnd() - 0.5) * 0.5, la = rnd() * Math.PI * 2;
    const bx = Math.cos(a) * r, bz = Math.sin(a) * r;
    const dx = Math.cos(la + Math.PI / 2) * w, dz = Math.sin(la + Math.PI / 2) * w;
    const tx = bx + Math.cos(la) * lean * h, tz = bz + Math.sin(la) * lean * h;
    // two-segment blade: base quad + tip triangle
    const mx = (bx + tx) / 2, mz = (bz + tz) / 2, mh = h * 0.55;
    const P = [[bx - dx, 0, bz - dz], [bx + dx, 0, bz + dz], [mx + dx * 0.7, mh, mz + dz * 0.7], [mx - dx * 0.7, mh, mz - dz * 0.7], [tx, h, tz]];
    const tri = [[0, 1, 2], [0, 2, 3], [3, 2, 4]];
    const tone = 0.75 + rnd() * 0.5;
    for (const t of tri) for (const i of t) {
      pos.push(...P[i]);
      const k = P[i][1] / h;
      col.push((0.05 + 0.1 * k) * tone, (0.1 + 0.12 * k) * tone, (0.02 + 0.03 * k) * tone);
      nrm.push(0, 1, 0);
    }
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
  g.setAttribute('normal', new THREE.Float32BufferAttribute(nrm, 3));
  g.setAttribute('color', new THREE.Float32BufferAttribute(col, 3));
  return g;
}

export class Grass {
  constructor(terrain, surfImg, surfMeta, max = 7000) {
    this.terrain = terrain; this.max = max; this.R = 16; this.cell = 0.32;
    this.last = null; this.count = max;
    // lawn weight (B channel) on the CPU
    const W = surfImg.naturalWidth, H = surfImg.naturalHeight;
    const cv = document.createElement('canvas'); cv.width = W; cv.height = H;
    const g = cv.getContext('2d'); g.drawImage(surfImg, 0, 0);
    const d = g.getImageData(0, 0, W, H).data;
    this.lawn = new Uint8Array(W * H);
    for (let i = 0; i < W * H; i++) this.lawn[i] = d[i * 4 + 2];
    this.W = W; this.H = H; this.b = surfMeta.bounds;
    this.uniforms = { uCam: { value: new THREE.Vector3() }, uR: { value: this.R } };
    const m = new THREE.MeshStandardMaterial({ vertexColors: true, roughness: 0.85, side: THREE.DoubleSide });
    m.onBeforeCompile = (sh) => {
      sh.uniforms.uTime = SU.uTime; Object.assign(sh.uniforms, this.uniforms);
      sh.vertexShader = sh.vertexShader.replace('#include <common>', '#include <common>\nuniform float uTime, uR; uniform vec3 uCam;')
        .replace('#include <begin_vertex>', `#include <begin_vertex>
vec3 ip = vec3(instanceMatrix[3][0], instanceMatrix[3][1], instanceMatrix[3][2]);
float fade = 1.0 - smoothstep(uR * 0.6, uR, distance(ip.xz, uCam.xz));
transformed *= fade;
float sway = sin(uTime * 1.7 + ip.x * 0.7 + ip.z * 0.5) * 0.5 + sin(uTime * 3.1 + ip.x * 2.3) * 0.25;
transformed.x += sway * 0.05 * position.y * 6.0; transformed.z += sway * 0.03 * position.y * 6.0;`)
        .replace('#include <beginnormal_vertex>', '#include <beginnormal_vertex>\nobjectNormal = vec3(0.0, 1.0, 0.0);');
    };
    m.customProgramCacheKey = () => 'cc-grass';
    this.mesh = new THREE.InstancedMesh(clumpGeometry(), m, max);
    this.mesh.count = 0; this.mesh.frustumCulled = false; this.mesh.receiveShadow = true; this.mesh.name = 'GrassTufts';
    this.mesh.userData.noAO = true;
    this.M = new THREE.Matrix4(); this.Q = new THREE.Quaternion(); this.S = new THREE.Vector3(); this.P = new THREE.Vector3();
  }
  lawnAt(x, y) {
    const [x0, y0, x1, y1] = this.b;
    const c = Math.floor((x - x0) / (x1 - x0) * this.W), r = Math.floor((y1 - y) / (y1 - y0) * this.H);
    if (c < 0 || r < 0 || c >= this.W || r >= this.H) return 0;
    return this.lawn[r * this.W + c] / 255;
  }
  setMax(n) { this.count = Math.min(n, this.max); this.last = null; }
  update(camPos) {
    this.uniforms.uCam.value.copy(camPos);
    const x = camPos.x, y = -camPos.z;
    if (this.last && Math.hypot(x - this.last[0], y - this.last[1]) < 3) return;
    this.last = [x, y];
    const R = this.R, c = this.cell;
    let n = 0;
    const gx0 = Math.floor((x - R) / c), gx1 = Math.ceil((x + R) / c), gy0 = Math.floor((y - R) / c), gy1 = Math.ceil((y + R) / c);
    for (let gy = gy0; gy <= gy1 && n < this.count; gy++) {
      for (let gx = gx0; gx <= gx1 && n < this.count; gx++) {
        // stable per-cell jitter (hash of the cell)
        let h = (gx * 73856093) ^ (gy * 19349663); h = (h ^ (h >>> 13)) * 1274126177; h ^= h >>> 16;
        const r1 = ((h >>> 0) % 1000) / 1000, r2 = (((h >>> 10) >>> 0) % 1000) / 1000, r3 = (((h >>> 20) >>> 0) % 1000) / 1000;
        const px = (gx + r1) * c, py = (gy + r2) * c;
        if ((px - x) ** 2 + (py - y) ** 2 > R * R) continue;
        const l = this.lawnAt(px, py);
        if (l < 0.55 || r3 > l * 1.1) continue;
        this.P.set(px, this.terrain.height(px, py) - 0.01, -py);
        this.Q.setFromAxisAngle(new THREE.Vector3(0, 1, 0), r3 * 6.28);
        const s = 0.8 + r1 * 0.6;
        this.S.set(s, s * (0.8 + r2 * 0.5), s);
        this.mesh.setMatrixAt(n++, this.M.compose(this.P, this.Q, this.S));
      }
    }
    this.mesh.count = n;
    this.mesh.instanceMatrix.needsUpdate = true;
  }
}
