# Art direction — painterly Higashiyama (Phases 5, 6, 8-Blender)

**Rule: accuracy first, stylisation second.** The art pass (`blender/art_pass.py` + `blender/kit_*.py`) starts from
`blender/higashiyama_blockout.blend` and never moves surveyed geometry: footprints, roof shapes, heights, streets,
stairs, terrain and tree positions stay as they were. The only geometric change to a building is the documented wall
inset under the eaves (see 1). Everything the pass adds carries `detail_class` (`observed` | `inferred` | `artistic`)
and an `evidence_ref` custom property. The `evidence_confidence` property keeps the raw evidence class
(observed / documented / measured / inferred).

```
/home/user/venv/bin/python blender/art_pass.py            # -> blender/higashiyama_art.blend (checkpoint after each stage)
/home/user/venv/bin/python blender/kit_render.py --shots a,e,b,c,d --res 3840 --samples 96 --threshold 0.03 --time-limit 1200 --out renders/final_
/home/user/venv/bin/python blender/kit_gallery.py         # -> web/assets/renders/*.jpg + renders.json
/home/user/venv/bin/python blender/kit_export.py          # -> web/assets/world_art.glb
```

## 1. Architecture (`kit_arch.py`, `kit_machiya.py`)

| priority | selection | treatment |
|---|---|---|
| **2** (126 buildings) | footprint within street half-width + 2.5 m of the OSM centrelines of 八坂通 (24516359 + its pedestrian continuation 710696944), 二寧坂, 産寧坂, 一念坂 | uniform 0.45 m street-front eave on traditional buildings only (see below). The roof keeps its exact shape and gets a 0.2 m slab, ridge caps (munagawara) on convex roof edges and a nokigawara roll on horizontal eave edges. The machiya kit is placed on the street-facing walls |
| **3** (539) | other buildings in the box | LOD2 geometry kept; 0.15 m roof fascia + ridge caps; painterly materials |
| **4** (602) | backdrop outside the box | massing and roof silhouette only, one atmospheric material |

**Wall inset (revised after the accuracy audit, `docs/accuracy_report.md` F1).** PLATEAU LOD2 walls stand on the roof edge
(`lod0RoofEdge`). The first version of this pass set walls back per edge from GSI 建築物の外周線 offsets. The audit showed
those GSI-vs-PLATEAU differences are registration noise, not eaves, so that rule was removed. The pass now applies **one uniform,
inferred 0.45 m inset** (`evidence_ref` = "typical machiya eave overhang (building_evidence.md)", `detail_class=inferred`).
* It applies only to street-facing edges of *traditional* Priority-2 buildings: timber (木造・土蔵造) in
`building_evidence.json` and ≤ 3 storeys. That is 60 buildings and 93 edges.
* Every other wall stays exactly on the PLATEAU outline: unknown or non-timber structure, side, rear and party walls (1,219 edges).
* Roofs are untouched. New wall tops are ray-cast onto the roof underside. A 0.35 m stone plinth band follows the terrain.

**Machiya kit** (hidden collection `A_Asset_Library`, one collection per piece, placed as collection instances in
`60_Machiya_Kit/60_Kit_<street>`). There are 2,721 placements: 1,052 `observed`, 1,419 `inferred` and 250 `artistic`. The inferred count includes 206 gutters and downpipes. Every placement carries both `detail_class` and the boolean `artistic`. Proportions follow `docs/evidence/building_evidence.md`:
* bays of 1 ken (1.82 m);
* a tiled 1F hisashi with its outer edge at about 2.6 m and attached at about 3.0 m (PLATEAU has no hisashi; the evidence gives 2.7–3.2 m);
* oya-ko sen-gōshi at a 56 mm slat pitch;
* glazed sliding doors with noren in indigo, brown, cream or persimmon;
* open lit shopfronts where an OSM shop, café or restaurant POI is within 6 m, or the PLATEAU usage is commercial or mixed;
* hanging signboards;
* red chōchin at food POIs, and black lanterns with white panels or white chōchin at other shops;
* on the 2F, exposed posts and beam (shinkabe) and glazed lattice windows with sudare (observed as dominant), sometimes with a wooden railing (observed). Mushiko-mado appear sparingly, only on low (eave < 6 m) upper floors (documented district standard; not clearly seen in photos);
* inuyarai rare (12 % of closed bays: only *inferred* on the main slopes);
* old-style lamp posts (type observed, positions artistic);
* potted plants and andon (artistic).

`detail_class` is `observed` when `building_evidence.json` has an *observed* item for that feature on that street segment
(Ichinenzaka is always inferred from Ninenzaka, as the evidence notes). Otherwise it is `inferred`, or `artistic` for pots, andon and lamp-post positions.
`evidence_ref` names the evidence item and photo, the OSM POI or PLATEAU usage that triggered the shop treatment, and the
nearest geotagged Commons photos.

Modern blocks (≥3 storeys or >11.5 m) get no machiya dressing, only a lit shopfront where there is a shop. This keeps
Yasaka-dōri west honest: the evidence describes it as mixed, with RC/steel blocks.

## 2. Materials

**Realism revision (lead/user feedback "reads as boxes").** The image-based texture library (`blender/materials_textured.py`,
`blender/textures/`, `docs/texture_library.md`) is now applied:
* all 1,267 PLATEAU buildings: the facade atlas mapped per storey by `assign_facades` (machiya / modern / temple modules; the
  structure class comes from `building_evidence.json`) and kawara tiles with eave and ridge strips (`apply_roof_uvs`);
* paving ribbons: `ishidatami_granite`, or `setts_granite` on Yasaka-dōri west;
* terrain: asphalt / setts / gravel / earth-moss blended by the surveyed surface mask (`kit_texground.py`);
* steps: `stone_steps_trim`; walls: `ishigaki_mossy`; fences: `bamboo_fence_kenninji`.

**Coherent facades (`kit_facades.py`).** Each building gets ONE module family, seeded by its PLATEAU id: one upper-storey module on
street fronts, one plaster colour (cream or ochre) for its other upper walls, and one ground-floor module. Commercial fronts allow
at most about one feature bay (shop opening or noren entrance). Side, rear and party walls are plain itabari or plaster. Priority-2
traditional fronts never get modern modules. Where the geometric kit stands, the atlas ground floor is plain itabari, so the kit's lattice,
doors and shopfronts are not doubled; the atlas provides the upper storeys, and the kit no longer places flat 2F pieces.

**Roof edges.** The PLATEAU roof edge is the eave line, and it is not extended. Instead the roof slab (0.2 m on Priority 2, 0.15 m on Priority 3)
gets a timber fascia and soffit (slot 4). Ridge caps and the nokigawara tile-edge roll use procedural kawara (slot 3). On the 93
inset street-front edges, 885 exposed rafter tails sit under the eave (`60_Eave_Rafters`, inferred).

**Trees** use the library's alpha foliage cards (`foliage_atlas`):
* maples use `maple_autumn`;
* cherries mix bronze `cherry_leaf` and `maple_autumn`;
* pines use `pine_needles`;
* bamboo uses `bamboo_leaves`;
* shrubs use azalea or box.

Ginkgo keeps the procedural yellow cards.

**Stairs.** The fix is upstream: `build_world.py` now lowers the DEM under every OSM flight (`carve_under_steps`). The regenerated
blockout and `world.glb` agree with the art pass.

The machiya kit geometry stays on top of the Priority-2 street walls. It now has 6 mm geometric bevels on its pieces, plus
inferred eave gutters and downpipes on every hisashi. Concrete utility poles and overhead wires were added on Yasaka-dōri west,
where they are observed (positions inferred; the shot-(a) sightline to the pagoda is kept clear). The procedural
materials below remain for the kit, the trees and the fallbacks. The brushwork is now subtle (`BRUSH_AMOUNT` 0.5, Kuwahara 18 %).

### Procedural set (`kit_materials.py`)
Palette (linear RGB), taken from the *observed* evidence colours and pushed warm/muted:

| role | colour | source |
|---|---|---|
| kawara | (0.165, 0.175, 0.195) | #7d8085 observed |
| plaster cream / ochre | (0.70, 0.59, 0.40) / (0.52, 0.37, 0.19) | #e6d6b0 / #c8a878 observed |
| dark timber | (0.075, 0.032, 0.012) | #5a3418 observed |
| granite slab / sett | (0.36, 0.335, 0.30) / (0.24, 0.225, 0.195) | #a9a39a / #8a857a observed |
| bengara lattice | (0.115, 0.036, 0.018) | district standard (documented) |
| lantern amber / shop glow | (1.0, 0.42, 0.13) / (1.0, 0.58, 0.28) | artistic |

* **Facades** use `plateau_rgb`, the real mean colour per surface, as the base tint. Dark surfaces turn into weathered vertical boards; light ones turn into lime/earth plaster with soft stains.
* **Roofs** have a kawara wave (0.30 m) and course (0.27 m) normal detail, computed from the face normal without UVs. Per-tile value jitter, faint lichen, a dark fascia and a timber soffit are added.
* **Paving.** P2 streets are UV ribbons that follow the OSM centreline (`detail_class=inferred`: the centreline and surface are documented, the widening and slab pattern are not). They use the mapped width and are extended up to 3 m to the building line (inferred). Ninenzaka, Sannenzaka and Yasaka-dōri east get ishidatami slabs about 0.31 × 0.62 m in running bond. Yasaka-dōri west (OSM `surface=sett`) gets small setts. Granite gutter bands sit at the edges.
* **Wet sheen.** Post-rain sheen comes from a restrained (~9 %) low-frequency puddle mask with low roughness, plus darker joints.
* **Other surfaces.** Stone steps have worn bright edges (bevel-normal mask) and moss in crevices (AO). Barrier walls are mossy stone; fences are bamboo/wood.
* **Brushwork.** The shared node group `G_Brush` jitters hue, saturation and value by a few percent with noise-warped, stretched Voronoi dabs. It acts on colour only, never on geometry.
* **Edges.** Kit wood and plaster use a bevel-shader edge highlight for softened edges.
* **Compositor.** A light anisotropic Kuwahara pass (55 % mix) gives the painterly read in the final images.

## 3. Vegetation (`kit_veg.py`) — season: **late autumn (mid/late November, kōyō)**
Late autumn was chosen because it is Higashiyama's signature season and suits the late-afternoon to blue-hour light. Maples are crimson-orange,
cherries bronze and thinning, ginkgo yellow, pines and evergreen broadleaves dark. Fallen maple leaves lie in the gutters.

* **Documented** (`50_Vegetation_Documented`): all 274 OSM tree points keep their exact positions (tree rows are sampled every 5 m). Heights come from `height` tags, otherwise the default is 7 m (flagged).
  * Species come from tags where present: 3 cherries (Cerasus, ヤマザクラ), 1 Acer palmatum, 1 broadleaved.
  * The other 223 trees have no tags. They get an inferred species from a late-autumn Higashiyama mix, flagged as `species_src = inferred`.
  * The trees are painterly prototypes with clustered leaf "dabs" (maple ×3, cherry ×2, pine niwaki pads ×2, broadleaf ×2, ginkgo), placed as collection instances named `Tree_osm<id>_<k>`.
* **Artistic** (`55_Vegetation_Artistic`, `artistic=True`):
  * forest and garden fill inside OSM `landuse=forest`, `natural=scrub` and `leisure=garden/park` areas (area documented, plants inferred), including bamboo;
  * shrubs along walls;
  * weeds at facade bases;
  * about 15,000 fallen leaves on the paving, denser in gutters and near maples;
  * moss on walls, roofs and steps (shader only).
* **Pagoda sightlines (audit F9).** Artistic trees are kept out of 5 m corridors from every geotagged Commons photo of the pagoda, and from the hero cameras, to the pagoda (18 skipped). Documented trees with the default 7 m height inside a corridor get crowns drawn 20 % smaller (flagged `crown_note`).

## 4. Lighting & atmosphere (`kit_light.py`)
* **Sky.** Blender 5.2's `MULTIPLE_SCATTERING` sky has its sun disc off. It is paired with a separate sun lamp from the WSW (azimuth 238–246°, the late-November sunset direction).
* **Presets.** Real sun positions for Kyoto on 20 November:
  * `golden`: 16:00 JST, azimuth 231°, altitude 11.5°;
  * `dusk`: 16:25 JST, azimuth 237°, altitude 6.5°;
  * `blue`: sun at −4°, no sun lamp, sky only, lanterns ×1.25, pagoda floodlights on.
* **Ambient.** For non-camera rays, part of the physical sky is replaced by an art-directed tint: warm peach in the golden hour, lavender at blue hour. This gives lavender-blue shadows without a navy cast. The sky as seen by the camera is scaled separately.
* **Lanterns and lights.**
  * The documented 常夜燈 stone lantern (OSM 14104439550) and the two OSM street lamps are modelled with real point lights.
  * Every kit chōchin, andon, black lantern and lamp post gets a small warm point light (inferred/artistic, as its kit piece).
  * Lit koshi and shopfronts glow (emission).
  * Yasaka Pagoda night illumination is observed in the Commons "Illuminated Yasakanoto Tower" photos. It is rendered with four ground floods; the fixture positions are artistic.
* **Fog.** A thin, homogeneous fog fills a terrain-following shell (ground −2 m to +16 m) over the box. It hazes the space between buildings and thins above the roofs. Being homogeneous, it costs no ray-marching.
* **Distant landscape.** `blender/build_backdrop.py` `add_backdrop(scene, "render")` (backdrop workstream, `docs/backdrop.md`) provides GSI terrain rings to ±15 km, 69.6k PLATEAU city buildings and forest canopy. Each preset retunes its aerial perspective (nodes `BackdropHaze` / `BackdropHazeAmount`). My painted DEM10B backdrop (`kit_backdrop.py`) is only a fallback.
* **Grade.** AgX (Base Contrast), then a compositor soft bloom (Glare/Bloom), anisotropic Kuwahara (55 %), a cool-lift/warm-gain colour balance, slight desaturation and a vignette.

## 5. Hero pagoda
`kit_light.pagoda()` imports `blender/hero_pagoda.py` and calls `build_pagoda(collection, "high")` (hero model by the pagoda workstream: measured position, 38.8 m total, +1.4° orientation; the hidden `LM_Yasaka_Pagoda_COLLIDER` stays non-rendering). Its procedural materials get the shared `G_Brush` colour jitter for consistency. Shot (d) switches on four artistic ground floods, because the night illumination of the pagoda is observed in Commons photos. The PLATEAU placeholder
`LM_Yasaka_Pagoda_PLATEAU_LOD2` is hidden. If the import fails, the placeholder stays and `scene["pagoda"]` records why.

## 6. Shots
All camera positions are snapped to OSM centrelines, at the walkable surface (terrain, or the step/paving surface under the camera) + 1.6 m. Shot (d) is raised 14 m above the walkable point.

| shot | position | preset |
|---|---|---|
| a Yasaka-dōri, looking east to the pagoda | way 24516359 near (−79, 88) | golden |
| b Ninenzaka, looking south to its 17 steps | way 30913263 near (153.6, 98) | dusk |
| c Sannenzaka 46-step stair, looking up-south | way 1569088146 near (166.5, −142) | dusk |
| d blue-hour view over the kawara roofs to the illuminated pagoda | above way 710696944 near (118, 30), +14 m | blue |
| e iconic view down Yasaka-dōri east to the pagoda, matching the Commons "at dusk" photo position (91.8, 44.7, heading 311°) | way 710696944 | dusk |

Audit F3: the model blocks the pagoda view from the upper Yasaka-dōri / Ninenzaka junction (x > ~135 m), which is unresolved. All hero cameras that feature the pagoda are therefore west of x = 130 m: (a) x −79, (e) x 91.8, (d) x 118.

## 7. Web export (`kit_export.py` → `web/assets/world_art.glb`)
Y-up, extras on, no normals (flat shading). Textured buildings (Priority 2 and 3) carry one UV layer `WebUV` as TEXCOORD_0: facade faces use FacadeUV (u = bays, v = metres above the wall base) and roof faces use RoofUV (u = metres along the eave, v = metres up-slope). The web maps `web/assets/tex/` onto materials `W_Wall_Facade` and `W_Roof_Kawara` (see `docs/texture_library.md`); their base colour is a plaster or kawara fallback. Priority-4 massing uses two constant materials. Everything else has COLOR_0 vertex colours (normalised ushort). There are 4 small textures:
* terrain 1024² from the surface mask and the palette;
* ishidatami 512² and sett 256² repeat tiles;
* kit atlas 1024².

Names and prefixes are kept: `Terrain_`, `B_`, `LM_`, `Steps_osm`, `Paving_osm`, `Barrier_`, `Tree_osm…`, `TreeArt_`, `Shrub_art_`,
`Lantern_osm`, `StreetLamp_osm`, `Kit_<street>`. The props `collide` and `walkable` are kept, plus the provenance props.
* The Priority-2 kit is realised as simplified atlas cards, merged per street. Kit meshes have `collide=False`.
* Trees share 7 low-poly species meshes.
* Excluded: the hero pagoda and its PLATEAU placeholder (the web uses `pagoda.glb`), fog, the far DEM backdrop, fallen leaves, weeds, lights and cameras.

## Documented vs inferred vs artistic — summary
* **Documented / measured:** footprints, roof shapes and heights (PLATEAU), GSI-matched wall insets, street and stair geometry and surfaces (OSM), tree positions and tagged species (OSM), the stone lantern and street lamps (OSM), terrain (GSI DEM5A / DEM10B), and the facade vocabulary per street (evidence file).
* **Inferred:** 0.5 m wall insets, hisashi height, the per-bay arrangement of the kit, untagged tree species, default tree heights, paving extension to the building line, and ishidatami slab size (by eye in photos).
* **Artistic:** brushwork, palette push, weather (post-rain sheen, fog), lighting and grade, pots and andon, lamp-post positions, forest/garden fill, shrubs, weeds, fallen leaves, distant land cover and city lights, and pagoda flood positions.

## Eave overhang note
PLATEAU walls stand on the surveyed roof edge, and the accuracy audit (F1) rules out moving them from GSI data. Real eave depth therefore
appears only where it is evidenced as typical: the uniform 0.45 m set-back of traditional street fronts, plus the tiled hisashi, gutters and
the roof-slab and nokigawara edge geometry. Main roofs are never extended beyond the surveyed roof edge.
