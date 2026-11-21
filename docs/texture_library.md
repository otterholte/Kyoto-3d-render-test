# Realistic texture & facade library

The PLATEAU LOD2 buildings have survey-accurate footprints, heights and roof shapes but no surface detail. This
library adds that detail. It is a set of physically scaled PBR textures, and every one of them is generated from
real-scale source geometry or height fields, so nothing is a photo crop. Each texture comes in two versions:

| target | folder | resolution | format |
|---|---|---|---|
| Blender Cycles (4K stills) | `blender/textures/` | 2048² sets, 4096² facade atlas, 2048×1024 foliage atlas | JPG q92 (normals q95), foliage PNG + alpha |
| Three.js explorer (mobile-friendly) | `web/assets/tex/` | facade atlas 2048², foliage 1024×512, tileables 1024/512 (see `library.json` → `resolution`) | JPG q80–82, foliage PNG + alpha; total ≤ 8 MB |

On disk, the web set is 7.6 MB (budget 8 MB, enforced by `texture_library.web_pack`) and the Blender set is about 140 MB.
Most of the Blender size is high-quality JPG normal and ORM maps. Re-encode them at q85 if repository size matters.

To rebuild everything, run `/home/user/venv/bin/python blender/texture_library.py`. You can also rebuild only some parts with
`--only surfaces,facade,roof,foliage,web`. With `TEXLIB_SCRATCH` set, the intermediate EXR passes are kept, and setting
`TEXLIB_REUSE=1` then re-runs only the post-processing. Run the demo render with `python blender/texlib_demo.py`.

## Conventions

* **File names.** Each texture uses the pattern `<set>_albedo.jpg`, `<set>_normal.jpg`, `<set>_orm.jpg` and `<set>_emit.jpg`. The emit map is at half resolution. The foliage atlas uses `foliage_atlas_albedo.png`, whose alpha channel is the leaf coverage.
* **Albedo.** Albedo maps are sRGB base colour with no lighting baked in. There is one intentional exception. In facade modules, surfaces deep behind openings (shop interiors, rooms behind lattices) have a depth-darkened albedo. A flat wall cannot occlude itself, so this fakes the indoor light falloff (it is *artistic*).
* **Normal.** Normal maps are **tangent space, OpenGL convention: R = +u (right), G = +v (up), B = out**. Blender's Normal Map node and Three.js `normalMap` use this convention directly. Unreal and DirectX need the green channel flipped.
* **ORM.** In the ORM map, R = ambient occlusion, G = roughness and B = metalness, all linear. This is the glTF / Three.js `aoMap` + `roughnessMap` + `metalnessMap` packing. Three.js needs `uv1` for `aoMap`, or you can copy `uv` into it.
* **Emit.** The emit map is a greyscale emissive mask. It covers shop interiors, shoji, lamps and glazing behind which a room is lit. Multiply it by a warm colour (≈ `#ffb86b`). Use a strength of about 0.2–0.4 by day for shop interiors and about 3–8 at night.
* **Units.** Every tileable set has `size_m = [width, height]`, the physical size of one repeat. Write UVs in **metres** and divide by `size_m` (`make_material` does this) to get real scale.
* **Descriptors.** `library.json` exists in both folders and lists every set with its kind (`tileable`, `strip`, `trim`, `alpha_atlas`), category, size_m, tags, notes and files. `facade_atlas.json` and `foliage_atlas.json` describe the two atlases.

## A. Facade module atlas (`facade_atlas_*`, `facade_atlas.json`)

Each module is one bay. A full bay is **1 ken = 1.82 m** wide and a half bay is 0.91 m. Modules are modelled in Blender at
real scale (`texlib_facade.py`) in a frame where X runs along the wall, Y points up and +Z points out of the wall. Z = 0 is the
PLATEAU wall line. Posts (hashira, 120 mm) stand 15 mm proud of it, plaster is recessed 10–12 mm, degōshi lattices
sit 40–60 mm in front of it, and interiors lie 0.3–2 m behind it.

Each module is baked with an orthographic Cycles render of data passes, not lighting:
* AOV albedo, roughness, metalness, emission, plaster mask and wood mask
* the Normal pass, which equals the tangent-space normal because the camera looks straight down −Z
* AO (distance 0.35 m)
* Position (for the weathering)

Copies of the module are placed at x ± W so that AO and edges wrap across bay joints, and the atlas padding wraps in x.
Glazing is applied in post-processing so that the camera can see the room behind it. The post-process also adds:
* rain streaks below every protruding element on plaster
* grime under the eaves and splash dirt in the bottom 0.5 m
* silvering of low timber
* plaster stains and patch repairs

The atlas is 4096² at 300 px/m (3.3 mm/px) for Blender and 2048² at 150 px/m for the web, with 8 px (4 px on the web) of
padding. Modules are shelf-packed, and `facade_atlas.json` gives each module's:
* `uv_rect` [u0, v0, u1, v1] (bottom-left UV origin)
* `px_rect` (top-left pixels)
* `width_m`, `height_m`
* `kind`, `floor` (gf/uf) and `tags` (traditional/modern/temple/commercial/half/…)
* `has_emissive` and `evidence`

| module | size (m) | floor | content | evidence class |
|---|---|---|---|---|
| machiya_gf_senkoshi | 1.82×3.0 | gf | bengara degōshi, oyako slats 22 mm / 17 mm gap, shoji + glass doors behind | documented (district rules) + inferred dims |
| machiya_gf_senkoshi_dark / _half | 1.82 / 0.91 ×3.0 | gf | same in dark-stained timber | observed |
| machiya_gf_shop_open, _shop_open_b | 1.82×3.0 | gf | open front, display platform, shelves of generic goods, short noren (甘味 / plain), kanban (御土産, generic word) | observed (photos); goods/text generic |
| machiya_gf_noren_entrance | 1.82×3.0 | gf | recessed glazed sliding door, indigo noren (generic 茶 crest), side lattice | observed; crest generic |
| machiya_gf_glazed_doors | 1.82×3.0 | gf | four glazed wooden sliding doors with kick boards, short wave noren | observed |
| machiya_gf_plaster_base / _half | 1.82 / 0.91 ×3.0 | gf | ochre plaster above a board skirting; full bay has an inuyarai | observed; inuyarai *inferred* on the slopes |
| machiya_gf_itabari / _half | 1.82 / 0.91 ×3.0 | gf | vertical dark board wall with battens | observed |
| modern_gf_shopfront | 1.82×3.0 | gf | aluminium + glass, lit shelves, sign band (おみやげ, generic) | observed (Yasaka-dōri west) |
| modern_gf_entrance | 1.82×3.0 | gf | tile cladding, aluminium door | generic |
| temple_dobei | 1.82×3.0 | gf | stone base, ochre earthen wall with 5 sujibei lines, tiled coping | inferred (generic temple vocabulary) |
| white_plaster_timber / _vermilion | 1.82×3.0 | gf | white shikkui between dark or vermilion (#c0503a-like) posts and nuki | observed (Kōshin-dō) |
| kura_white_namako | 1.82×3.0 | gf | white kura wall with a namako-kabe dado | observed (white kura); namako generic |
| board_fence_itabei | 1.82×2.4 | gf | board fence, plaster band, tile coping, rubble plinth | observed (Yasaka-dōri east) |
| machiya_uf_mushikomado (+_ochre) | 1.82×2.4 | uf | sōnurigome plaster, 1.3×0.57 m mushiko-mado with plaster bars | documented (district rule); use sparingly |
| machiya_uf_window_lattice / _half | 1.82 / 0.91 ×2.4 | uf | glazed + shoji window behind a wooden lattice | observed |
| machiya_uf_glazed_railing | 1.82×2.4 | uf | glazed sliding windows, sudare, wooden railing | observed |
| machiya_uf_plaster (+_ochre, _half) | 1.82 / 0.91 ×2.4 | uf | plaster between posts with a nuki | observed |
| modern_uf_window | 1.82×3.0 | uf | nichōgake tile cladding, aluminium sash, curtain | generic |

The storey heights follow the evidence. The ground floor runs 0–3.0 m: openings up to the kamoi at 2.05 m, then a plaster
band, then a beam at 2.8 m where the hisashi attaches (PLATEAU has no hisashi; the measured range is 2.7–3.2 m). The
upper floor runs 0–2.4 m, a low tsushi-nikai with the floor beam at the bottom and the eave plate at the top. The UV helper stretches the
upper storey to the building's real eave height, clamped to 1.9–3.4 m.

**Hisashi are not in the textures.** A 0.9 m pent roof cannot be faked on a flat wall, so add it as geometry and give it the kawara
material. `texlib_demo.py` shows a minimal version.

### Using the atlas
In Blender, call `make_facade_material()` and then `assign_facades(obj, attrs)`. The shader does the following for each pixel:
* It reads `FacadeUV`, where u counts bays and v is metres above the wall base.
* It picks the storey from the attributes `fac_h` (gf_h, uf_h, n_upper).
* It picks the module rect from `fac_gf`, `fac_gf_alt`, `fac_uf`, `fac_uf_alt` and `fac_top`. A per-bay white-noise hash and `fac_p` choose the variants.
* It maps `fract(u), v_in_storey` into the rect.

In **Three.js**, do the same in `onBeforeCompile`:
`atlasUV = rect.xy + fract(uv) * (rect.zw - rect.xy)`. Use `textureGrad` with the unfracted derivatives, or bias the LOD, to avoid the
1-pixel mip seam at bay joints. The 4 px padding covers bilinear filtering and mip levels 0–2.

## B. Roofs

| set | size_m | how |
|---|---|---|
| roof_kawara_sangawara | 2.120 × 2.115 (8×9 tiles) | Real J-tile geometry in Blender (`texlib_roof.py`), Cycles passes, tileable. Sizes are those of the J-type "53A" sangawara: 265 mm working width × 235 mm working length, about 16 tiles/m², the common Japanese size. Each tile rides 22 mm proud on the course below, which gives a contact-shadow course line. *documented size class / generic per building* |
| roof_kawara_hongawara | 2.10 × 2.16 | Temple hongawara: a 0.30 m column pitch (hiragawara channel plus marugawara Ø150), 0.27 m marugawara courses and 0.09 m hiragawara steps. *generic* |
| roof_kawara_eave (strip) | 2.12 × 0.53 | First courses plus round eave-tile bosses, with no onigawara. v = 0 is the eave line. Tiles in u only. |
| roof_kawara_ridge (strip) | 2.12 × 0.53 | Five noshi-gawara layers plus a kanmuri cap, modelled upright and rotated into a 24° roof plane (the evidence median pitch). v = 1 is the ridge line. |
| roof_copper_patina | 1.8 × 1.8 | Hira-buki copper plates 0.30 × 0.18 m with verdigris and run-off. *generic temple* |
| roof_metal_seam | 1.82 × 1.82 | Galvalume standing seam every 0.455 m. *modern, generic* |
| roof_cement_slate | 1.82 × 1.82 | Cement / colonial slate in 0.182 m rows. *modern, generic* |

Kawara colour starts from the observed `#7d8085` (sunlit) and drops to an albedo of about `#6e7175`. Variation between tiles is subtle (±2.5 %), with a few replaced darker tiles. The post-process adds moss and lichen in the troughs and along the course lines, plus pale bloom streaks.

`apply_roof_uvs(obj)` groups coplanar roof faces. For each plane it writes `RoofUV`: u is metres along the eave (horizontal), v is metres up-slope from the
plane's lowest point, and (u, v, n) is right-handed. It also writes the corner attribute `roof_ridge_dist`. `make_roof_material()` then blends the eave strip where v < 0.53 m
and the ridge strip where ridge_dist < 0.53 m. Flat roofs get world-XY UVs and no strips.

## C. Ground (numpy height fields at real scale, `texlib_surfaces.py`)

| set | size_m | notes / evidence |
|---|---|---|
| ishidatami_granite | 2.4 × 2.4 | Granite slabs about 0.30 × 0.45–0.85 m in running bond, 10 mm joints, rough-flamed, mm-scale mineral speckle, per-slab tilt, worn arrises, grime. Rows run along u, so map u across the street. Slab size is *observed* (about 0.3 × 0.6 m by eye) and the colour is *observed* `#a9a39a`. |
| setts_granite | 1.6 × 1.6 | Rough-flamed granite setts about 0.10 × 0.16–0.24 m with domed tops (OSM `surface=sett`, colour *observed* `#8a857a`). The size is *inferred*. |
| asphalt_worn | 4 × 4 | Aggregate binder, darker patch repairs, tar-sealed cracks, oil stains and a worn white edge-line remnant at u = 0.30–0.45 m. Put u = 0 at the road edge. |
| gravel | 1 × 1 | About 3500 stamped pebbles 8–30 mm (temple precincts, roadside). |
| earth_moss | 2 × 2 | Packed earth with grit and moss in the damp hollows. |
| kerb_granite | 2.4 × 0.6 (strip) | Granite kerb blocks 0.6–1.0 m long. v 0–0.4 is the top face and 0.4–0.6 the street face. |
| stone_steps_trim | 2.4 × 1.2 (trim) | Trim sheet bands, measured in metres from the bottom of the texture: riser 0–0.20, nosing 0.20–0.24, tread 0.24–0.66, mossy riser 0.66–0.86, mossy tread 0.86–1.20. Riser and tread sizes are *not verified* (evidence notes a single source giving a riser of about 14.5 cm), so the bands are generous. |

## D. Misc + foliage

* **timber_planks_weathered and timber_planks_bengara** (2.4 m): vertical boards 0.18–0.27 m wide with 4 mm gaps, cupping, grain and silvering.
* **plaster_lime / _ochre / _cream / _earth** (2 m): trowel undulation, sand grain, straw fibres in the earth plasters, hairline cracks and grime. The colours are the *observed* `#e6d6b0` and `#c8a878`, reduced to albedo.
* **ishigaki_mossy** (3 m): nozura-zumi boulders with mossy joints (*observed* on the Sannenzaka stair and Yasaka-dōri east).
* **bamboo_fence_kenninji** (1.8 m): split bamboo, oshibuchi bars at 0.3, 0.9 and 1.5 m, and black shuro rope ties (*generic*).
* **bark_pine** (1 m): kuromatsu plate bark (*generic*).
* **foliage_atlas**: a 4×2 grid of leaf cards, each with `uv_rect`, `size_m` and its pivot at the bottom centre:
  * maple_autumn and maple_green (Acer palmatum, leaves 5–7 cm, 0.5 m card)
  * pine_needles (Pinus thunbergii tufts, 0.6 m)
  * cherry_blossom and cherry_leaf
  * shrub_azalea and shrub_box
  * bamboo_leaves (0.8 m)

  The albedo carries alpha coverage, colour is bled into the transparent pixels so mipmaps have no dark halos, and each leaf gets its own tilt in the normal map. This is botany-generic. The species follow the area's street trees.

## Helper API (`blender/materials_textured.py`)

```python
make_material(name, set_name, uv_scale=None, tint=None, uv_map="UVMap", normal_strength=1.0, emit_strength=0.0)
    # uv_scale=None: UVs are metres -> repeats every size_m;  float/(su,sv): explicit multiplier
make_facade_material(name="TX_Facade_Atlas", emit_strength=0.0)
make_roof_material(name="TX_Roof_Kawara", field="roof_kawara_sangawara", eave="roof_kawara_eave",
                   ridge="roof_kawara_ridge", tint=None, use_strips=True)
apply_wall_facade_uvs(obj, facade_assignments, wall_pred=None, base_z=None) -> [group info]
    # facade_assignments: dict or callable(group_info)->dict(gf, gf_alt, uf, uf_alt, top, gf_half, uf_half,
    #                     p_gf_alt, p_uf_alt, gf_h, uf_h, n_upper, seed)
assign_facades(obj, building_attrs=None, streets=None, street_dist=8.0) -> [group info]
apply_roof_uvs(obj, roof_pred=None) -> [planes]
classify(attrs) -> "traditional" | "modern" | "temple";   facade_plan(...);   load_streets();   ensure_slots(obj, wall, roof, plinth)
```

`assign_facades` groups wall faces into wall planes, using azimuth (±4°) and plane offset (±0.2 m). For each plane:
* **u**: the plane is fitted with a whole number of bays, so the bay width is stretched by at most ±25 % and no module is cut.
* **Half-bay modules**: planes shorter than 0.7 bay use the half-bay modules.
* **Street-facing test**: the plane centre must be within 8 m of an OSM centreline and its outward normal must point at it.

Module choice is deterministic: the CRC of `plateau_id` + plane index picks from weighted lists.
* **Structure.** The PLATEAU code is checked against `data/raw/plateau/codelists/BuildingDetailAttribute_buildingStructureType.xml`. **601 = 木造・土蔵造 (wood / earthen storehouse)**, 602 = SRC, 603 = RC, 604 = steel, 605 = light steel, 606 = masonry, 610 = non-wood and 611 = unknown. In `buildings.json` the structure is empty, so the demo fills it from `docs/evidence/building_evidence.json` by matching centroids.
* **Usage.** Usage codes follow `Building_usage.xml`: 402/403/404/413/414 are commercial or mixed. 461 (unknown) is also treated as commercial on these shopping streets.
* **Classification.**
  * temple: the name contains 寺 / 院 / 堂 / 神社 / 宮 / 庵
  * modern: the structure is 602–606 or 610, or the building has ≥ 4 storeys, or it is ≥ 3 storeys and built ≥ 1970
  * traditional: everything else
* **Traditional street fronts.**
  * ground floor: shop / noren / senkoshi / itabari, with a 30 % per-bay alternate on walls longer than 4 m
  * upper floor: lattice / railing / mushiko / plaster, with a 25 % plaster alternate per bay and storey
* **Non-street walls** get itabari or plaster.
* **Gable triangles** above the last storey use the `top` module (plaster).

## Demo
`renders/texlib_demo_ninenzaka.png` is a 1280×720 render from local (153.6, 98) looking south along Ninenzaka, using the blockout camera
`Cam_Ninenzaka_South`. It covers 114 PLATEAU buildings within 140 m of the camera, of which the 14 nearest the Ninenzaka centreline are listed
in the run log. They get the textured facades and roofs, plus simple hisashi on street-facing traditional fronts. The ground mixes ishidatami, asphalt, gravel and earth according to the
existing surface mask, and retaining walls get ishigaki. The `.blend` file is opened read-only and never saved.

## What is evidence-based vs artistic
* **Evidence-based:**
  * bay width 1.82 m (ken)
  * hisashi zone 2.7–3.2 m, low upper storey, 24° pitch
  * documented district vocabulary: degōshi / sen-koshi, mushiko-mado, bengara, kawara, plaster walls
  * observed colours (plaster `#e6d6b0` / `#c8a878`, timber `#5a3418`, kawara `#7d8085`, granite `#a9a39a`, setts `#8a857a`, vermilion `#c0503a`), reduced from sunlit samples to albedo
  * ishidatami slab size (by eye), board fences, white kura, inuyarai (Ishin-no-michi)
* **Industry-standard / documented size classes:** sangawara 53A (265 × 235 mm working size) and hashira 120 mm.
* **Generic / artistic:**
  * all weathering (streaks, moss, lichen, grime)
  * lattice slat spacing, noren designs (generic crest and the generic words 茶 / 甘味 / 和 / 御土産 / おみやげ, with no real shop names or logos), goods on shelves
  * hongawara proportions, temple dobei sujibei lines, modern cladding
  * leaf cards, gravel, asphalt details, interior depth-darkening
