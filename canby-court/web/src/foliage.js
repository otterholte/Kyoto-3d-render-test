// Leaf-card crowns (placeholder world, Medium+) from the scene agent's foliage atlas (assets/tex/foliage_atlas.*):
// conifers = drooping fir / cedar sprays (winter shifts the UVs to the snow-laden cells of the same atlas row),
// deciduous = maple clusters on an ellipsoid shell (summer only; winter keeps the bare branch skeletons).
// Card normals point away from the crown axis so a crown shades as one soft volume.
import * as THREE from 'three';
import { mulberry } from './util.js';
import { SU } from './shared.js';

// unit crown space: height 1 (base at 0), radius 1; the instance scale is (r, h, r). Cards are sized in metres for
// a typical crown (r0, h0) and converted (x/z by r0, y by h0).
export function crownGeometry(kind, cellName, cells, seed, { r0 = 4, h0 = 20, cards = 220, cardM = 2.0 } = {}) {
  const cell = cells[cellName].uv_rect;
  const snow = cells[cellName + '_snow'];
  const snowShift = snow ? snow.uv_rect[0] - cell[0] : 0;
  const pos = [], nrm = [], uv = [], idx = [], shift = [];
  const UV = [[cell[0], cell[1]], [cell[2], cell[1]], [cell[2], cell[3]], [cell[0], cell[3]]];
  const quad = (cx, cy, cz, ax, az, droop, w, hgt, n) => {
    const al = Math.hypot(ax, az) || 1; ax /= al; az /= al;
    const ox = -az, oz = ax;                                  // sideways (unit space, x/z in r-units)
    const tx = ax * Math.cos(droop), ty = -Math.sin(droop) + 0.12, tz = az * Math.cos(droop);
    const k = r0 / h0;                                        // r-units -> h-units for the vertical extent
    const P = [
      [cx - ox * w / 2, cy, cz - oz * w / 2], [cx + ox * w / 2, cy, cz + oz * w / 2],
      [cx + ox * w / 2 + tx * hgt, cy + ty * hgt * k, cz + oz * w / 2 + tz * hgt], [cx - ox * w / 2 + tx * hgt, cy + ty * hgt * k, cz - oz * w / 2 + tz * hgt],
    ];
    const b = pos.length / 3;
    for (let q = 0; q < 4; q++) { pos.push(...P[q]); nrm.push(n.x, n.y, n.z); uv.push(...UV[q]); shift.push(snowShift); }
    idx.push(b, b + 1, b + 2, b, b + 2, b + 3);
  };
  const rnd = mulberry(seed);
  const n = new THREE.Vector3();
  if (kind === 'conifer') {
    for (let i = 0; i < cards; i++) {
      const t = Math.pow(rnd(), 0.85);                      // more sprays low in the crown
      const y = 0.15 + t * 0.83;
      const rad = Math.pow(1 - t, 0.9) * 0.95 + 0.05;
      const a = rnd() * Math.PI * 2, rr = rad * (0.3 + 0.65 * rnd());
      const sc = 0.55 + 0.45 * (1 - t);
      const w = cardM / r0 * (0.8 + rnd() * 0.5) * sc, hgt = cardM / r0 * (0.9 + rnd() * 0.4) * sc;
      n.set(Math.cos(a), 0.6, Math.sin(a)).normalize();
      quad(Math.cos(a) * rr, y, Math.sin(a) * rr, Math.cos(a), Math.sin(a), 0.3 + rnd() * 0.5, w, hgt, n);
    }
  } else {
    for (let i = 0; i < cards; i++) {
      const a = rnd() * Math.PI * 2, e = Math.acos(1 - 2 * Math.pow(rnd(), 0.8));
      const sx = Math.sin(e) * Math.cos(a), sy = Math.cos(e), sz = Math.sin(e) * Math.sin(a);
      const k = i % 4 === 0 ? 0.25 + 0.45 * rnd() : 0.65 + 0.35 * rnd();   // a quarter fill the inside
      n.set(sx, sy * 1.2 + 0.25, sz).normalize();
      const w = cardM / r0 * (0.8 + rnd() * 0.5), b = a + (rnd() - 0.5) * 2.4;
      quad(sx * k, 0.64 + sy * 0.34 * k, sz * k, Math.cos(b), Math.sin(b), -0.4 + rnd() * 1.4, w, w, n);
    }
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
  g.setAttribute('normal', new THREE.Float32BufferAttribute(nrm, 3));
  g.setAttribute('uv', new THREE.Float32BufferAttribute(uv, 2));
  g.setAttribute('aSnowShift', new THREE.Float32BufferAttribute(shift, 1));
  g.setIndex(idx);
  return g;
}

export function leafCardMaterial(albedo) {
  const mat = new THREE.MeshStandardMaterial({ map: albedo, alphaTest: 0.45, side: THREE.DoubleSide, roughness: 0.85, metalness: 0 });
  mat.name = 'CC_LeafCards';
  mat.onBeforeCompile = (sh) => {
    sh.uniforms.uSeason = SU.uSeason;
    sh.vertexShader = sh.vertexShader.replace('#include <common>', '#include <common>\nattribute float aSnowShift; uniform float uSeason;')
      .replace('#include <uv_vertex>', '#include <uv_vertex>\n#ifdef USE_MAP\nvMapUv.x += aSnowShift * step(0.5, uSeason);\n#endif');
    // leaves: a little transmission-like brightening toward the light (cheap backlight)
    sh.fragmentShader = sh.fragmentShader.replace('#include <map_fragment>', '#include <map_fragment>\ndiffuseColor.rgb *= 0.92;');
  };
  mat.customProgramCacheKey = () => 'cc-leafcards';
  return mat;
}
