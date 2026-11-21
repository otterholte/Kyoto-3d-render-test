// Shared constants. Local frame (data/processed/boundary.json): x = east, y = north (m from the 3905 Canby Ct address
// point, EPSG:6339 E 539320 / N 5396840), z = NAVD88 m.  three.js frame: (x, z, -y).
export const LAT = 48.72334, LON = -122.46537;
export const CONTEXT = [-210, -160, 110, 110];      // walkable box (x0, y0, x1, y1), soft wall at its edge
export const SOFT_MARGIN = 6;

// Places: x/n = local east/north, look = point to face.
export const PLACES = [
  { id: 'bulb', en: 'Cul-de-sac bulb', sub: 'Canby Ct, facing 3905', x: -18, n: -24, look: [0, -2], pitch: 0.08, dist: 6.5 },
  { id: 'front', en: '3905 front door', sub: 'walkway from the bulb', x: -5.5, n: -13.5, look: [0.5, -5], pitch: 0.12, dist: 5 },
  { id: 'back', en: '3905 back yard', sub: 'rear lawn, north side', x: -8, n: 22, look: [2, 4], pitch: 0.1, dist: 6 },
  { id: 'top', en: 'Top of the sled run', sub: 'by the 3904 / 3909 drives', x: 3.2, n: -37.6, look: [-30, -31], pitch: 0.18, dist: 6, sledHere: true },
  { id: 'bottom', en: 'Bottom · 38th St', sub: 'Canby Ct junction', x: -121, n: -6.5, look: [-80, -18], pitch: 0.05, dist: 6 },
];
export const SPAWN = PLACES[0];

// Named zones for the place label
export const ZONES = [
  { en: '3905 Canby Ct', test: (x, n) => x > -14 && x < 22 && n > -12 && n < 34 },
  { en: 'Cul-de-sac bulb', test: (x, n) => Math.hypot(x + 16, n + 26) < 15 },
  { en: 'Canby Ct', test: (x, n) => x > -128 && x < -16 && n > -45 && n < -2 },
  { en: '38th St', test: (x) => x <= -128 && x > -145 },
  { en: 'Canby Court', test: () => true },
];

// Seasons: dates/times chosen for the look (artistic), sun from a solar-position model for Bellingham.
export const SEASONS = {
  summer: {
    label: 'Summer', date: Date.UTC(2025, 6, 21, 2, 20), // 2025-07-20 19:20 PDT, late afternoon
    sky: { zenith: [0.16, 0.34, 0.72], horizon: [0.72, 0.8, 0.9], ground: [0.32, 0.3, 0.27], haze: 0.35, clouds: 0.32, cloudCol: [1.0, 0.97, 0.93], overcast: 0 },
    sunScale: 1.15, hemiI: 0.35, envI: 0.85, fog: [0.72, 0.78, 0.86], fogD: 0.0018, exposure: 1.0, shadowDark: 1.0,
  },
  winter: {
    label: 'Winter', date: Date.UTC(2025, 11, 28, 21, 50), // 2025-12-28 13:50 PST, low sun through thin overcast
    sky: { zenith: [0.42, 0.47, 0.56], horizon: [0.8, 0.82, 0.86], ground: [0.7, 0.72, 0.76], haze: 0.7, clouds: 0.92, cloudCol: [0.86, 0.88, 0.92], overcast: 1 },
    sunScale: 0.45, hemiI: 0.6, envI: 0.95, fog: [0.74, 0.77, 0.82], fogD: 0.0042, exposure: 0.92, shadowDark: 0.55,
  },
};

// Quality tiers. post: composer on; ao: GTAO; aa: 'msaa' | 'fxaa' | 'smaa' | 'none'. 'ultra' = Photo mode only.
export const QUALITY = {
  low: { dprCap: 1.0, shadows: false, shadow: 1024, shadowRange: 24, bloom: false, post: false, ao: false, aa: 'none', snow: 900, grass: false },
  medium: { dprCap: 1.5, shadows: true, shadow: 1024, shadowRange: 30, bloom: false, post: true, ao: false, aa: 'fxaa', snow: 1800, grass: true },
  high: { dprCap: 2.0, shadows: true, shadow: 2048, shadowRange: 40, bloom: true, post: true, ao: true, aoScale: 0.5, aoSamples: 12, aa: 'msaa', snow: 4000, grass: true },
  ultra: { dprCap: 2.5, shadows: true, shadow: 4096, shadowRange: 55, bloom: true, post: true, ao: true, aoScale: 1.0, aoSamples: 16, aa: 'smaa', snow: 4000, grass: true },
};

// Sled game tuning (SI units). Friction ~0.05-0.1 on packed snow (artistic but physically plausible).
export const SLED = {
  g: 9.81, mu: 0.045, muOffTrack: 0.08, muBrake: 0.3, muStop: 0.55, dragK: 0.0026, carve: 0.88, muLat: 0.55, muLatSkid: 0.28,
  steerRate: 1.5, airSteerRate: 1.1, push: 3.0,
  popWindowBefore: 0.35, popWindowAfter: 0.25, popBase: 2.3, popBonus: 1.3, ollie: 1.7,
  tricks: {
    superman: { label: 'Superman', points: 600, dur: 0.95, key: '1' },
    spread_eagle: { label: 'Spread eagle', points: 400, dur: 0.8, key: '2' },
    grab: { label: 'Grab', points: 250, dur: 0.6, key: '3' },
  },
  wipeImpact: 12.5,     // m/s into the ground (normal component)
  wipeYaw: 1.25,        // rad between sled heading and travel direction on landing
  trickFinish: 0.85,    // fraction of a trick that must be done before touch-down
};
