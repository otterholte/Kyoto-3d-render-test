// Sky dome (gradient lavender-blue with warm horizon, sun glow, painted Higashiyama hills to the east)
// and the time-of-day controller: t = 0 golden hour ... t = 1 blue hour.
import * as THREE from 'three';
import { SUN_AZIMUTH } from './config.js';
import { shared } from './materials.js';

const SKY_VERT = /* glsl */`
varying vec3 vDir;
void main() {
  vDir = normalize( position );
  vec4 p = projectionMatrix * modelViewMatrix * vec4( position, 1.0 );
  gl_Position = p.xyww;
}`;
const SKY_FRAG = /* glsl */`
uniform vec3 uTop, uMid, uHorizon, uWarm, uSunDir, uSunCol, uHill, uHillFar;
uniform float uSunSize, uStars, uGlow;
varying vec3 vDir;
float h1( float x ) { return fract( sin( x * 127.1 ) * 43758.5453 ); }
float n1( float x ) { float i = floor( x ), f = fract( x ); f = f * f * ( 3.0 - 2.0 * f ); return mix( h1( i ), h1( i + 1.0 ), f ); }
float hash3( vec3 p ) { p = fract( p * 0.3183099 + 0.1 ); p *= 17.0; return fract( p.x * p.y * p.z * ( p.x + p.y + p.z ) ); }
void main() {
  vec3 d = normalize( vDir );
  float y = d.y;
  float az = atan( d.x, -d.z );           // 0 = north, +pi/2 = east
  // vertical gradient: warm horizon -> lavender -> deep blue zenith
  vec3 c = mix( uHorizon, uMid, smoothstep( -0.02, 0.22, y ) );
  c = mix( c, uTop, smoothstep( 0.18, 0.85, y ) );
  // warm glow toward the sun, strongest at the horizon
  float sd = max( dot( d, normalize( uSunDir ) ), 0.0 );
  float hb = exp( -max( y, 0.0 ) * 6.0 );
  c += uWarm * ( pow( sd, 6.0 ) * 0.55 + pow( sd, 2.0 ) * 0.18 ) * ( 0.35 + 0.65 * hb ) * uGlow;
  // sun disc + halo
  c += uSunCol * ( smoothstep( 1.0 - uSunSize, 1.0 - uSunSize * 0.6, sd ) * 6.0 + pow( sd, 600.0 ) * 2.0 );
  // faint stars at blue hour
  if ( uStars > 0.0 && y > 0.08 ) {
    vec3 sp = floor( d * 340.0 );
    float s = step( 0.9975, hash3( sp ) ) * smoothstep( 0.08, 0.5, y );
    c += vec3( s * uStars );
  }
  // painted ridgelines (artistic): Higashiyama hills rise to the east, low far hills elsewhere
  float east = smoothstep( 1.9, 0.2, abs( az - 1.57 ) );
  float ridgeFar = 0.018 + 0.022 * n1( az * 5.0 + 3.0 ) + 0.012 * n1( az * 13.0 );
  float ridge = 0.01 + east * ( 0.06 + 0.035 * n1( az * 7.0 ) + 0.015 * n1( az * 23.0 ) );
  if ( y < ridgeFar ) c = mix( c, uHillFar, 0.75 * smoothstep( ridgeFar, ridgeFar - 0.004, y ) );
  if ( y < ridge ) c = mix( c, uHill, smoothstep( ridge, ridge - 0.004, y ) * ( 0.55 + 0.4 * east ) );
  if ( y < 0.0 ) c = mix( c, uHill * 0.9, smoothstep( 0.0, -0.05, y ) );
  gl_FragColor = vec4( c, 1.0 );
  #include <tonemapping_fragment>
  #include <colorspace_fragment>
}`;

// keyframes along t (linear-ish colours in three's working space)
const K = [
  { t: 0.0, el: 13, sun: [1.0, 0.74, 0.5], sunI: 3.0, hemiSky: [0.55, 0.62, 0.9], hemiGround: [0.58, 0.44, 0.32], hemiI: 1.9,
    top: [0.18, 0.28, 0.58], mid: [0.52, 0.55, 0.78], hor: [1.0, 0.72, 0.5], warm: [1.0, 0.55, 0.25], fog: [0.78, 0.68, 0.62],
    fogD: 0.0038, lan: 0.6, wet: 0.12, exp: 1.0, stars: 0, hill: [0.42, 0.40, 0.52], hillFar: [0.62, 0.56, 0.62], glow: 1.0 },
  { t: 0.5, el: 3, sun: [1.0, 0.5, 0.26], sunI: 1.7, hemiSky: [0.5, 0.5, 0.82], hemiGround: [0.5, 0.36, 0.32], hemiI: 1.65,
    top: [0.14, 0.18, 0.45], mid: [0.48, 0.42, 0.66], hor: [1.0, 0.55, 0.36], warm: [1.0, 0.42, 0.22], fog: [0.62, 0.5, 0.55],
    fogD: 0.0045, lan: 1.6, wet: 0.35, exp: 1.08, stars: 0, hill: [0.30, 0.27, 0.42], hillFar: [0.5, 0.42, 0.55], glow: 1.0 },
  { t: 1.0, el: -5, sun: [0.42, 0.5, 0.85], sunI: 0.45, hemiSky: [0.32, 0.38, 0.72], hemiGround: [0.24, 0.2, 0.26], hemiI: 1.35,
    top: [0.035, 0.06, 0.2], mid: [0.15, 0.17, 0.4], hor: [0.55, 0.42, 0.55], warm: [0.75, 0.38, 0.32], fog: [0.2, 0.22, 0.36],
    fogD: 0.005, lan: 3.4, wet: 0.65, exp: 1.25, stars: 0.6, hill: [0.08, 0.09, 0.18], hillFar: [0.16, 0.16, 0.3], glow: 0.55 },
];
const lerp = (a, b, f) => a + (b - a) * f;
function sample(t) {
  let i = 0;
  while (i < K.length - 2 && t > K[i + 1].t) i++;
  const a = K[i], b = K[i + 1];
  const f = THREE.MathUtils.clamp((t - a.t) / (b.t - a.t), 0, 1);
  const s = (f * f) * (3 - 2 * f);
  const o = {};
  for (const k of Object.keys(a)) o[k] = Array.isArray(a[k]) ? a[k].map((v, j) => lerp(v, b[k][j], s)) : lerp(a[k], b[k], s);
  return o;
}

export class Sky {
  constructor(renderer, scene) {
    this.renderer = renderer;
    this.scene = scene;
    this.uniforms = {
      uTop: { value: new THREE.Color() }, uMid: { value: new THREE.Color() }, uHorizon: { value: new THREE.Color() },
      uWarm: { value: new THREE.Color() }, uSunDir: { value: new THREE.Vector3(0, 1, 0) }, uSunCol: { value: new THREE.Color() },
      uSunSize: { value: 0.0009 }, uStars: { value: 0 }, uHill: { value: new THREE.Color() }, uHillFar: { value: new THREE.Color() },
      uGlow: { value: 1 },
    };
    const mat = new THREE.ShaderMaterial({ vertexShader: SKY_VERT, fragmentShader: SKY_FRAG, uniforms: this.uniforms,
      side: THREE.BackSide, depthWrite: false, fog: false });
    this.mesh = new THREE.Mesh(new THREE.SphereGeometry(900, 48, 24), mat);
    this.mesh.frustumCulled = false;
    this.mesh.renderOrder = -10;
    scene.add(this.mesh);

    // env scene for PMREM (sky only)
    this.envScene = new THREE.Scene();
    this.envMesh = new THREE.Mesh(this.mesh.geometry, mat);
    this.envScene.add(this.envMesh);
    this.pmrem = new THREE.PMREMGenerator(renderer);
    this.envRT = null;

    this.sun = new THREE.DirectionalLight(0xffffff, 3);
    this.sun.castShadow = true;
    this.sun.shadow.bias = -0.0004;
    this.sun.shadow.normalBias = 0.04;
    this.sun.shadow.radius = 3;
    scene.add(this.sun, this.sun.target);
    this.hemi = new THREE.HemisphereLight(0xaab4e6, 0x6b5440, 0.8);
    scene.add(this.hemi);
    scene.fog = new THREE.Fog(0xffffff, 0.004, 0.035); // near = density, far = height falloff (see materials.js)
    this.sunDir = new THREE.Vector3();
    this.lightDir = new THREE.Vector3(0, 1, 0);
    this._s = { up: new THREE.Vector3(), right: new THREE.Vector3(), upL: new THREE.Vector3(), snapped: new THREE.Vector3(), last: new THREE.Vector3(NaN, 0, 0) };
    this.shadowDirty = true;
    this.params = null;
    this.t = -1;
    this.lanternIntensity = 1;
    this._envDirty = true;
    this._envTimer = 0;
  }

  setTime(t) {
    if (Math.abs(t - this.t) < 1e-4) return;
    this.t = t;
    const p = sample(t);
    this.params = p;
    const az = THREE.MathUtils.degToRad(SUN_AZIMUTH);
    const el = THREE.MathUtils.degToRad(p.el);
    // direction toward the sun: east = +x, north = -z
    this.sunDir.set(Math.sin(az) * Math.cos(el), Math.sin(el), -Math.cos(az) * Math.cos(el)).normalize();
    const u = this.uniforms;
    u.uTop.value.setRGB(...p.top); u.uMid.value.setRGB(...p.mid); u.uHorizon.value.setRGB(...p.hor);
    u.uWarm.value.setRGB(...p.warm); u.uSunDir.value.copy(this.sunDir);
    u.uSunCol.value.setRGB(...p.sun).multiplyScalar(p.el > -1 ? 1 : 0);
    u.uStars.value = p.stars; u.uHill.value.setRGB(...p.hill); u.uHillFar.value.setRGB(...p.hillFar); u.uGlow.value = p.glow;
    // light: below the horizon the key light becomes a soft cool sky fill from the same side
    const lightEl = Math.max(p.el, 7);
    const le = THREE.MathUtils.degToRad(lightEl);
    this.lightDir.set(Math.sin(az) * Math.cos(le), Math.sin(le), -Math.cos(az) * Math.cos(le)).normalize();
    this.sun.color.setRGB(...p.sun);
    this.sun.intensity = p.sunI;
    this.hemi.color.setRGB(...p.hemiSky);
    this.hemi.groundColor.setRGB(...p.hemiGround);
    this.hemi.intensity = p.hemiI;
    this.scene.fog.color.setRGB(...p.fog);
    this.scene.fog.near = p.fogD;
    this.scene.fog.far = 0.045;
    this.renderer.toneMappingExposure = p.exp;
    this.lanternIntensity = p.lan;
    shared.uWet.value = p.wet;
    shared.uWarm.value = 1 - t;
    this._envDirty = true;
    this._envTimer = 0.15;
    this.shadowDirty = true;
  }

  // follow the camera, refresh the PMREM env (debounced) when time changes
  update(dt, camera, groundMat) {
    this.mesh.position.copy(camera.position);
    if (this._envDirty) {
      this._envTimer -= dt;
      if (this._envTimer <= 0) {
        this._envDirty = false;
        const old = this.envRT;
        this.envRT = this.pmrem.fromScene(this.envScene, 0, 1, 1000);
        if (old) old.dispose();
        if (groundMat) {
          groundMat.envMap = this.envRT.texture;
          groundMat.envMapIntensity = 0.25 + 1.4 * this.params.wet;
          groundMat.needsUpdate = true;
        }
      }
    }
  }

  // tight shadow frustum that follows the player, snapped to texels to avoid shimmer.
  // Returns true when the shadow camera moved (the shadow map must be re-rendered).
  placeShadow(center, range, mapSize) {
    let changed = false;
    const L = this.sun;
    const cam = L.shadow.camera;
    if (cam.right !== range || L.shadow.mapSize.x !== mapSize) {
      cam.left = -range; cam.right = range; cam.top = range; cam.bottom = -range;
      cam.near = 1; cam.far = 420;
      cam.updateProjectionMatrix();
      changed = true;
      if (L.shadow.mapSize.x !== mapSize) {
        L.shadow.mapSize.set(mapSize, mapSize);
        if (L.shadow.map) { L.shadow.map.dispose(); L.shadow.map = null; }
      }
    }
    const texel = (2 * range) / mapSize;
    // snap in light space
    const d = this.lightDir;
    const { up, right, upL, snapped, last } = this._s;
    if (Math.abs(d.y) > 0.99) up.set(0, 0, 1); else up.set(0, 1, 0);
    right.crossVectors(up, d).normalize();
    upL.crossVectors(d, right).normalize();
    const cx = Math.round(center.dot(right) / texel) * texel;
    const cy = Math.round(center.dot(upL) / texel) * texel;
    // depth along the light only matters coarsely (near/far are generous): quantise to 1 m
    const cz = Math.round(center.dot(d));
    snapped.set(0, 0, 0).addScaledVector(right, cx).addScaledVector(upL, cy).addScaledVector(d, cz);
    if (!snapped.equals(last)) { changed = true; last.copy(snapped); }
    L.target.position.copy(snapped);
    L.position.copy(snapped).addScaledVector(d, 200);
    L.target.updateMatrixWorld();
    L.updateMatrixWorld();
    return changed;
  }
}
