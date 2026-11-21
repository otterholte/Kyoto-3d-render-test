// Terrain: the 0.5 m DTM (3DEP bare earth) as a height sampler + a render/collision mesh (tensor grid: 1 m in the
// core, coarser outside, plus a far skirt) and the placeholder ground material (surface classes + procedural detail,
// summer lawn/asphalt/concrete or winter snow with sparkle and a packed sled track).
import * as THREE from 'three';
import { loadText } from './util.js';
import { SU } from './shared.js';

export class Terrain {
  constructor(meta, u16) {
    this.meta = meta;
    this.W = meta.width; this.H = meta.height; this.res = meta.res;
    [this.x0, this.y0, this.x1, this.y1] = meta.bounds;
    const k = (meta.zMax - meta.zMin) / 65535;
    this.z = new Float32Array(u16.length);
    for (let i = 0; i < u16.length; i++) this.z[i] = meta.zMin + u16[i] * k;
  }

  // NAVD88 height at local (x east, y north), bilinear, clamped to the raster
  height(x, y) {
    const fc = (x - this.x0) / this.res - 0.5, fr = (this.y1 - y) / this.res - 0.5;
    const c = Math.max(0, Math.min(this.W - 1.001, fc)), r = Math.max(0, Math.min(this.H - 1.001, fr));
    const c0 = Math.floor(c), r0 = Math.floor(r), tx = c - c0, ty = r - r0;
    const i = r0 * this.W + c0, z = this.z;
    return (z[i] * (1 - tx) + z[i + 1] * tx) * (1 - ty) + (z[i + this.W] * (1 - tx) + z[i + this.W + 1] * tx) * ty;
  }

  // world-space (three.js) normal at local (x, y) from central differences over `d` metres
  normal(x, y, d = 0.75, out = new THREE.Vector3()) {
    const dx = (this.height(x + d, y) - this.height(x - d, y)) / (2 * d);
    const dy = (this.height(x, y + d) - this.height(x, y - d)) / (2 * d);
    // three: x = east, y = up, z = -north  => dh/dz = -dy
    return out.set(-dx, 1, dy).normalize();
  }

  // tensor-grid mesh: fine spacing inside [fx0,fx1]x[fy0,fy1] (local), coarse outside, skirt ring beyond the raster
  buildGeometry({ fine = 1.0, coarse = 3.0, focus = [-180, -128, 80, 82], skirt = 900 } = {}) {
    const axis = (a0, a1, f0, f1) => {
      const v = [];
      let t = a0 + 0.3;
      v.push(a0 - skirt);
      while (t < a1 - 0.3) {
        v.push(t);
        const inFine = t >= f0 && t < f1;
        t += inFine ? fine : coarse;
        if (!inFine && t > f0 && v[v.length - 1] < f0) t = f0;
      }
      v.push(a1 - 0.3);
      v.push(a1 + skirt);
      return v;
    };
    const xs = axis(this.x0, this.x1, focus[0], focus[2]);
    const ys = axis(this.y0, this.y1, focus[1], focus[3]);
    const nx = xs.length, ny = ys.length;
    const pos = new Float32Array(nx * ny * 3), nrm = new Float32Array(nx * ny * 3);
    const n = new THREE.Vector3();
    for (let j = 0; j < ny; j++) {
      for (let i = 0; i < nx; i++) {
        const x = xs[i], y = ys[j];
        const edge = i === 0 || j === 0 || i === nx - 1 || j === ny - 1;
        const cx = Math.max(this.x0 + 0.3, Math.min(this.x1 - 0.3, x)), cy = Math.max(this.y0 + 0.3, Math.min(this.y1 - 0.3, y));
        let h = this.height(cx, cy);
        if (edge) h -= 6;                       // skirt dips under the horizon fog
        const k = (j * nx + i) * 3;
        pos[k] = x; pos[k + 1] = h; pos[k + 2] = -y;
        if (edge) n.set(0, 1, 0); else this.normal(x, y, 0.75, n);
        nrm[k] = n.x; nrm[k + 1] = n.y; nrm[k + 2] = n.z;
      }
    }
    const idx = new Uint32Array((nx - 1) * (ny - 1) * 6);
    let q = 0;
    for (let j = 0; j < ny - 1; j++) {
      for (let i = 0; i < nx - 1; i++) {
        const a = j * nx + i, b = a + 1, c = a + nx, d = c + 1;
        // rows go north with j (three z decreases); keep CCW seen from above
        idx[q++] = a; idx[q++] = b; idx[q++] = c;
        idx[q++] = b; idx[q++] = d; idx[q++] = c;
      }
    }
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.BufferAttribute(pos, 3));
    g.setAttribute('normal', new THREE.BufferAttribute(nrm, 3));
    g.setIndex(new THREE.BufferAttribute(idx, 1));
    // winding check: first triangle normal must point up
    const p = (i) => new THREE.Vector3(pos[i * 3], pos[i * 3 + 1], pos[i * 3 + 2]);
    const t0 = new THREE.Triangle(p(idx[0]), p(idx[1]), p(idx[2]));
    const tn = t0.getNormal(new THREE.Vector3());
    if (tn.y < 0) { for (let i = 0; i < idx.length; i += 3) { const t = idx[i + 1]; idx[i + 1] = idx[i + 2]; idx[i + 2] = t; } }
    g.computeBoundingBox(); g.computeBoundingSphere();
    return g;
  }
}

export async function loadTerrain(manifest) {
  const txt = await loadText(manifest.terrain.file + '?v=' + encodeURIComponent(manifest.generated || ''));
  const bin = b64ToBytes(txt);
  const u16 = new Uint16Array(bin.buffer, bin.byteOffset, bin.byteLength / 2);   // little-endian (all browsers)
  return new Terrain(manifest.terrain, u16);
}

export function b64ToBytes(txt) {
  const s = txt.trim();
  if (typeof Uint8Array.fromBase64 === 'function') return Uint8Array.fromBase64(s);
  const bin = atob(s), out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

// ---------------------------------------------------------------- shared procedural noise texture
// RGBA tileable value noise at four frequencies (R fine ... A coarse); linear data, repeat wrapping, mipmapped.
let _noise = null;
export function noiseTexture() {
  if (_noise) return _noise;
  const N = 256, data = new Uint8Array(N * N * 4);
  const lattice = (f, seed) => {
    const g = new Float32Array(f * f);
    let s = seed;
    for (let i = 0; i < g.length; i++) { s = (s * 16807) % 2147483647; g[i] = s / 2147483647; }
    return g;
  };
  const freqs = [64, 32, 12, 5];
  const octs = freqs.map((f, k) => ({ f, g: lattice(f, 1234 + k * 977), g2: lattice(f * 2, 4321 + k * 131) }));
  const sample = (g, f, u, v) => {
    const x = u * f, y = v * f, x0 = Math.floor(x), y0 = Math.floor(y);
    let tx = x - x0, ty = y - y0; tx = tx * tx * (3 - 2 * tx); ty = ty * ty * (3 - 2 * ty);
    const at = (i, j) => g[((j % f + f) % f) * f + ((i % f + f) % f)];
    return (at(x0, y0) * (1 - tx) + at(x0 + 1, y0) * tx) * (1 - ty) + (at(x0, y0 + 1) * (1 - tx) + at(x0 + 1, y0 + 1) * tx) * ty;
  };
  for (let j = 0; j < N; j++) {
    for (let i = 0; i < N; i++) {
      const u = i / N, v = j / N;
      for (let k = 0; k < 4; k++) {
        const o = octs[k];
        const val = sample(o.g, o.f, u, v) * 0.68 + sample(o.g2, o.f * 2, u, v) * 0.32;
        data[(j * N + i) * 4 + k] = Math.round(val * 255);
      }
    }
  }
  const t = new THREE.DataTexture(data, N, N, THREE.RGBAFormat);
  t.wrapS = t.wrapT = THREE.RepeatWrapping;
  t.magFilter = THREE.LinearFilter; t.minFilter = THREE.LinearMipmapLinearFilter;
  t.generateMipmaps = true; t.anisotropy = 4;
  t.needsUpdate = true;
  _noise = t;
  return t;
}

// sled track mask (0..1) over the terrain raster: the run path drawn with a soft wide brush
export function trackTexture(terrain, path, width = 3.2) {
  const S = 2; // px per metre
  const W = Math.round((terrain.x1 - terrain.x0) * S), H = Math.round((terrain.y1 - terrain.y0) * S);
  const cv = document.createElement('canvas'); cv.width = W; cv.height = H;
  const g = cv.getContext('2d');
  g.fillStyle = '#000'; g.fillRect(0, 0, W, H);
  g.lineCap = 'round'; g.lineJoin = 'round';
  const px = ([x, y]) => [(x - terrain.x0) * S, (terrain.y1 - y) * S];
  g.filter = 'blur(3px)';
  for (const [w, a] of [[width * 1.6, 0.35], [width, 1]]) {
    g.strokeStyle = `rgba(255,255,255,${a})`; g.lineWidth = w * S;
    g.beginPath(); path.forEach((p, i) => { const [u, v] = px(p); if (i) g.lineTo(u, v); else g.moveTo(u, v); }); g.stroke();
  }
  const t = new THREE.CanvasTexture(cv);
  t.colorSpace = THREE.NoColorSpace;
  t.wrapS = t.wrapT = THREE.ClampToEdgeWrapping;
  return t;
}

// ---------------------------------------------------------------- ground material
export const groundUniforms = {
  uSeason: SU.uSeason,
  uSurf: { value: null },
  uTrack: { value: null },
  uNoise: SU.uNoise,
  uBounds: { value: new THREE.Vector4() },      // x0, y0, 1/w, 1/h (local)
  uSunDirW: SU.uSunDirW,
  uSparkle: { value: 1 },
};

// optional photographic texture sets (assets/tex, scene agent): {lawn, asphalt, concrete, bed, snow, snowPacked}
// each {a: albedo Texture (sRGB), n: normal Texture, size: metres per repeat}
export function groundMaterial(terrain, surfTex, trackTex, { lite = false, lib = null } = {}) {
  const U = groundUniforms;
  if (lib) {
    for (const [k, t] of Object.entries(lib)) {
      U['tA_' + k] = { value: t.a }; U['tN_' + k] = { value: t.n }; U['sz_' + k] = { value: 1 / t.size };
    }
  }
  U.uSurf.value = surfTex; U.uTrack.value = trackTex; U.uNoise.value = noiseTexture();
  U.uBounds.value.set(terrain.x0, terrain.y0, 1 / (terrain.x1 - terrain.x0), 1 / (terrain.y1 - terrain.y0));
  const m = new THREE.MeshStandardMaterial({ color: 0xffffff, roughness: 0.9, metalness: 0 });
  m.name = 'CC_Ground';
  m.onBeforeCompile = (sh) => {
    Object.assign(sh.uniforms, U);
    sh.defines = sh.defines || {};
    if (lite) sh.defines.CC_LITE = '';
    if (lib) sh.defines.CC_LIB = '';
    sh.vertexShader = sh.vertexShader
      .replace('#include <common>', '#include <common>\nvarying vec3 vWorldG;')
      .replace('#include <worldpos_vertex>', '#include <worldpos_vertex>\nvWorldG = (modelMatrix * vec4(transformed, 1.0)).xyz;');
    sh.fragmentShader = sh.fragmentShader
      .replace('#include <common>', `#include <common>
varying vec3 vWorldG;
uniform float uSeason, uSparkle;
uniform sampler2D uSurf, uTrack, uNoise;
uniform vec4 uBounds;
uniform vec3 uSunDirW;
#ifdef CC_LIB
uniform sampler2D tA_lawn, tA_asphalt, tA_concrete, tA_bed, tA_snow, tA_snowPacked;
uniform sampler2D tN_lawn, tN_asphalt, tN_concrete, tN_bed, tN_snow, tN_snowPacked;
uniform float sz_lawn, sz_asphalt, sz_concrete, sz_bed, sz_snow, sz_snowPacked;
#endif
float ccHash(vec2 p) { p = fract(p * vec2(123.34, 456.21)); p += dot(p, p + 45.32); return fract(p.x * p.y); }
`)
      .replace('#include <map_fragment>', `
vec2 lw = vec2(vWorldG.x, -vWorldG.z);
vec2 suv = vec2((lw.x - uBounds.x) * uBounds.z, (lw.y - uBounds.y) * uBounds.w);
vec3 surf = texture2D(uSurf, suv).rgb;
float track = texture2D(uTrack, suv).r;
vec4 nf = texture2D(uNoise, lw * 0.37);          // ~2.7 m tiles, fine detail
vec4 nm = texture2D(uNoise, lw * 0.061);         // ~16 m
vec4 nc = texture2D(uNoise, lw * 0.013);         // ~77 m
float wAs = surf.r, wCo = surf.g, wLa = surf.b, wBe = max(0.0, 1.0 - wAs - wCo - wLa);
// summer palette (linear)
vec3 asph = vec3(0.055, 0.056, 0.06) * (0.8 + 0.45 * nf.r) + vec3(0.04) * step(0.86, texture2D(uNoise, lw * 3.1).r);
asph *= 0.85 + 0.3 * nm.b;
vec3 conc = vec3(0.34, 0.33, 0.31) * (0.86 + 0.2 * nf.g) * (0.9 + 0.15 * nm.a);
vec3 lawnA = vec3(0.085, 0.16, 0.035), lawnB = vec3(0.17, 0.19, 0.06);
vec3 lawn = mix(lawnA, lawnB, smoothstep(0.35, 0.8, nm.g * 0.6 + nc.b * 0.6)) * (0.75 + 0.5 * nf.b);
float blades = texture2D(uNoise, lw * vec2(9.0, 7.0)).r * 0.6 + texture2D(uNoise, lw * vec2(23.0, 19.0)).g * 0.4;
lawn *= 0.72 + 0.56 * blades;
// planting beds / shrub cover: low evergreen groundcover with bark-mulch gaps
vec3 bed = mix(vec3(0.07, 0.05, 0.03), vec3(0.045, 0.085, 0.03), smoothstep(0.3, 0.55, nf.a * 0.55 + nm.r * 0.55)) * (0.75 + 0.5 * nf.r);
#ifdef CC_LIB
// photographic sets (scene agent library), large-scale tint variation breaks the tiling
vec2 rot = vec2(lw.x * 0.83 + lw.y * 0.55, -lw.x * 0.55 + lw.y * 0.83);
asph = texture2D(tA_asphalt, lw * sz_asphalt).rgb * (0.85 + 0.3 * nm.b);
conc = texture2D(tA_concrete, lw * sz_concrete).rgb * (0.9 + 0.15 * nm.a);
vec3 lawnT = mix(texture2D(tA_lawn, lw * sz_lawn).rgb, texture2D(tA_lawn, rot * sz_lawn * 0.37).rgb, 0.4);
lawn = lawnT * mix(vec3(0.95, 1.0, 0.85), vec3(1.15, 1.05, 0.8), smoothstep(0.3, 0.8, nm.g * 0.6 + nc.b * 0.6));
bed = mix(texture2D(tA_bed, lw * sz_bed).rgb, lawnT * vec3(0.6, 0.75, 0.55), smoothstep(0.35, 0.6, nf.a * 0.5 + nm.r * 0.6));
#endif
vec3 summerCol = asph * wAs + conc * wCo + lawn * wLa + bed * wBe;
float summerRough = 0.88 * wAs + 0.8 * wCo + 0.96 * wLa + 0.95 * wBe;
// winter: fresh snow on lawns/beds, packed + smoothed snow on the street and the sled track
float packed = clamp(wAs * 0.8 + wCo * 0.5 + track, 0.0, 1.0);
vec3 snowFresh = vec3(0.86, 0.885, 0.93) * (0.94 + 0.08 * nf.g);
vec3 snowPacked = vec3(0.7, 0.72, 0.76) * (0.92 + 0.1 * nf.r) * (0.95 + 0.08 * nm.b);
snowPacked = mix(snowPacked, vec3(0.78, 0.8, 0.84), track);
#ifdef CC_LIB
snowFresh = texture2D(tA_snow, lw * sz_snow).rgb * (0.95 + 0.07 * nm.g);
snowPacked = mix(texture2D(tA_snowPacked, lw * sz_snowPacked).rgb, snowFresh, 0.25 + 0.35 * track) * (0.96 + 0.06 * nm.b);
#endif
vec3 winterCol = mix(snowFresh, snowPacked, packed);
// dirty slush strip at the curbs / under conifer drip lines is skipped: snow is fresh (artistic)
float winterRough = mix(0.82, 0.45, packed * (0.6 + 0.4 * track));
vec3 gcol = mix(summerCol, winterCol, uSeason);
diffuseColor.rgb *= gcol;
`)
      .replace('#include <roughnessmap_fragment>', `
float roughnessFactor = mix(summerRough, winterRough, uSeason);
`)
      .replace('#include <normal_fragment_maps>', `#include <normal_fragment_maps>
#ifndef CC_LITE
{
  // micro relief: grass tufts / asphalt grain / snow ripples (world-space bump from noise gradients)
  float bs = mix(0.35 * wLa + 0.18 * wAs + 0.25 * wBe, 0.12 * (1.0 - packed) + 0.05, uSeason);
  vec2 e = vec2(0.06, 0.0);
#ifdef CC_LIB
  // tangent-space normal maps (OpenGL, +Y = north on the ground), blended by class weights
  vec3 tn;
  if (uSeason < 0.5) {
    tn = (texture2D(tN_asphalt, lw * sz_asphalt).xyz * wAs + texture2D(tN_concrete, lw * sz_concrete).xyz * wCo
        + texture2D(tN_lawn, lw * sz_lawn).xyz * wLa + texture2D(tN_bed, lw * sz_bed).xyz * wBe) * 2.0 - 1.0;
  } else {
    tn = mix(texture2D(tN_snow, lw * sz_snow).xyz, texture2D(tN_snowPacked, lw * sz_snowPacked).xyz, packed) * 2.0 - 1.0;
  }
  vec3 bw = vec3(tn.x, 0.0, -tn.y) * 0.9;
#else
  float h0 = texture2D(uNoise, lw * 1.7).r;
  float hx = texture2D(uNoise, (lw + e.xy) * 1.7).r, hy = texture2D(uNoise, (lw + e.yx) * 1.7).r;
  vec3 bw = vec3(-(hx - h0), 0.0, (hy - h0)) * bs * 4.0;
#endif
  normal = normalize(normal + (viewMatrix * vec4(bw, 0.0)).xyz);
}
#endif
`)
      .replace('#include <emissivemap_fragment>', `#include <emissivemap_fragment>
#ifndef CC_LITE
if (uSeason > 0.5) {
  // snow sparkle: sparse glints that light up when the half-vector meets a randomly oriented facet
  vec2 cell = floor(lw * 38.0);
  float hs = ccHash(cell);
  if (hs > 0.985) {
    vec3 Vw = normalize(cameraPosition - vWorldG);
    vec3 Hw = normalize(Vw + uSunDirW);
    vec3 fac = normalize(vec3(ccHash(cell + 1.7) - 0.5, 1.3, ccHash(cell + 3.1) - 0.5));
    float gl = pow(max(dot(Hw, fac), 0.0), 220.0);
    float dist = length(cameraPosition - vWorldG);
    totalEmissiveRadiance += vec3(gl * 3.5 * uSparkle * (1.0 - packed * 0.6) * smoothstep(40.0, 4.0, dist));
  }
}
#endif
`);
  };
  m.customProgramCacheKey = () => 'cc-ground' + (lite ? '-lite' : '') + (lib ? '-lib' : '');
  return m;
}
