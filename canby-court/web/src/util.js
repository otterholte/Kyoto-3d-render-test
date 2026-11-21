// Small shared helpers: storage (try/catch), text/GLB loading, error text.
import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { MeshoptDecoder } from 'three/addons/libs/meshopt_decoder.module.js';

export const store = {
  get(k, d) { try { const v = localStorage.getItem('cc-' + k); return v === null ? d : v; } catch { return d; } },
  set(k, v) { try { localStorage.setItem('cc-' + k, String(v)); } catch { /* storage unavailable */ } },
};

export function loadText(url, onProgress) {
  return new Promise((res, rej) => {
    const fl = new THREE.FileLoader(); fl.setResponseType('text');
    fl.load(url, res, onProgress, rej);
  });
}

export async function loadJSON(url) {
  const r = await fetch(url, { cache: 'no-cache' });
  if (!r.ok) throw new Error(`${url}: HTTP ${r.status}`);
  return r.json();
}

const gltfLoader = new GLTFLoader();
gltfLoader.setMeshoptDecoder(MeshoptDecoder);
// GLB by URL; '*.b64.txt' = GLB shipped as base64 text (the artifact host does not serve .glb)
// resourcePath: base for external URIs inside the GLB (e.g. 'assets/' for "tex/x.jpg")
export function loadGLB(url, onProgress, resourcePath = '') {
  return new Promise((res, rej) => {
    if (!/\.b64\.txt(\?|$)/.test(url)) { gltfLoader.load(url, res, onProgress, rej); return; }
    loadText(url, onProgress).then((txt) => {
      try {
        const s = txt.trim();
        let buf;
        if (typeof Uint8Array.fromBase64 === 'function') buf = Uint8Array.fromBase64(s);
        else { const bin = atob(s); buf = new Uint8Array(bin.length); for (let i = 0; i < bin.length; i++) buf[i] = bin.charCodeAt(i); }
        gltfLoader.parse(buf.buffer, resourcePath, res, rej);
      } catch (err) { rej(err); }
    }, rej);
  });
}

// readable text for anything a promise may reject with
export function describe(e) {
  if (!e) return 'unknown error';
  if (e instanceof Error) return e.message || e.name;
  if (typeof Event !== 'undefined' && e instanceof Event) {
    const t = e.target, src = t && (t.currentSrc || t.src || t.href);
    return `failed to load ${src || 'a resource'} (${e.type})`;
  }
  if (typeof e === 'object' && e.message) return String(e.message);
  return String(e);
}

export const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
export const lerp = (a, b, t) => a + (b - a) * t;
export const damp = (a, b, k, dt) => a + (b - a) * (1 - Math.exp(-k * dt));
export function angDiff(a, b) { let d = b - a; return Math.atan2(Math.sin(d), Math.cos(d)); }
// local (x east, y north, z up) -> three.js
export const toW = (x, y, z = 0, out = new THREE.Vector3()) => out.set(x, z, -y);

// point-in-polygon (local 2D)
export function inPoly(x, y, poly) {
  let ins = false;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const [xi, yi] = poly[i], [xj, yj] = poly[j];
    if ((yi > y) !== (yj > y) && x < (xj - xi) * (y - yi) / (yj - yi) + xi) ins = !ins;
  }
  return ins;
}
export function polyArea(poly) {
  let a = 0;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) a += (poly[j][0] * poly[i][1] - poly[i][0] * poly[j][1]);
  return a / 2;
}
export function mulberry(a) {
  return () => { a |= 0; a = a + 0x6D2B79F5 | 0; let t = Math.imul(a ^ a >>> 15, 1 | a); t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t; return ((t ^ t >>> 14) >>> 0) / 4294967296; };
}
