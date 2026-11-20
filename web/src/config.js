// Shared constants. Local frame (docs/boundary.md): x = east, north = y_local; three.js z = -north.
export const BOUNDARY = 200;          // half size of the 400 m box
export const SOFT_EDGE = 195;         // start warning here
export const TERRAIN_EXTENT = 300;    // terrain / surface-mask half extent

// Late-afternoon sun from the WSW (azimuth clockwise from north, degrees)
export const SUN_AZIMUTH = 245;

export const PAGODA = { x: 9.67, n: 83.46 };

// Teleport targets. `look` = point to face (local x, north). Spots flagged `verify` are probed at runtime
// (downward ray must land on terrain/steps with free capsule space; otherwise the nearest free spot is used).
export const PLACES = [
  { id: 'yasaka', ja: '八坂通', en: 'Yasaka-dōri view', x: -79, n: 88.2, look: [PAGODA.x, PAGODA.n] },
  { id: 'gate', ja: '八坂の塔 門前', en: 'Yasaka Pagoda gate', x: -5, n: 75, look: [PAGODA.x, PAGODA.n], verify: true },
  { id: 'ninenzaka', ja: '二寧坂', en: 'Ninenzaka', x: 153.6, n: 98, look: [155.5, 45] },
  { id: 'ninen-steps', ja: '二寧坂 石段上', en: 'Ninenzaka steps (top)', x: 152, n: 24, look: [155.9, 60] },
  { id: 'ichinenzaka', ja: '一念坂', en: 'Ichinenzaka', x: 110, n: 152, look: [150, 150] },
  { id: 'sannen-stairs', ja: '産寧坂 石段下', en: 'Sannenzaka stairs (bottom)', x: 166.5, n: -142, look: [151, -177] },
  { id: 'koshindo', ja: '八坂庚申堂', en: 'Kōshin-dō', x: -36, n: 66, look: [PAGODA.x, PAGODA.n], verify: true },
];
export const SPAWN = PLACES[0];

// Named zones for the place label (rough, from OSM street extents)
export const ZONES = [
  { ja: '八坂の塔', en: 'Yasaka Pagoda', test: (x, n) => Math.hypot(x - PAGODA.x, n - PAGODA.n) < 22 },
  { ja: '八坂庚申堂', en: 'Kōshin-dō', test: (x, n) => Math.hypot(x + 36, n - 62) < 14 },
  { ja: '一念坂', en: 'Ichinenzaka', test: (x, n) => x > 95 && x < 146 && n > 134 && n < 162 },
  { ja: '二寧坂', en: 'Ninenzaka', test: (x, n) => x > 140 && x < 170 && n > 21 && n < 165 },
  { ja: '産寧坂', en: 'Sannenzaka', test: (x, n) => x > 140 && x < 185 && n > -185 && n <= 21 },
  { ja: '東大路通', en: 'Higashiōji-dōri', test: (x) => x < -168 },
  { ja: '八坂通', en: 'Yasaka-dōri', test: (x, n) => n > 68 && n < 102 && x < 140 },
  { ja: '東山', en: 'Higashiyama', test: () => true },
];

export const QUALITY = {
  low: { dprCap: 1.0, shadow: 1024, shadowRange: 26, bloom: false, msaa: false, particles: 120, petalsSize: 1 },
  medium: { dprCap: 1.5, shadow: 1024, shadowRange: 32, bloom: false, msaa: false, particles: 220, petalsSize: 1 },
  high: { dprCap: 2.0, shadow: 2048, shadowRange: 40, bloom: true, msaa: true, particles: 420, petalsSize: 1 },
};
