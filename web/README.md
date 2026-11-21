# Higashiyama Walk — browser explorer

A third-person, phone-and-desktop walk through the 400 × 400 m Higashiyama reconstruction
(Yasaka Pagoda, Yasaka-dōri, Kōshin-dō, Ninenzaka, Ichinenzaka, Sannenzaka). Static page: three.js
r170 + three-mesh-bvh 0.8.3 from the jsDelivr CDN (exact versions in an import map), everything else
is relative files in this folder.

## Build

```bash
cd web
npm install          # dev tools only: gltf-transform, meshoptimizer, three (tests), http-server
node build.mjs       # = npm run build
npm run serve        # http://localhost:8765/  (any static server works)
npm test             # Playwright end-to-end tests (desktop + iPhone 13 + Pixel 7), screenshots + results.json
```

`build.mjs`:

1. Picks the world: `assets/world_art.glb` (art pass) if present, else `assets/world.glb` (blockout).
   Picks `assets/pagoda.glb` (hero pagoda) if present.
2. Vertex colours: keeps the informative `COLOR_n` set as `COLOR_0`. If the median linear luminance of
   roof/wall colours is implausibly dark (< 0.03, the blockout's double sRGB→linear conversion of
   `plateau_rgb`) it re-encodes once. Recorded in the manifest.
3. Joins `B_*` buildings and `Barrier_*` per 100 m section and material. Every source object's name and extras
   are kept in the joined node's `extras.members`. The per-vertex `_MEMBER` attribute indexes into that list,
   so collider hits still resolve to e.g. `B_0af19343` or `Barrier_wall_osm…`. This takes the blockout from
   3,800 primitives (about 5 MB of JSON) to 59 nodes.
4. `dedup` + `prune` (extras kept) + `meshopt` (reorder, quantize 16-bit positions, `EXT_meshopt_compression`)
   into `dist/`. Writes `dist/manifest.json`.
5. Derives `assets/minimap.json` (simplified PLATEAU footprints, OSM streets/steps/barriers) from
   `data/processed/*.json` and copies `data/processed/surface_mask.png` to `assets/`.

**Re-run `node build.mjs` whenever `assets/world_art.glb` or `assets/pagoda.glb` change.** Without
`dist/manifest.json` the page falls back to a runtime HEAD check of `assets/world_art.glb` → `assets/world.glb`
and `assets/pagoda.glb`. Those source GLBs are not meant for publishing (world.glb is over 15 MB).

## Files to publish (paths relative to `web/`)

```
index.html  style.css
src/main.js src/config.js src/world.js src/materials.js src/sky.js src/controller.js src/camera.js
src/character.js src/input.js src/lanterns.js src/particles.js src/minimap.js
src/textures.js src/pbr.js src/post.js src/backdrop.js src/gallery.js
dist/manifest.json  dist/world_art.glb.b64.txt  dist/pagoda.glb.b64.txt  dist/backdrop.glb.b64.txt
assets/minimap.json  assets/surface_mask.png
assets/tex/facade_atlas.json assets/tex/library.json assets/tex/foliage_atlas.json + the image files they
  reference that the page uses (see "Texture library" below)
assets/renders/renders.json + its JPGs (when present)
```

The page requests only what `dist/manifest.json` lists, so a missing optional input (textures, backdrop,
renders) never causes a 404.

For the claude.ai artifact, publish `artifact.html` as the page instead of `index.html`. `build.mjs`
regenerates it from `index.html` on every build, so edit only `index.html`.

Do not publish `node_modules/`, `tests/`, `build.mjs`, `package*.json`, `assets/*.glb`.

## Controls

| | desktop | touch |
|---|---|---|
| walk | WASD / arrow keys (camera-relative) | left thumb: virtual joystick (appears where you touch, left 45 % of the screen) |
| run | hold Shift | **Run** toggle button |
| look | drag with the mouse | drag on the right side |
| zoom | mouse wheel | pinch |
| menu | Places (teleport), time-of-day + quality, ⓘ about/credits; Esc closes panels | same, 44 px targets |

Tap the mini-map to switch between the local view and the whole 400 m area.

## Texture library (texture agent, `assets/tex/`)

* `facade_atlas.json` ("facade_atlas v1": `files{albedo,normal,orm,emit}`, `modules{name:{uv_rect}}`). Slots
  are mapped by name in `src/textures.js` (`LIB_MODULE`).
* `library.json` (`sets{name:{files, size_m}}`). Roles map to sets in `LIB_SET`:
  * roofs → `roof_kawara_sangawara`
  * paving and steps → `ishidatami_granite`
  * setts → `setts_granite`
  * asphalt → `asphalt_worn`
  * gravel → `gravel`
  * soil → `earth_moss`
  * stone walls → `ishigaki_mossy`
* `foliage_atlas.json` (`cards{name:{uv_rect}}`): maple_autumn, maple_green, cherry_leaf, pine_needles,
  shrub_azalea, bamboo_leaves.
* Files actually loaded:
  * the 4 facade atlas images;
  * the foliage atlas albedo PNG (with alpha);
  * albedo / normal / ORM for the 7 sets listed above.

  Every other set in `assets/tex/` is unused for now and does not need publishing.
* Anything missing falls back to the procedural textures generated in `src/textures.js` (artistic
  stand-ins).

## Data contract (what the page expects)

* Frame: three.js x = east, y = up (absolute T.P. height, about 48–86 m), z = −north. Local origin is the box
  centre (EPSG:6674 E −20160, N −111160). Boundary ±200 m.
* `Terrain*`: walkable. It is rendered with the page's own ground shader, which samples
  `assets/surface_mask.png` by world position (R asphalt, G granite paving, B gravel, else soil; extent ±300 m,
  row 0 = north), plus hand-painted noise, ishidatami slab pattern and wet sheen at dusk.
* `B_*` / `Buildings_s*` (joined): collide; material slot names `*roof*` / `*wall*` / `*plinth*` select the
  blockout's role materials (the PLATEAU colours get a perceptual lift).
* `Steps_osm*`: walkable stairs. `Barrier_*`: collide. `Paving_osm*` and any `extras.walkable`: walkable.
  `extras.collide`: collides. The art kit (`Kit_*`), `StreetLamp*` and `Lantern_osm*` always collide so that
  benches, pots and lamps match the visible scene.
* Trees: blockout `Tree_*`/`TreeCrown_*` are replaced by instanced procedural trees at the same positions and
  sizes. Art trees (`Tree*`, `Shrub*`) keep their meshes. Trees with `extras.collide` get a 0.26 m trunk
  collider.
* Art world (`manifest.world.kind == "art"`): authored materials are kept. Meshes reused at least 4 times are
  instanced; the rest are merged per material and 100 m section. With no normals, objects are flat shaded.
  Materials named `*glow*` / `*emiss*` are dimmed at golden hour and brightened at blue hour.
* `pagoda.glb` (world coordinates): the visible meshes are shown. Meshes named `*COLLIDER*` (or with
  `extras.collider_for`) are used for collision and hidden. `LM_Yasaka_Pagoda_PLATEAU_LOD2` is then hidden and
  excluded from collision. The root's `extras.height_m` appears in the info panel.

## Runtime

* **Physics**: one `MeshBVH` over all colliders (terrain, buildings, pagoda collider, steps, barriers,
  kit, trunks; about 280k triangles, built in about 0.2 s).
  * Kinematic capsule: radius 0.30 m, height 1.68 m. The horizontal capsule is lifted by the 0.35 m step-up,
    so risers up to 0.35 m are climbed. Walls push it out and it slides along them.
  * Ground snap uses 5 downward rays. Slopes over 40° block uphill movement.
  * Physics runs at a fixed ≤ 1/60 s sub-step. A soft invisible wall at ±199.5 m shows a message.
* **Camera**: smooth orbit follow. Five rays approximate a sphere sweep and pull the camera in (fast) when
  geometry blocks the view, then ease it back out. On touch it gently auto-aligns behind the walker.
* **Look (realism pass)**:
  * **PBR role materials** (`src/pbr.js`) use the texture library (`src/textures.js`):
    * **Facades:** each storey and bay picks a module from the facade atlas
      (`assets/tex/facade_atlas.json`). UVs are computed in the shader: u = metres along the wall / 1.82 m bay,
      v = metres above the building's wall base / storey height. Module choice comes from the PLATEAU extras:
      * `usage`: temple, shop-house, residential;
      * `storeys`, `year`, art `priority`;
      * a deterministic per-building seed.

      Bays vary (senkoshi, noren entrance, open shop, itabari, mushiko-mado, lattice and glazed windows,
      plaster). The emissive mask lights interiors at dusk. If walls carry GLB UVs flagged `extras.facade_uv`
      (u = bays, v = storeys), those UVs are used instead.
    * **Roofs:** kawara with u along the eave and v down the slope; flat roofs get a membrane finish.
    * **Stone:** box-mapped for plinths, steps and walls (ishigaki).
    * **Ground:** ishidatami, asphalt, gravel and earth-moss by world UV, blended by the surveyed surface
      mask. Street ribbons get ishidatami or setts by OSM `surface`. Wet sheen at dusk.
    * The art/PLATEAU vertex colours are a gentle tint on all of these.
    * Role geometry is non-indexed with exact per-face normals: UV frames built from screen-space
      derivatives of world positions speckle at 150 m (float32). Per-building constants use a `flat` varying.
  * **Trees:** alpha leaf-card canopies (foliage atlas cards by OSM/art species: autumn and green maple,
    cherry, pine, shrubs) replace the low-poly crowns. Trunk colliders are unchanged.
  * **Lighting:**
    * Physically based sun for Kyoto, mid-November: the slider runs from about 16:00 JST (az 230°,
      alt 12°) to civil twilight (alt −6°). Colour and illuminance follow a Rayleigh/Mie transmittance over
      Kasten–Young airmass.
    * Image-based lighting from the PMREM of the sky dome (`scene.environment`), with hemisphere fill reduced.
    * Exponential height fog plus aerial perspective: the haze toward the sun is lit warm. This is a patch
      on every material (`patchAtmos`).
  * **Backdrop:** `dist/backdrop.glb` (real Kyoto terrain rings to ±15 km plus PLATEAU city massing, from
    the backdrop agent). It loads after the walk starts, has no collision and no shadows, and is
    fog-blended. The camera far plane is 18 km (near 0.12 m, normal 24-bit depth). When the backdrop is
    present, the sky's painted ridge is switched off.
  * **Post** (`src/post.js`, one composer): GTAO ambient occlusion (half resolution on High, full in Photo
    mode; leaf cards, sky and particles excluded), UnrealBloom, ACES output, a colour grade (gentle
    S-curve, split toning, vignette), then FXAA (Medium) or SMAA (Photo). High uses 4× MSAA.
  * **Artistic extras:** instanced chōchin lanterns with halo sprites, falling momiji leaves, lit facade
    interiors at blue hour.
* **Quality tiers** (`src/config.js`): see the table.

  | tier | used by | post | AO | AA | shadows |
  |---|---|---|---|---|---|
  | low | — | none | — | — | none |
  | medium | default on phones | grade | — | FXAA | 1k PCF, trees don't cast; lite ground shader |
  | high | default on desktop | grade, bloom | GTAO ½-res | MSAA 4× | 2k PCF-soft |
  | ultra | Photo mode only | grade, bloom | full-res GTAO | SMAA + MSAA | 4k over ±60 m, DPR up to 2.5 |

  `?q=low|medium|high|ultra` forces a tier for one visit.
* **Photo mode** (camera button, bottom right): hides the UI and switches to Ultra. **Save image** downloads
  a PNG; you can toggle the traveller; Esc or **Exit** returns.
* **Renders gallery** (image button, top bar): lists `assets/renders/renders.json`. Accepted entries are a
  file name (`"a.jpg"`) or `{file, title, caption, thumb}`, either as a plain list or under `{renders: [...]}`.
  Shows "No renders published yet" when the list is missing or empty. Tap a render for a full-screen lightbox.
* **Quality**: Auto picks High on desktop and Medium on touch devices. Pixel ratio is capped at 2 on desktop
  and 1.5 on mobile, and adaptive resolution (scale 0.6–1.0, refresh-aware: drops below target, recovers once fps sits at the display refresh; the first window after start, a quality change or a tab return is skipped; shaders are pre-compiled before the loader hides). Low turns
  shadows off. The choice and the time of day are remembered in localStorage (wrapped in try/catch).
* **Robustness**:
  * A classic inline watchdog shows a clear message if the CDN module or import maps fail (immediately on
    a module fetch error, or after 20 s).
  * A missing surface mask falls back to plain ground.
  * The frame loop survives exceptions; a fatal message appears after 5 consecutive failures.
  * GLB URLs carry `?v=<manifest.generated>`.
  * The shadow map is re-rendered only when the light, its snapped centre or the walker changes. Mobile
    uses PCF; trees cast shadows only on High.
* **Test hooks**: `window.__hw` exposes `state()`, `teleport()`, `probe()`, `setTime()`, `stats()` and
  `quality()` for the Playwright suite.

## What is measured vs artistic

Shown in the ⓘ panel.
* **Measured**: terrain (GSI DEM5A), buildings (PLATEAU LOD2), streets, steps, barriers and trees (OSM),
  and ground surface classes.
* **Artistic**: lantern placement, falling leaves, sky and hills, fog, wet sheen, lighting, and the traveller.
* **Defaults (inferred)**: untagged wall and tree sizes.
* The art pass and the hero pagoda carry their own evidence notes in `extras` and `docs/evidence/`.

Credits: © OpenStreetMap contributors (ODbL) · 国土地理院 (GSI) · PLATEAU (MLIT) · Wikimedia Commons.

## Published build

Live (claude.ai artifact): https://claude.ai/artifact/PHsRBZiypkVmaGeBJbuStU

`artifact.html` is `index.html` without the html/head/body wrapper (the artifact host adds it); it is
regenerated by `node build.mjs`.
The host does not serve `.glb`, so `build.mjs` also writes each optimised GLB as base64 text
(`dist/*.glb.b64.txt`), which `src/world.js` decodes before `GLTFLoader.parse`.
