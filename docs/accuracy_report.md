# Phase 9: Independent accuracy audit

**Scope:** the 400 × 400 m Higashiyama reconstruction (Yasaka Pagoda). The audit covers the processed data, `blender/higashiyama_blockout.blend` and `blender/higashiyama_art.blend`. The art scene was audited from a snapshot taken at 22:57 on 2026-11-20 (file mtime 22:33, before the final-render job).

**Method:** every number below was re-derived from the raw sources with new audit code in `pipeline/audit/`. The builder's `pipeline/*.py`, `osm_parse.py` and `terrain_sample.py` were not imported. Scene geometry was read through `bpy`, and visibility was tested with `scene.ray_cast`, which includes collection instances. `docs/validation_report.md` was not trusted; where a builder claim was checked, the result is noted.

**Evidence classes used in this report:**

| class | meaning |
|---|---|
| measured | computed by this audit from raw data or scene geometry |
| documented | a published source |
| inferred | typical practice, or reasoned without a direct source |
| artistic | invented content, flagged as such in the scene |

## 1. Summary verdict

| # | check | method | result | verdict |
|---|---|---|---|---|
| 1 | Boundary (400 m metric box) | OSM way 371717416 re-parsed with lxml. Centroid computed in EPSG:6674. Corners inverted with pyproj. Geodesic side lengths on GRS80. | Pagoda centroid local (9.671, 83.458), identical to `boundary.json`. Corners agree to 4×10⁻⁸°. Sides are 400.04 m on the ground, which is the grid scale factor 0.999905. The S and N edges differ in latitude by 8×10⁻⁶°, so the box is grid-aligned and not built from degrees. JIS mesh is 52353692 only. | **PASS** |
| 2a | Footprint position and height vs raw PLATEAU GML | 674 in-box `bldg:Building` re-parsed (EPSG:6697 via 6668). Compared with the projected roof faces of every scene object carrying `plateau_id`. | All 674 are present in both scenes. No duplicates. Roof IoU median 0.9996 (min 0.956). Centroid offset median 1.4 mm (max 0.26 m). Top z matches to < 4 µm. | **PASS** |
| 2b | PLATEAU vs GSI 建築物の外周線 (BldL) | 3,355 BldL lines polygonized and matched by IoU. Vertex-to-line distances computed. | Vertex → BldL distance median 0.45 m, p90 1.38 m. Systematic shift GSI − PLATEAU dx −0.12 m, dy +0.41 m. Matched-polygon IoU median 0.72, because BldL merges row houses. | **PASS** |
| 2c | Inventory and in-box classification | Polygon centroid compared with the builder's vertex-mean centroid. | 9 buildings whose footprint is mostly inside the box are classed as backdrop (priority 4). 1 building is classed the other way. | **REVIEW** |
| 2d | Art-pass wall inset: did it shift buildings? | Wall cross-section at base + 1.5 m in blockout vs art, for all 126 P2 buildings. | Roofs are untouched (IoU 0.9994). Walls are moved: area −16 % median (max −64 %), wall centroid shift median 0.25 m (max 0.57 m). The inset is labelled "gsi measured" / `inset_detail_class=observed`, but the GSI data show no systematic eave offset (finding F1). | **FAIL** (provenance) |
| 3a | Streets represented, connectivity | All 180 OSM highway ways in the box. Surface mask sampled every 2 m. Steps meshes checked. Graph rebuilt. | 180/180 ways are on a paved mask class (3,439 samples, 0 on soil). 15/15 `highway=steps` have meshes. Components re-derived as [448, 19, 9, 1, 1, 1], identical to the builder's claim. | **PASS** |
| 3b | Widths vs GSI 道路縁 (RdEdg) | 148 perpendicular cross-sections, 128 of them with both edges. | Scene minus GSI bias / RMSE: Yasaka-dōri +0.07 / 0.56 m, Ninenzaka +0.10 / 0.97 m, Sannenzaka +0.06 / 0.54 m, Higashiōji +0.15 / 0.25 m. OSM centreline vs GSI mid-line offset median 0.18–0.44 m, p90 ≤ 0.75 m. | **PASS** |
| 3c | Obstructions on walkable centrelines | Upward rays from 0.05 to 1.9 m every 1 m (6,787 points). Point-in-wall test. | 44 m of footway/path centreline lies inside building walls (0.65 %); none on a named street. 13 head-height obstructions. | **REVIEW** |
| 3d | Stairs vs terrain | Tread top z at both ends vs terrain 0.6 m beyond the end. | Top ends are within ±0.15 m. 6 bottom ends sit 0.35–0.43 m above the street, about two risers. 3 flights have implausible risers (0.06–0.075 m). | **REVIEW** |
| 4a | Terrain vs raw DEM5A | 10,302 DEM5A pixel centres re-decoded. Terrain mesh sampled by BVH ray cast. | Bias −0.001 m, RMSE 0.077 m, max 1.33 m (stair carving). | **PASS** |
| 4b | Terrain vs PLATEAU DEM TIN, GSI contours and ElevPt | 2,500 TIN triangle centroids (mesh 52353692 TIN streamed from the 823 MB GML). 149 points on 1:25k contours. 1 ElevPt. | TIN: bias +0.13 m, RMSE 0.65 m, p95 1.53 m, max 4.5 m. Contours: bias +0.32 m, RMSE 1.96 m, within 1:25k accuracy. ElevPt: 51 m vs 51.83 m. | **PASS** |
| 4c | Building bases vs terrain | Terrain along each wall outline vs PLATEAU LOD1 base. | 39 buildings have terrain > 1 m above the PLATEAU base along their lowest wall (4 are > 2 m, max 2.25 m). The PLATEAU TIN agrees with the base for all but one. | **REVIEW** |
| 5a | Hero pagoda position, orientation and outline | Root transform plus mesh slices, vs OSM and PLATEAU. | 0.31 m from both centroids (OSM and PLATEAU are 0.63 m apart). Rotation 1.40° (OSM 1.94°, PLATEAU 0.95°). Lowest-eave hull vs PLATEAU roof edge IoU 0.946. | **PASS** |
| 5b | Pagoda total height 38.8 m vs 46 m | Own pixel measurement on a 163 m telephoto Commons photo, anchored on PLATEAU tiers. Web search. | Photo-derived height is 39.2–40.0 m (±1 m), which supports about 39 m geometrically. The cited document (NDL 1000061716, 総高 38.8 m) could not be retrieved or found. Published sources overwhelmingly say about 46 m. Scene metadata contradicts itself. | **REVIEW** |
| 5c | Kōshin-dō position | OSM way 1316622873 vs PLATEAU and scene. | OSM centroid (−35.6, 60.3). PLATEAU `bldg_6217f674` (196 m², 9.0 m) lies 99 % inside the OSM polygon and is present in `30_C_Koshindo_Central`. | **PASS** |
| 6 | Sightlines vs Commons photos | 16 photos with EXIF camera positions, snapped to the street evident in the photo. Ray casts to 4 pagoda tiers in both scenes. 6 side-by-side renders. 183-point street sweep. | 13/16 agree within ±15 m along the street. The 3 that disagree (plus 7 album duplicates) are all at the upper Yasaka-dōri / Ninenzaka junction: the model hides the pagoda east of x ≈ 135 m except from the south kerb. | **REVIEW** |
| 7a | Artistic flagging | Custom properties of all 3,627 empties and every mesh. | Every instance carries `artistic` or `detail_class`. The schema is inconsistent: kit pieces have no `artistic` boolean, hero meshes have no class, and paving is labelled "observed" although its widening is inferred. | **REVIEW** |
| 7b | Artistic content blocking streets | Instance positions vs OSM corridors and buildings. Horizontal ray casts across 148 sections at 0.5 m and 1.2 m. | No artistic object narrows any section inside the GSI road edges. Only weeds (17) and minor props stand in pedestrian corridors. | **PASS** |
| 7c | Artistic alteration of views | Blockout vs art visibility from the same eye points. | An artistic tree (`TreeArt_666214492_699`) hides the whole pagoda from the elevated NE viewpoint of a Commons photo. Art-pass crowns of *documented* trees hide 1–3 extra tiers on upper Yasaka-dōri. | **REVIEW** |
| 8 | Scale | GSI RdEdg / RdCompt, PLATEAU storeys, kit heights. | Higashiōji is 16.06 m edge to edge (GSI) vs 16.15–16.28 m in the scene; the carriageway is about 12.0 m. 2-storey machiya median 8.7 m. Hisashi at 2.96 m above the street (evidence 2.7–3.2 m). Units are 1 m. | **PASS** |
| 9 | Builder self-validation re-derived | Comparison of `validation_report.md` claims with this audit. | Connectivity, pagoda offset, step table, footprint agreement and the Yasaka-dōri sightline reproduce. The "×1.00 eave" result contradicts the later GSI-based inset (F1). The report predates the art pass. | **REVIEW** |

**Counts:** 11 PASS · 9 REVIEW · 1 FAIL. There are no critical findings.

## 2. Findings

Each finding gives its severity first. The checks in the "observed" column of the summary are measured unless stated otherwise.

### F1 (major): the art-pass wall inset re-shapes 126 surveyed buildings on a "measured" label the data do not support

**Measured:**

* `kit_arch.rebuild_p2` rebuilds the outer walls of all 126 Priority-2 buildings. The insets are per edge, from 0 to 1.2 m (mean per building: median 0.40 m).
* At 1.5 m above the base, the wall footprint loses a median 16 % of its area (p90 30 %, max 64 %).
* The wall centroid moves a median 0.25 m (max 0.57 m, `bldg_8bb1e246…` on Yasaka-dōri). Roof geometry is unchanged (roof IoU vs GML median 0.9994).
* The 536 Priority-3 buildings are untouched (0.000 m shift).

**The justification fails.** 231 edges are labelled `gsi:BldL … measured` and the objects get `inset_detail_class = "observed"`. The rule is that a GSI 外周線 lying 0.3–1.6 m *inside* the PLATEAU roof edge is read as the wall line under the eaves. Across all 674 in-box buildings, however:

* the nearest BldL line is **outside** the PLATEAU roof edge at 54 % of vertices and **inside** at only 39 % (median signed offset −0.11 m);
* there is a 0.41 m systematic N–S registration difference between GSI and PLATEAU;
* the builder's own validation found roof-edge area / ground area = ×1.00, so PLATEAU walls already stand on the roof edge.

Both GSI 1:2500 and PLATEAU outlines are photogrammetric. Their difference is noise plus registration (inferred). The rule therefore selects the inward tail of that noise and gives it a measured label.

**Consequence:** eave depth varies from 0 to 1.2 m between adjacent edges of the same building for no physical reason. 760 further edges get a uniform 0.5 m (labelled inferred, which is correct).

**Figure:** `docs/audit/04_footprints_walls_widths.png`, panels (a) and (b).

### F2 (major): the pagoda height is geometrically supported, but its documentary basis is unverified and the metadata contradicts itself

**Measured (this audit):**

* On *Yasaka-Dori - panoramio.jpg* (Koichi Shibata, CC BY-SA 3.0; camera on Yasaka-dōri about 163 m west, telephoto, near-level) the pixel rows are: finial 416, roban top 565, top-roof apex 577, eave 1 at 867.
* That gives sōrin / (apex − eave 1) = 0.51–0.56.
* Anchored on the PLATEAU LOD2 tiers (eave 1 at 8.3 m, apex at 28.7 m above the 61.04 m ground), the finial is at **39.2–40.0 m** (±1 m for tilt and edge definition).
* 46 m would need a sōrin of about 17 m, about 245 px instead of the 149–161 px observed.
* The PLATEAU tier spacing (about 4.0 m) agrees with the photo's eave rhythm: (apex − eave 1) = 4.7–4.9 eave spacings, against 5.1 in PLATEAU.
* The hero model is 38.80 m tall (tip at 99.83 m T.P.).

So **about 39 m is the geometrically consistent value**, and the model is within about 1 m of it.

**Documented:**

* The decisive citation is NDL Collaborative Reference 1000061716 (総高 38.8 m). It could not be fetched: crd.ndl.go.jp and ja.wikipedia.org are not reachable from this environment.
* A web search found no source giving 38.8 m for Hōkan-ji. Almost all published sources (operator and tourist sites, OSM `height=46`) give "約46 m", and describe it as third-tallest after Tō-ji and Kōfuku-ji.
* "38 m" is the published height of the **Daigo-ji** pagoda, so a mix-up cannot be excluded.

**Metadata conflicts:**

* `LM_Yasaka_Pagoda_PLATEAU_LOD2["hero_replacement"]` in the blockout says "PLATEAU height 28.7 m under-reads documented 46 m".
* The hero root, `docs/boundary.md` and `yasaka_pagoda_model.md` say that 46 m is disputed.
* The hero root labels 38.8 m as "documented + measured".

**Smaller geometric deviations:**

* Tiers 4 and 5 sit 0.47 m and 0.42 m below the PLATEAU LOD2 steps (20.0 / 23.9 m vs 20.47 / 24.32 m), because a uniform 3.9 m spacing replaced the measured steps.
* Position, orientation and lowest-eave outline all PASS (row 5a).

**Figure:** `docs/audit/06_pagoda_height.png`.

### F3 (major, unresolved): the upper Yasaka-dōri / Ninenzaka junction view of the pagoda is mostly blocked in the model

**Measured:**

* A street sweep on way 710696944 (`c_scene_probe.py`) and a 0.5 m lateral grid (`c3_junction.py`) show the pagoda's upper tiers visible from the centreline up to x ≈ 131 m.
* East of that, visibility shrinks to the southern 1–1.5 m of the street (2–3 tiers at x 137–143 m) and disappears at x ≥ 149 m. The occluder is `B_4005f62e` (PLATEAU), 8–13 m from the eye.
* *JP-Kyoto-Tower-Of-Hokan-Ji(Temple).jpg* (geotag 0.1 m from the centreline at x = 148.1 m), *Kyoto - Nineizaka (51472101182).jpg* and the 8-photo album *Gion - Nineizaka …* (all sharing one coordinate, at x = 143.4 m) all show the full upper pagoda down the street axis.

**Not decidable from the data available.** The album shares a single coordinate and the snap distances are 11–22 m, so geotag error is plausible. It is equally possible that `B_4005f62e`'s height or position, or the bend of way 710696944 at x 130–150 m, is slightly off.

This is the most-photographed view in the district, so it needs field verification.

**Figure:** `docs/audit/02_sightline_yasaka_dori_upper.png`.

### F4 (minor): boundary classification uses the vertex-mean centroid

`05_buildings.py` decides `in_box` by the mean of the roof-edge vertices. As a result:

* nine buildings that are 51–66 % inside the box are treated as backdrop: priority 4, backdrop material, no roof or wall pass. They are `bldg_2a10a754`, `2c931dc7`, `346874a0`, `3520ab3b`, `49e28fa0`, `6d4d6939`, `a140b193`, `e5c420c9` (on Higashiōji), and `fe0fe634`;
* `bldg_9c1a8a7c` (41 % inside) is treated as in-box.

Visible effect: half-built-looking buildings on the box edge, including two on the Higashiōji frontage.

### F5 (minor): stair ends and risers

**Measured:**

* The bottom treads of six flights sit 0.35–0.43 m above the street just beyond them, about two risers instead of one: `30882783` Ninenzaka 0.35 m, `179116810` Sannenzaka 0.35 m, `527257294`, `893851279`, `893851280` and `893851292`.
* Risers derived from terrain rise / OSM `step_count` are implausible for `893851294` (0.06 m) and `893851288` (0.075 m). The Ninenzaka flight is 0.222 m, which is steep. These come from the 5 m DEM smoothing short flights.
* All top ends match the terrain within ±0.15 m.

The carving of the terrain under the stairs is the cause of the 1.33 m maximum in check 4a (expected).

### F6 (minor): terrain stands above PLATEAU building bases on steep slopes

**Measured:**

* 39 in-box buildings have DEM5A-derived terrain more than 1 m above their PLATEAU LOD1 base at the lowest point of the wall outline: 4 are over 2 m, and the largest is `bldg_6c3bac3e` (108.7, −113.3) at 2.25 m.
* They cluster on the Sannenzaka slopes (x 100–180, y −180…−10).
* The PLATEAU TIN agrees with the bases (only one building is more than 1 m off). The 5 m DEM is smoothing terraced plots, which partly buries the ground-floor walls.

**Terrain vs PLATEAU TIN:**

* Overall RMSE is 0.65 m (slopes 0.85 m, Higashiōji 0.14 m).
* The largest residuals (+4.5 m) are a flat 68.8 m DEM5A patch inside the school building `bldg_e09f68c3` (x 17–62, y −23…−5). They are interior to the building and not visible.

### F7 (minor): obstructions on mapped walkways

**Measured:**

* 44 m of OSM centreline (footway, path, precinct way) lies inside building walls. The largest are `397245758` (9 m in `bldg_4215e5eb`), `1148998439` (8 m in `bldg_2e667e83`), `545016557`, `1550466023`, and the pagoda precinct way `371717425`.
* Head-height obstructions: the underside of `B_93246887` is 1.3–1.8 m above footways `545679620`, `545679621` and `545679623`. The art pass lowered this further: 10 hits in the art scene vs 4 in the blockout, from the roof slab and eave rolls. A documented maple canopy is at 1.4–1.7 m over steps `179116812` / `666214494`.
* None of these are on Yasaka-dōri, Ninenzaka, Sannenzaka, Ichinenzaka or Higashiōji. At 1.2 m height, none of the 128 sections is more than 0.5 m narrower than the GSI road width. At 0.5 m height, 4 Yasaka-dōri sections are, because of shop display tables and a retaining wall.

### F8 (minor): artistic content and labelling

**Measured:**

* The 924 instances in `55_Vegetation_Artistic` are all `artistic=True`. None stands in a building. Only weeds (17) stand inside a mapped street corridor.
* Kit pieces (2,428) carry `detail_class` (observed 1,040 / inferred 1,146 / artistic 242) but **no `artistic` boolean**. A consumer filtering on `artistic` alone misses 242 artistic pieces.
* "Observed" is assigned per street segment from the evidence file, not per facade, so it overstates how specifically a piece is evidenced.
* The 27 hero-pagoda meshes carry no class; it exists only on the root empty.
* Paving ribbons are `detail_class="observed"`, although they are widened to the building line by up to 3 m (inferred) and the slab pattern is artistic. The evidence string says so; the class does not.
* Artistic props in pedestrian way `550352948` (west of the pagoda): 5 andon, 2 lamp posts, 9 pots.
* `K_ShopFront` display tables (0.6 m deep, inferred or observed) extend up to 0.5 m inside the GSI road edge at 4 of 51 Yasaka-dōri sections, at 0.5 m height.
* `LM_Yasaka_Pagoda_PLATEAU_LOD2` stays in the art scene with `hide_render=True` but `collide=True`. Verify that exporters skip it, otherwise there is double pagoda collision.

**Figures:** `docs/audit/03_sightline_alley_and_elevated.png`. Row-7c details are in F9.

### F9 (minor): the art pass changes documented views

**Measured:**

* From the camera position of *法観寺八坂の塔 - panoramio - くろふね.jpg* (143.8, 190.4), the blockout shows tiers 3–5 and the sōrin. In the art scene the whole pagoda is hidden by `TreeArt_666214492_699`, an artistic tree about 4 m from the eye. The photo is elevated, so the photographer's exact eye height is unknown.
* On upper Yasaka-dōri (x 50–60 m), art-pass prototypes of OSM trees `5315756916`, `5315756917` and `5315712565` hide 1–3 more tiers than the blockout's 7 m default trees. Their position is documented, but the height is a 7 m default and the crown is inferred.
* The photos taken there (*Illuminated Yasakanoto Tower (Hokanji Temple) 2.jpg*, *Japan - Flickr - GregTheBusker (14).jpg*) show tiers 3–5 and the sōrin. The art scene shows only the tip at the snapped camera point (blockout: tier 5 and above).

### F10 (minor): scale notes

**Measured:**

* Higashiōji is 16.06 m edge to edge (21 GSI sections), against 16.15–16.28 m in the scene.
* GSI 歩道 lines put the carriageway at about 12.0 m (6.2 + 5.8 m) with about 2 m sidewalks. The scene paints all 16 m as asphalt, with no kerb or sidewalk.
* The PLATEAU mesh 52354602 (north of 35.0° N, local y > +244 m) was not downloaded, so the northern backdrop ring has no buildings. This is outside the box.

**Documented / inferred:** the pagoda platform (9.4 × 1.0 m) is inferred. No survey value is available, so it cannot be verified.

## 3. Sightline table (check 6)

* **Eye:** walkable surface + 1.6 m.
* **Targets:** the pagoda axis at eave 3 (16.1 m), eave 5 (23.9 m), apex (28.5 m) and tip (38 m).
* **Snap:** geotags were snapped to the street evident in the photo. The cameras of *Tower of Yasaka (Hokanji).jpg*, *法観寺八坂の塔 - panoramio.jpg*, *Gojunoto Tower … of Hokanji Temple at dusk.JPG*, *Japan - Flickr - GregTheBusker (14).jpg* and *At Kyoto 2024 169.jpg* fell inside buildings at the raw geotag.
* **Codes:** V = visible, - = blocked. The "±15 m" column gives the best number of the 4 tiers visible along the street within 15 m (blockout / art).

| photo (Commons, photo id) | snap (m), way | blockout | art | ±15 m | photo shows | agreement |
|---|---|---|---|---|---|---|
| *Yasaka-Dori - panoramio.jpg*, 244 | 0.4, 24516359 | VVVV | VVVV | 4/4 | tiers 2–5 + sōrin | yes |
| *Tower of Yasaka (Hokanji).jpg*, 238 | 11.2, 24516359 | VVVV | VVVV | 4/4 | full upper pagoda | yes |
| *法観寺八坂の塔 - panoramio.jpg*, 269 | 6.9, 24516359 | VVVV | VVVV | 4/4 | upper pagoda | yes |
| *Yasakanoto Tower of Hokanji Temple 2.jpg*, 246 | 26.6, 24516359 | VVVV | VVVV | 4/4 | full pagoda | yes (geotag 27 m off) |
| *At Kyoto 2024 169.jpg*, 6 (alley from Kiyomizu-michi) | 5.1, 157527424 | VVVV | -VVV | 4/4 | upper pagoda at alley end | yes |
| *Gojunoto Tower … of Hokanji Temple at dusk.JPG*, 44 | 7.8, 710696944 | VVVV | VVVV | 4/4 | full upper pagoda | yes |
| *青空 京都 2015 (31868548931).jpg*, 274 | 0.7, 710696944 | VVVV | VVVV | 4/4 | full upper pagoda | yes |
| *Kyoto (49071381327).jpg*, 197 | 1.5, 710696944 | VVVV | VVVV | 4/4 | upper pagoda | yes |
| *Yasaka no Tō.jpg*, 243 | 0.3, 710696944 | VVVV | -VVV | 4/4 | tiers 3–5 + sōrin | yes |
| *Gojunoto Tower … from Sanneizaka.jpg*, 45 | 9.0, 710696944 | -VVV | -VVV | 4/4 | tiers 2–5 | yes |
| *Illuminated Yasakanoto Tower (Hokanji Temple) 2.jpg*, 56 | 1.4, 710696944 | -VVV | ---V | 4/4 | tiers 3–5 + sōrin | partial (F9) |
| *Japan - Flickr - GregTheBusker (14).jpg*, 190 | 3.3, 710696944 | -VVV | ---- | 4/4 | tiers 3–5 | partial (F9) |
| *法観寺八坂の塔 - panoramio - くろふね.jpg*, 268 (elevated) | n/a | VVVV | ---- | n/a | tiers 3–5 + sōrin | art no (F9) |
| *Kyoto - Nineizaka (51472101182).jpg*, 199 | 22.1, 710696944 | ---- | ---- | 3 / 2 | full upper pagoda | **no** (F3) |
| *JP-Kyoto-Tower-Of-Hokan-Ji(Temple).jpg*, 189 | 0.1, 710696944 | ---- | ---- | 0 / 0 | full upper pagoda | **no** (F3) |
| *Gion - Nineizaka (Ninenzaka) …*, album of 8 (18, 19, 25, 26, 28, 29, 39, 40) | 11.6, 710696944 | ---- | ---- | 3 / 3 | full upper pagoda | **no** (F3) |

**Street sweep (183 points, 4 m apart; art scene; share of points where each target is visible):**

| street | eave 3 | eave 5 | apex | tip |
|---|---|---|---|---|
| Yasaka-dōri | 77 % | 88 % | 89 % | 90 % |
| Ninenzaka | 0 % | 0 % | 3 % | 0 % |
| Sannenzaka | 0 % | 0 % | 2 % | 9 % |

All Commons photos labelled "Ninenzaka" are in fact taken at or near the Yasaka-dōri junction. No photo evidences a view from Ninenzaka or Sannenzaka proper, so those streets cannot be checked.

**Side-by-side images** (photo on the left, 480 × 360 Cycles render of the blockout at 8 samples on the right):

* `docs/audit/01_sightline_yasaka_dori_lower.png`
* `docs/audit/02_sightline_yasaka_dori_upper.png`
* `docs/audit/03_sightline_alley_and_elevated.png`

## 4. What is measured vs documented vs inferred vs artistic

| item | class | basis |
|---|---|---|
| Building footprints, heights, roof shapes (blockout; art P3; art P2 roofs) | measured | PLATEAU LOD2, reproduced to mm |
| Art P2 wall positions | **inferred**, labelled observed/measured | F1 |
| Streets: alignment and connectivity | measured | OSM ±0.5 m vs GSI |
| Street widths | measured | PLATEAU road area (median section) or OSM tag; checked vs GSI |
| Paving extension to building line | inferred | labelled observed (F8) |
| Terrain | measured | DEM5A 5 m resampled to 2 m; carved under stairs (inferred) |
| Stairs: position and count | measured / documented | OSM `step_count` |
| Riser heights | inferred | DEM rise / count |
| Pagoda: position, rotation, eave-1 outline, tier heights 1–3 | measured | PLATEAU / OSM |
| Pagoda: tiers 4–5 heights | estimated | photo spacing |
| Pagoda: total height 38.8 m | measured + estimated | PLATEAU apex + photo sōrin (this audit: 39.2–40.0 m) |
| Pagoda: "documented 38.8 m" | unverified | F2 |
| Pagoda: details | inferred / observed | per `yasaka_pagoda_model.md` |
| Documented trees: position | measured | OSM |
| Documented trees: height | inferred | 7 m default (270 of 274 species inferred) |
| Machiya kit: piece type | observed / inferred | per street segment |
| Machiya kit: per-bay placement, pots, andon, lamp-post positions | artistic | — |
| Forest, bamboo, shrubs, weeds, fallen leaves | artistic | flagged |
| Backdrop land cover | artistic | — |
| Fog | artistic | — |
| Pagoda floodlight positions | artistic | — |

## 5. Recommended fixes (priority order)

1. **F1, wall inset.**
   * Stop deriving per-edge insets from GSI-vs-PLATEAU differences.
   * Either keep walls on the PLATEAU roof edge and model eaves only through the kit hisashi, or apply one documented street-front eave depth (inferred, uniform) to street-facing edges only.
   * Relabel `wall_inset_src` and `inset_detail_class` as `inferred`, and re-run the art pass.
2. **F2, pagoda height.**
   * Obtain the text of NDL 1000061716, or a 修理工事報告書 / 文化財 record (needs crd.ndl.go.jp reachable).
   * Until then, relabel 38.8 m as "measured (PLATEAU apex) + photo-estimated sōrin; total height 38.8 m adopted, 39.2–40.0 m audit estimate; 46 m published figure unreconciled".
   * Remove the contradictory `hero_replacement` text on the PLATEAU LOD2 object.
   * Restore the measured tier 4 and 5 heights (20.47 / 24.32 m).
3. **F3, junction view.**
   * Field-verify with a photo or street-level image whose position is known: Mapillary or KartaView, once reachable.
   * Check `B_4005f62e` (PLATEAU height and LOD2 roof) and the alignment of way 710696944 at x 130–150 m against GSI RdEdg.
   * Until then, do not place hero cameras east of x ≈ 130 m on that way. The `e_yasaka_dori_upper_west` camera is at x 91.8, which is fine.
4. **F4:** decide `in_box` by area fraction ≥ 0.5 (or by polygon centroid) and promote the 9 edge buildings to P3.
5. **F5:** set each flight's bottom z from the terrain at its foot after carving, enforce one riser at both ends, and clamp risers to 0.10–0.20 m (flagged inferred).
6. **F6:** lower the terrain to the PLATEAU base (or TIN) inside a 1 m band around walls where DEM5A is more than 0.5 m higher. Alternatively, use the PLATEAU TIN in built-up cells.
7. **F9:** keep the pagoda view corridors (all Commons viewpoints in §3) free of artistic trees, and move or remove `TreeArt_666214492_699`. Size documented-tree crowns conservatively, or from aerial-photo crown diameters.
8. **F8:**
   * Add `artistic` to every kit instance (derived from `detail_class`).
   * Add `detail_class` to hero meshes.
   * Label the paving width as inferred.
   * Keep the `K_ShopFront` table depth inside the GSI road edge.
   * Exclude the hidden PLATEAU pagoda from collision.
9. **F7:** check the 44 m of centreline inside buildings against the aerial photo. These are likely roofed passages or gates; tag them, or open the passages. Raise or tag the `B_93246887` underside.
10. **F10:** add Higashiōji sidewalks and kerbs from GSI RdCompt. Fetch PLATEAU mesh 52354602 for the northern backdrop.

## 6. Limitations

* **Unreachable sites:** crd.ndl.go.jp and ja.wikipedia.org could not be resolved. Downloading Commons thumbnails was refused (HTTP error page), so the photos used are the earlier research workstream's cached thumbnails (`scratchpad/refs/`, mapped by `scratch_ref_id`).
* **Geotag accuracy:** photo geotags are EXIF or Panoramio positions. Their 5–25 m error limits check 6.
* **Renders:** all renders are blockout views at 480 × 360, 8 samples, 2 threads, to stay clear of the concurrent final-render job.
* **Art scene changes:** the art scene was still being updated by another agent. Findings F1, F7, F8 and F9 refer to the 22:33 save.

## Appendix: audit code and outputs (`pipeline/audit/`)

Run in this order, with the venv Python:

1. `a1_boundary.py`
2. `a2_plateau_parse.py`
3. `b_dump_scene.py <blend> out/scene_{blockout,art}.pkl`
4. `a2_footprints.py`
5. `a3_streets.py`
6. `a4_prep.py`
7. `c_scene_probe.py <blend> {art,blockout}`
8. `a3b_centreline_buildings.py`
9. `a5_landmarks.py`
10. `a7_artistic.py`
11. `a8_scale_terrain.py`
12. `c2_photos.py <blockout> <art> <render_dir>`
13. `c3_junction.py <blend> art`
14. `d_figures.py <scratch_dir>`

The shared helpers are in `acommon.py`.

The JSON summaries and the intermediates (pickles and npz, about 22 MB) are in `pipeline/audit/out/`. The intermediates can be regenerated by running the scripts above.
