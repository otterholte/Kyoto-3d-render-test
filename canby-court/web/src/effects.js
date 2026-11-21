// Winter effects: falling snow (GPU-wrapped points around the camera), breath puffs, snow spray (skids, landings,
// wipeouts), the sled's track ribbon and boot prints in the snow. All artistic.
import * as THREE from 'three';

const flakeTex = (() => {
  let t = null;
  return () => {
    if (t) return t;
    const c = document.createElement('canvas'); c.width = c.height = 64;
    const g = c.getContext('2d');
    const gr = g.createRadialGradient(32, 32, 0, 32, 32, 32);
    gr.addColorStop(0, 'rgba(255,255,255,1)'); gr.addColorStop(0.35, 'rgba(255,255,255,0.75)'); gr.addColorStop(1, 'rgba(255,255,255,0)');
    g.fillStyle = gr; g.fillRect(0, 0, 64, 64);
    t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace;
    return t;
  };
})();

export class Snowfall {
  constructor(max = 4000) {
    const BOX = [70, 34, 70];
    const pos = new Float32Array(max * 3), rnd = new Float32Array(max);
    for (let i = 0; i < max; i++) { pos[i * 3] = Math.random() * BOX[0]; pos[i * 3 + 1] = Math.random() * BOX[1]; pos[i * 3 + 2] = Math.random() * BOX[2]; rnd[i] = Math.random(); }
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.BufferAttribute(pos, 3));
    g.setAttribute('aRnd', new THREE.BufferAttribute(rnd, 1));
    this.uniforms = {
      uTime: { value: 0 }, uCam: { value: new THREE.Vector3() }, uBox: { value: new THREE.Vector3(...BOX) }, uMap: { value: flakeTex() },
      uScale: { value: 400 }, uColor: { value: new THREE.Color(0.92, 0.94, 0.98) }, uWind: { value: new THREE.Vector2(0.5, 0.25) },
    };
    const m = new THREE.ShaderMaterial({
      uniforms: this.uniforms, transparent: true, depthWrite: false,
      vertexShader: /* glsl */`
        attribute float aRnd; uniform float uTime, uScale; uniform vec3 uCam, uBox; uniform vec2 uWind; varying float vA;
        void main() {
          float fall = 0.7 + aRnd * 0.6;
          vec3 p = position;
          p.y -= uTime * fall;
          p.x += uTime * uWind.x + sin(uTime * (0.6 + aRnd) + aRnd * 40.0) * 0.5;
          p.z += uTime * uWind.y + cos(uTime * (0.5 + aRnd) + aRnd * 17.0) * 0.5;
          p = mod(p - uCam + uBox * 0.5, uBox) + uCam - uBox * 0.5;
          vec4 mv = modelViewMatrix * vec4(p, 1.0);
          gl_Position = projectionMatrix * mv;
          float d = -mv.z;
          gl_PointSize = clamp(uScale * (0.03 + aRnd * 0.03) / d, 0.0, 40.0);
          vA = smoothstep(0.3, 1.5, d) * (1.0 - smoothstep(22.0, 34.0, d));
        }`,
      fragmentShader: /* glsl */`
        uniform sampler2D uMap; uniform vec3 uColor; varying float vA;
        void main() { vec4 t = texture2D(uMap, gl_PointCoord); gl_FragColor = vec4(uColor, t.a * vA * 0.9); if (gl_FragColor.a < 0.01) discard; }`,
    });
    this.points = new THREE.Points(g, m);
    this.points.frustumCulled = false; this.points.userData.noAO = true; this.points.renderOrder = 5;
    this.points.name = 'Snowfall';
  }
  setCount(n) { this.points.geometry.setDrawRange(0, n); }
  update(dt, camera, heightPx) {
    this.uniforms.uTime.value += dt;
    this.uniforms.uCam.value.copy(camera.position);
    const f = heightPx / (2 * Math.tan(THREE.MathUtils.degToRad(camera.fov) / 2));
    this.uniforms.uScale.value = f;
  }
}

// CPU particle pool for puffs / spray (soft sprites with per-particle size and alpha)
export class Puffs {
  constructor(max = 260) {
    this.max = max; this.n = 0;
    this.p = new Float32Array(max * 3); this.v = new Float32Array(max * 3); this.life = new Float32Array(max); this.age = new Float32Array(max);
    this.size0 = new Float32Array(max); this.grow = new Float32Array(max); this.alpha0 = new Float32Array(max); this.drag = new Float32Array(max); this.grav = new Float32Array(max);
    const g = new THREE.BufferGeometry();
    this.aPos = new THREE.BufferAttribute(new Float32Array(max * 3), 3).setUsage(THREE.DynamicDrawUsage);
    this.aSize = new THREE.BufferAttribute(new Float32Array(max), 1).setUsage(THREE.DynamicDrawUsage);
    this.aAlpha = new THREE.BufferAttribute(new Float32Array(max), 1).setUsage(THREE.DynamicDrawUsage);
    g.setAttribute('position', this.aPos); g.setAttribute('aSize', this.aSize); g.setAttribute('aAlpha', this.aAlpha);
    this.uniforms = { uMap: { value: flakeTex() }, uScale: { value: 400 }, uColor: { value: new THREE.Color(0.95, 0.96, 1.0) } };
    const m = new THREE.ShaderMaterial({
      uniforms: this.uniforms, transparent: true, depthWrite: false,
      vertexShader: /* glsl */`attribute float aSize, aAlpha; uniform float uScale; varying float vA;
        void main() { vec4 mv = modelViewMatrix * vec4(position, 1.0); gl_Position = projectionMatrix * mv; gl_PointSize = clamp(uScale * aSize / -mv.z, 0.0, 256.0); vA = aAlpha; }`,
      fragmentShader: /* glsl */`uniform sampler2D uMap; uniform vec3 uColor; varying float vA;
        void main() { float a = texture2D(uMap, gl_PointCoord).a * vA; if (a < 0.005) discard; gl_FragColor = vec4(uColor, a); }`,
    });
    this.points = new THREE.Points(g, m);
    this.points.frustumCulled = false; this.points.userData.noAO = true; this.points.renderOrder = 6;
    this.points.name = 'Puffs';
    g.setDrawRange(0, 0);
  }
  emit(pos, vel, { life = 1.2, size = 0.15, grow = 0.4, alpha = 0.5, drag = 1.5, grav = 0, jitter = 0.3 } = {}) {
    let i = this.n < this.max ? this.n++ : Math.floor(Math.random() * this.max);
    this.p.set([pos.x, pos.y, pos.z], i * 3);
    this.v.set([vel.x + (Math.random() - 0.5) * jitter, vel.y + (Math.random() - 0.5) * jitter, vel.z + (Math.random() - 0.5) * jitter], i * 3);
    this.life[i] = life * (0.8 + Math.random() * 0.4); this.age[i] = 0; this.size0[i] = size; this.grow[i] = grow; this.alpha0[i] = alpha; this.drag[i] = drag; this.grav[i] = grav;
  }
  update(dt, camera, heightPx) {
    this.uniforms.uScale.value = heightPx / (2 * Math.tan(THREE.MathUtils.degToRad(camera.fov) / 2));
    let w = 0;
    const P = this.aPos.array, S = this.aSize.array, A = this.aAlpha.array;
    for (let i = 0; i < this.n; i++) {
      this.age[i] += dt;
      if (this.age[i] >= this.life[i]) continue;
      const k = Math.exp(-this.drag[i] * dt);
      this.v[i * 3] *= k; this.v[i * 3 + 1] = this.v[i * 3 + 1] * k - this.grav[i] * dt; this.v[i * 3 + 2] *= k;
      for (let c = 0; c < 3; c++) this.p[i * 3 + c] += this.v[i * 3 + c] * dt;
      const f = this.age[i] / this.life[i];
      // compact live particles to the front of the draw buffers
      P[w * 3] = this.p[i * 3]; P[w * 3 + 1] = this.p[i * 3 + 1]; P[w * 3 + 2] = this.p[i * 3 + 2];
      S[w] = this.size0[i] + this.grow[i] * f;
      A[w] = this.alpha0[i] * (1 - f) * Math.min(1, this.age[i] * 8);
      w++;
    }
    this.points.geometry.setDrawRange(0, w);
    this.aPos.needsUpdate = this.aSize.needsUpdate = this.aAlpha.needsUpdate = true;
    // drop dead particles at the end of the pool
    while (this.n > 0 && this.age[this.n - 1] >= this.life[this.n - 1]) this.n--;
  }
}

// Ribbon decal following a moving point on the snow (sled track); ring buffer of cross-sections
export class Trail {
  constructor(max = 600, width = 0.56, color = 0x9aa4b4) {
    this.max = max; this.width = width; this.count = 0; this.head = 0; this.last = null;
    const pos = new Float32Array(max * 2 * 3), alpha = new Float32Array(max * 2);
    const idx = [];
    for (let i = 0; i < max - 1; i++) { const a = i * 2; idx.push(a, a + 2, a + 1, a + 1, a + 2, a + 3); }
    const g = new THREE.BufferGeometry();
    this.aPos = new THREE.BufferAttribute(pos, 3).setUsage(THREE.DynamicDrawUsage);
    this.aAlpha = new THREE.BufferAttribute(alpha, 1).setUsage(THREE.DynamicDrawUsage);
    g.setAttribute('position', this.aPos); g.setAttribute('aAlpha', this.aAlpha); g.setIndex(idx);
    const m = new THREE.MeshStandardMaterial({ color, roughness: 0.35, metalness: 0, transparent: true, depthWrite: false, polygonOffset: true, polygonOffsetFactor: -2, polygonOffsetUnits: -2 });
    m.onBeforeCompile = (sh) => {
      sh.vertexShader = sh.vertexShader.replace('#include <common>', '#include <common>\nattribute float aAlpha; varying float vTA;').replace('#include <begin_vertex>', '#include <begin_vertex>\nvTA = aAlpha;');
      sh.fragmentShader = sh.fragmentShader.replace('#include <common>', '#include <common>\nvarying float vTA;').replace('#include <color_fragment>', '#include <color_fragment>\ndiffuseColor.a *= vTA;');
    };
    m.customProgramCacheKey = () => 'cc-trail';
    this.mesh = new THREE.Mesh(g, m);
    this.mesh.frustumCulled = false; this.mesh.userData.noAO = true; this.mesh.renderOrder = 2; this.mesh.name = 'SledTrail';
    g.setDrawRange(0, 0);
  }
  clear() { this.count = 0; this.last = null; this.mesh.geometry.setDrawRange(0, 0); }
  break() { this.last = null; }
  // p: world point on the ground, dir: horizontal heading vector, n: ground normal
  add(p, dir, n, strength = 1) {
    if (this.last && this.last.distanceToSquared(p) < 0.09) return;
    if (this.count >= this.max) {
      // shift (keep it simple: drop the oldest half)
      const P = this.aPos.array, A = this.aAlpha.array, half = Math.floor(this.max / 2);
      P.copyWithin(0, half * 6); A.copyWithin(0, half * 2); this.count -= half;
    }
    const side = new THREE.Vector3().crossVectors(n, dir).normalize().multiplyScalar(this.width / 2);
    const i = this.count++;
    const P = this.aPos.array, A = this.aAlpha.array;
    const lift = 0.025;
    P.set([p.x + side.x, p.y + lift, p.z + side.z, p.x - side.x, p.y + lift, p.z - side.z], i * 6);
    const a = this.last ? 0.55 * strength : 0;      // a gap starts transparent
    A[i * 2] = a; A[i * 2 + 1] = a;
    this.last = p.clone();
    this.aPos.needsUpdate = this.aAlpha.needsUpdate = true;
    this.mesh.geometry.setDrawRange(0, Math.max(0, (this.count - 1) * 6));
  }
}

// boot prints (winter walking): instanced dark ellipses, ring buffer
export class Footprints {
  constructor(max = 360) {
    this.max = max; this.i = 0; this.side = 1; this.last = null;
    const g = new THREE.PlaneGeometry(0.13, 0.3); g.rotateX(-Math.PI / 2);
    const m = new THREE.MeshStandardMaterial({ color: 0x8d97a8, roughness: 0.5, transparent: true, opacity: 0.55, depthWrite: false, polygonOffset: true, polygonOffsetFactor: -2, polygonOffsetUnits: -2 });
    m.onBeforeCompile = (sh) => {
      sh.vertexShader = sh.vertexShader.replace('#include <common>', '#include <common>\nvarying vec2 vFp;').replace('#include <uv_vertex>', '#include <uv_vertex>\nvFp = uv;');
      sh.fragmentShader = sh.fragmentShader.replace('#include <common>', '#include <common>\nvarying vec2 vFp;').replace('#include <color_fragment>', `#include <color_fragment>
vec2 q = vFp * 2.0 - 1.0; q.y *= 1.0; float sole = 1.0 - smoothstep(0.75, 1.0, length(vec2(q.x * (1.0 + 0.25 * q.y), q.y)));
diffuseColor.a *= sole;`);
    };
    m.customProgramCacheKey = () => 'cc-foot';
    this.mesh = new THREE.InstancedMesh(g, m, max);
    this.mesh.count = 0; this.mesh.frustumCulled = false; this.mesh.userData.noAO = true; this.mesh.name = 'Footprints';
    this.M = new THREE.Matrix4();
  }
  clear() { this.mesh.count = 0; this.i = 0; this.last = null; }
  step(pos, facing, n) {
    if (this.last && Math.hypot(pos.x - this.last.x, pos.z - this.last.z) < 0.68) return;
    this.last = pos.clone();
    this.side = -this.side;
    const off = new THREE.Vector3(Math.cos(facing), 0, -Math.sin(facing)).multiplyScalar(0.11 * this.side);
    const q = new THREE.Quaternion().setFromUnitVectors(new THREE.Vector3(0, 1, 0), n).multiply(new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 1, 0), facing));
    this.M.compose(new THREE.Vector3(pos.x + off.x, pos.y + 0.02, pos.z + off.z), q, new THREE.Vector3(1, 1, 1));
    this.mesh.setMatrixAt(this.i % this.max, this.M);
    this.i++;
    this.mesh.count = Math.min(this.i, this.max);
    this.mesh.instanceMatrix.needsUpdate = true;
  }
}
