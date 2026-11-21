// Sky dome (analytic gradient + Mie sun glow + procedural cloud deck), physically based sun (solar position for
// Bellingham + Kasten-Young airmass transmittance), hemisphere fill, PMREM image-based lighting, exponential fog,
// and a fogged ring of distant treeline (artistic backdrop hiding the edge of the data).
import * as THREE from 'three';
import { LAT, LON, SEASONS } from './config.js';
import { SU } from './shared.js';

const rad = THREE.MathUtils.degToRad, deg = THREE.MathUtils.radToDeg;

// NOAA-style low-precision solar position. Returns {alt, az} in degrees (az clockwise from north).
export function solarPosition(ms, lat = LAT, lon = LON) {
  const d = ms / 86400000 + 2440587.5 - 2451545.0;
  const g = rad((357.529 + 0.98560028 * d) % 360);
  const q = (280.459 + 0.98564736 * d) % 360;
  const L = rad(q + 1.915 * Math.sin(g) + 0.02 * Math.sin(2 * g));
  const e = rad(23.439 - 0.00000036 * d);
  const ra = Math.atan2(Math.cos(e) * Math.sin(L), Math.cos(L));
  const dec = Math.asin(Math.sin(e) * Math.sin(L));
  const gmst = (18.697374558 + 24.06570982441908 * d) % 24;
  const ha = rad(gmst * 15 + lon) - ra;
  const la = rad(lat);
  const alt = Math.asin(Math.sin(la) * Math.sin(dec) + Math.cos(la) * Math.cos(dec) * Math.cos(ha));
  const az = Math.atan2(-Math.sin(ha), Math.tan(dec) * Math.cos(la) - Math.sin(la) * Math.cos(ha));
  return { alt: deg(alt), az: (deg(az) + 360) % 360 };
}

function sunLight(alt) {
  const a = Math.max(alt, 0.5);
  const m = 1 / (Math.sin(rad(a)) + 0.50572 * Math.pow(a + 6.07995, -1.6364));
  const tau = [0.1, 0.17, 0.32];
  const T = tau.map((k) => Math.exp(-k * m));
  const mx = Math.max(...T);
  return { col: T.map((v) => v / mx), illum: 4.4 * mx * THREE.MathUtils.smoothstep(alt, -1, 3) };
}

const SKY_VERT = /* glsl */`
varying vec3 vDir;
void main() {
  vDir = normalize(position);
  vec4 p = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
  gl_Position = p.xyww;
}`;
const SKY_FRAG = /* glsl */`
uniform vec3 uZenith, uHorizon, uGround, uSunDir, uSunCol, uCloudCol;
uniform float uHaze, uClouds, uOvercast, uTime, uSunVis;
varying vec3 vDir;
float h2(vec2 p) { p = fract(p * vec2(234.34, 435.345)); p += dot(p, p + 34.23); return fract(p.x * p.y); }
float vn(vec2 p) { vec2 i = floor(p), f = fract(p); f = f * f * (3.0 - 2.0 * f);
  return mix(mix(h2(i), h2(i + vec2(1, 0)), f.x), mix(h2(i + vec2(0, 1)), h2(i + vec2(1, 1)), f.x), f.y); }
float fbm(vec2 p) { float s = 0.0, a = 0.5; for (int i = 0; i < 5; i++) { s += a * vn(p); p = p * 2.03 + 17.1; a *= 0.5; } return s; }
void main() {
  vec3 d = normalize(vDir);
  float y = d.y;
  vec3 c = mix(uHorizon, uZenith, pow(smoothstep(-0.02, 1.0, y), 0.55));
  float sd = max(dot(d, uSunDir), 0.0);
  // Mie forward glow + horizon haze brightening
  c += uSunCol * (pow(sd, 8.0) * 0.35 + pow(sd, 64.0) * 0.6) * uHaze * uSunVis;
  c = mix(c, uHorizon * 1.05, exp(-max(y, 0.0) * 9.0) * uHaze * 0.6);
  // sun disc (hidden by overcast)
  c += uSunCol * smoothstep(0.99985, 0.99993, sd) * 30.0 * (1.0 - uOvercast) * uSunVis;
  // cloud deck: plane projection
  if (y > 0.0) {
    vec2 uv = d.xz / (y + 0.08) * 1.6 + vec2(uTime * 0.004, uTime * 0.0015);
    float n = fbm(uv * 0.9);
    float cov = mix(0.62 - uClouds * 0.4, 0.0, uOvercast);
    float cl = smoothstep(cov, cov + 0.28, n);
    float shade = 0.75 + 0.35 * fbm(uv * 1.7 + 3.0);
    vec3 cc = uCloudCol * shade;
    cc += uSunCol * pow(sd, 6.0) * 0.5 * (1.0 - uOvercast) * uSunVis;   // silver lining toward the sun
    if (uOvercast > 0.5) { cc = mix(uCloudCol * (0.82 + 0.3 * n), uCloudCol, 0.4); cl = 1.0; cc += uSunCol * pow(sd, 3.0) * 0.25 * uSunVis; }
    float fade = smoothstep(0.0, 0.12, y);
    c = mix(c, cc, cl * fade * (uOvercast > 0.5 ? 0.92 : 0.9));
  } else {
    c = mix(uHorizon, uGround, smoothstep(0.0, -0.15, y));
  }
  gl_FragColor = vec4(c, 1.0);
  #include <tonemapping_fragment>
  #include <colorspace_fragment>
}`;

export class Sky {
  constructor(renderer, scene) {
    this.renderer = renderer; this.scene = scene;
    this.uniforms = {
      uZenith: { value: new THREE.Color() }, uHorizon: { value: new THREE.Color() }, uGround: { value: new THREE.Color() },
      uSunDir: { value: new THREE.Vector3(0, 1, 0) }, uSunCol: { value: new THREE.Color() }, uCloudCol: { value: new THREE.Color() },
      uHaze: { value: 0.4 }, uClouds: { value: 0.3 }, uOvercast: { value: 0 }, uTime: { value: 0 }, uSunVis: { value: 1 },
    };
    const mat = new THREE.ShaderMaterial({ vertexShader: SKY_VERT, fragmentShader: SKY_FRAG, uniforms: this.uniforms, side: THREE.BackSide, depthWrite: false, fog: false });
    this.mesh = new THREE.Mesh(new THREE.SphereGeometry(1500, 48, 24), mat);
    this.mesh.frustumCulled = false; this.mesh.renderOrder = -10; this.mesh.userData.noAO = true;
    scene.add(this.mesh);
    this.envScene = new THREE.Scene();
    this.envScene.add(new THREE.Mesh(this.mesh.geometry, mat));
    this.pmrem = new THREE.PMREMGenerator(renderer);
    this.envRT = null;

    this.sun = new THREE.DirectionalLight(0xffffff, 3);
    this.sun.castShadow = true;
    this.sun.shadow.bias = -0.0003;
    this.sun.shadow.normalBias = 0.035;
    this.sun.shadow.radius = 3;
    scene.add(this.sun, this.sun.target);
    this.hemi = new THREE.HemisphereLight(0xb8c8e8, 0x5a5040, 0.6);
    scene.add(this.hemi);
    scene.fog = new THREE.FogExp2(0xc8d0dc, 0.002);
    this.sunDir = new THREE.Vector3();
    this.lightDir = new THREE.Vector3();
    this._s = { up: new THREE.Vector3(), right: new THREE.Vector3(), upL: new THREE.Vector3(), snapped: new THREE.Vector3(), last: new THREE.Vector3(NaN, 0, 0) };
    this.shadowDirty = true;
    this._envDirty = true;
    this.season = null;
    this.blend = 0;                      // 0 summer .. 1 winter (for transitions)
  }

  setSeason(name) {
    const S = SEASONS[name];
    this.season = name;
    const sp = solarPosition(S.date);
    this.solar = sp;
    const az = rad(sp.az), el = rad(sp.alt);
    this.sunDir.set(Math.sin(az) * Math.cos(el), Math.sin(el), -Math.cos(az) * Math.cos(el)).normalize();
    const le = rad(Math.max(sp.alt, 8));
    this.lightDir.set(Math.sin(az) * Math.cos(le), Math.sin(le), -Math.cos(az) * Math.cos(le)).normalize();
    const L = sunLight(sp.alt);
    const u = this.uniforms;
    u.uZenith.value.setRGB(...S.sky.zenith); u.uHorizon.value.setRGB(...S.sky.horizon); u.uGround.value.setRGB(...S.sky.ground);
    u.uSunDir.value.copy(this.sunDir); u.uSunCol.value.setRGB(...L.col).multiplyScalar(1.0);
    u.uCloudCol.value.setRGB(...S.sky.cloudCol);
    u.uHaze.value = S.sky.haze; u.uClouds.value = S.sky.clouds; u.uOvercast.value = S.sky.overcast;
    u.uSunVis.value = S.sky.overcast ? 0.6 : 1;
    this.sun.color.setRGB(...L.col);
    if (S.sky.overcast) this.sun.color.lerp(new THREE.Color(0.85, 0.88, 0.95), 0.5);
    this.sun.intensity = L.illum * S.sunScale;
    if ('intensity' in this.sun.shadow) this.sun.shadow.intensity = S.shadowDark;
    this.sun.shadow.radius = S.sky.overcast ? 6 : 2.5;
    this.hemi.color.setRGB(...S.sky.zenith).lerp(new THREE.Color(1, 1, 1), 0.35);
    this.hemi.groundColor.setRGB(...(name === 'winter' ? [0.75, 0.77, 0.8] : [0.32, 0.3, 0.22]));
    this.hemi.intensity = S.hemiI * 0.6;
    this.scene.environmentIntensity = S.envI;
    this.scene.fog.color.setRGB(...S.fog);
    this.scene.fog.density = S.fogD;
    this.renderer.toneMappingExposure = S.exposure;
    SU.uSunDirW.value.copy(this.sunDir);
    this._envDirty = true;
    this.shadowDirty = true;
    this.params = S;
  }

  update(dt, camera) {
    this.mesh.position.copy(camera.position);
    this.uniforms.uTime.value += dt;
    if (this._envDirty) {
      this._envDirty = false;
      const old = this.envRT;
      this.envRT = this.pmrem.fromScene(this.envScene, 0, 1, 2000);
      if (old) old.dispose();
      this.scene.environment = this.envRT.texture;
    }
  }

  // tight shadow frustum around the player, snapped to texels (from the Kyoto explorer). Returns true if it moved.
  placeShadow(center, range, mapSize) {
    let changed = false;
    const L = this.sun, cam = L.shadow.camera;
    if (cam.right !== range || L.shadow.mapSize.x !== mapSize) {
      cam.left = -range; cam.right = range; cam.top = range; cam.bottom = -range;
      cam.near = 1; cam.far = 500;
      cam.updateProjectionMatrix();
      changed = true;
      if (L.shadow.mapSize.x !== mapSize) {
        L.shadow.mapSize.set(mapSize, mapSize);
        if (L.shadow.map) { L.shadow.map.dispose(); L.shadow.map = null; }
      }
    }
    const texel = (2 * range) / mapSize;
    const d = this.lightDir;
    const { up, right, upL, snapped, last } = this._s;
    if (Math.abs(d.y) > 0.99) up.set(0, 0, 1); else up.set(0, 1, 0);
    right.crossVectors(up, d).normalize();
    upL.crossVectors(d, right).normalize();
    const cx = Math.round(center.dot(right) / texel) * texel;
    const cy = Math.round(center.dot(upL) / texel) * texel;
    const cz = Math.round(center.dot(d));
    snapped.set(0, 0, 0).addScaledVector(right, cx).addScaledVector(upL, cy).addScaledVector(d, cz);
    if (!snapped.equals(last)) { changed = true; last.copy(snapped); }
    L.target.position.copy(snapped);
    L.position.copy(snapped).addScaledVector(d, 250);
    L.target.updateMatrixWorld(); L.updateMatrixWorld();
    return changed;
  }
}

// distant treeline ring (artistic): jagged conifer silhouettes beyond the data box, fogged
export function buildTreeline(terrain, center = [-50, -25]) {
  const R0 = 300, segs = 720;
  const pos = [], col = [], idx = [];
  let s = 7;
  const rnd = () => { s = (s * 16807) % 2147483647; return s / 2147483647; };
  for (let i = 0; i <= segs; i++) {
    const a = (i / segs) * Math.PI * 2;
    const R = R0 + 40 * Math.sin(a * 3 + 1) + 25 * Math.sin(a * 7);
    const x = center[0] + Math.cos(a) * R, y = center[1] + Math.sin(a) * R;
    const ex = Math.max(terrain.x0 + 1, Math.min(terrain.x1 - 1, x)), ey = Math.max(terrain.y0 + 1, Math.min(terrain.y1 - 1, y));
    const base = terrain.height(ex, ey) + (x - ex) * 0.0 - 4;
    // conifer spikes: alternate tip / notch vertices
    const tip = i % 2 === 0;
    const h = tip ? 22 + rnd() * 20 + 8 * Math.sin(a * 5) : 12 + rnd() * 8;
    pos.push(x, base - 30, -y, x, base + h, -y);
    const k = 0.75 + rnd() * 0.3;
    col.push(0.03 * k, 0.05 * k, 0.035 * k, 0.04 * k, 0.065 * k, 0.04 * k);
    if (i < segs) { const p = i * 2; idx.push(p, p + 2, p + 1, p + 1, p + 2, p + 3); }
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
  g.setAttribute('color', new THREE.Float32BufferAttribute(col, 3));
  g.setIndex(idx); g.computeVertexNormals();
  const m = new THREE.MeshLambertMaterial({ vertexColors: true, side: THREE.DoubleSide });
  m.name = 'CC_Treeline';
  m.onBeforeCompile = (sh) => {
    sh.uniforms.uSeason = SU.uSeason;
    sh.fragmentShader = sh.fragmentShader.replace('#include <common>', '#include <common>\nuniform float uSeason;')
      .replace('#include <color_fragment>', '#include <color_fragment>\ndiffuseColor.rgb = mix(diffuseColor.rgb, diffuseColor.rgb * 1.6 + vec3(0.18, 0.19, 0.21), uSeason * 0.55);');
  };
  const mesh = new THREE.Mesh(g, m);
  mesh.name = 'Treeline'; mesh.userData.noAO = true;
  return mesh;
}
