# Yasaka Pagoda hero model: dimension record

**Model:** `blender/hero_pagoda.py` → `build_pagoda(collection=None, detail="high"|"web")`. The root empty is `LM_Yasaka_Pagoda_HERO`.

**Outputs:**
* `blender/assets/hero_pagoda.blend`: pagoda only, collection `Yasaka_Pagoda_HERO`, for linking.
* `web/assets/pagoda.glb`: detail `web`, Y-up.
* `renders/hero_pagoda_*.png`: check renders.

**Spec used:** `docs/evidence/yasaka_pagoda_spec.json` (research workstream), plus the lead's decision of 2026-11-20 on total height.

## Confidence classes

| class | meaning |
|---|---|
| measured | Taken from PLATEAU 2025 CityGML (bldg_2b477621-2b5c-480b-a960-d2b3972db237 / 26100-bldg-489160), OSM way 371717416 or GSI DEM5A. |
| documented | Stated in a published source. |
| observed | Seen in a cited CC-licensed Wikimedia Commons photo. |
| estimated | Pixel ratios from Commons photos, scaled by a measured dimension. |
| inferred | Typical wayō five-storey pagoda practice. No direct evidence for this building. |

## Placement

| item | value | class | source |
|---|---|---|---|
| plan centre (local x, y) | **(9.38, 83.34)** | measured | Midpoint of the OSM centroid (9.67, 83.46) and the PLATEAU roof-edge centroid (9.09, 83.22). These two are 0.63 m apart. |
| plan rotation | **+1.4°** CCW from grid east | measured | Minimum rotated rectangle: OSM 1.94°, PLATEAU 0.95°. Range 0.9–1.9°. |
| ground / base z | **61.03 m T.P.** | measured | PLATEAU LOD2 GroundSurface. DEM5A at the centroid is 61.4 m. The terrain under the footprint is 60.8–61.6 m. |
| eave outline check | model lowest eave vs PLATEAU roof edge: area 216.9 / 229.2 m², **IoU 0.94**, Hausdorff 0.69 m | measured | Computed in the build check. |

## Overall height

| item | value | class | source |
|---|---|---|---|
| **total height incl. sōrin** | **38.8 m** (tip at 99.83 m T.P.) | documented + measured | NDL Collaborative Reference entry 1000061716 gives 総高 38.8 m. PLATEAU measuredHeight 28.7 m is the top-roof apex. Photo sōrin ratio. Lead decision. |
| top roof apex | 28.7 m | measured | PLATEAU measuredHeight. The roban top sits at about 28.4 m. The tile surface meets the roban at 27.6 m (inferred). |
| sōrin (roof top → tip) | 11.2 m incl. roban; 10.1 m above the PLATEAU apex | estimated | 2.3–2.5 eave spacings in photos. |
| popular figure 46 m | **not used (disputed)** | documented | OSM `height=46` and tourist sites. A 46 m pagoda would need about 19.6 m lowest eaves or a 17 m sōrin. Both are contradicted by the 15.1 m PLATEAU roof outline and by the photos. Stored as `popular_height_m_disputed` in the `evidence` property. `build_pagoda(height_basis="documented_46m")` scales the model uniformly if the popular figure is ever wanted. |

## Per-storey dimensions

Heights are in metres above the 61.03 m ground. The body width is the column-centre square. The eave span is measured corner tip to corner tip. The "eave top" is the top of the eave edge at mid-face.

| storey | body width | class | eave span | class | eave top | class | balcony floor | wall (floor→head-tie top) |
|---|---|---|---|---|---|---|---|---|
| 1 | 6.40 | documented (alt. 5.5) | 15.10 | measured (PLATEAU 15.31 × 14.96) | 8.30 | measured (PLATEAU LOD2 step 8.29) | platform 1.00 | 5.48 (derived) |
| 2 | 6.08 | estimated | 14.35 | estimated | 12.20 | measured + estimated (PLATEAU 12.23) | 9.41 | 1.6 (derived) |
| 3 | 5.76 | estimated | 13.60 | estimated | 16.10 | measured + estimated (16.07) | 13.31 | 1.6 |
| 4 | 5.45 | estimated | 12.85 | estimated | 20.00 | measured + estimated (20.47) | 17.21 | 1.6 |
| 5 | 5.13 | estimated | 12.10 | estimated | 23.90 | measured + estimated (24.32) | 21.11 | 1.6 |

* **Eave spacing 3.9 m** (estimated). It comes from the photo ratio of eave spacing to eave width, scaled by the measured 15.1 m. PLATEAU's stepped tiers are 3.84–4.40 m apart.
* **Taper about 5 % of the lowest eave per storey** (estimated). Photo widths for the 5th : 4th : 3rd eaves are 415 : 440 : 465 px (*Yasaka Pagoda (24922466195).jpg*). The body is about 0.42 × the eave span.
* The wall heights are **derived**. They follow from the measured eave heights minus the inferred bracket, rafter and roof-rise depths below. The tall first storey is a direct consequence of the measured 8.3 m first eave.

## Components

| element | modelled value | class | source |
|---|---|---|---|
| storeys / plan | 5 storeys, square, 3 × 3 bays | documented | Designation text 三間五重塔婆、本瓦葺 (souda-kyoto.jp, kyoto-design.jp). |
| style | pure wayō | documented | Spec `style`. |
| stone platform (kidan) | 9.4 m square, 1.0 m high; cap stones, face slabs, base course; 0.65 m buried skirt | inferred | Spec `base_platform`. Mostly hidden behind the street fence. |
| platform steps | four sides, 4 risers, 2.1 m wide | inferred | Typical kidan. Steps from the precinct gate are observed. |
| columns | round; Ø 0.44 m (storey 1) → 0.32 m (storey 5) | inferred | — |
| front of each storey | central plank double doors with battens and bronze studs; renji lattice windows over plank dado | observed (storey 1–2) / inferred (3–5) | *Kyoto Pagoda.jpg*, *塔の下商店街（八坂の塔）*. |
| white plaster | small wall under the head tie and between bracket blocks | observed | *Kyoto Pagoda.jpg*, *Yasaka Pagoda (24922466195).jpg*. |
| bracketing | three-step (mitesaki) sets on every column, tail rafters (odaruki), diagonal corner sets, intercolumnar struts (kentozuka), continuous tie-beams, purlin at 1.45 m projection | observed (multi-step) / inferred (layout, 1.45 m) | *Gion - Nineizaka (48923269328).jpg*, *Kyoto Pagoda.jpg*. |
| bracket set height | ×1.35 on storey 1, ×0.84 on storeys 2–5 (stack 1.78 / 1.11 m) | inferred | Fitted between the measured eave heights. |
| rafters | two tiers (base + flying), parallel, pitch 0.27 m, 0.105 × 0.13 m; hip rafters | observed (two tiers) / inferred (pitch, size) | *3D photo-cross view … panoramio.jpg*. |
| roof | hongawara: stepped flat-tile courses 0.30 m, round-tile rows at 0.27 m pitch, tomoe end discs, kioi beam | documented (本瓦葺) / observed (end discs) / inferred (pitches) | — |
| roof curve | concave profile (exponent 1.45; top roof 1.75); corner lift 0.55 m; plan kick 0.28 m | observed (soft upturn) / estimated (values) | *150124 At Yasakakamimachi … 02n.jpg*. |
| roof rise (roofs 1–4) | 0.95 m from eave top to the upper balcony | estimated | Most of it is hidden behind the eave lips in frontal photos. |
| eave edge thickness | 0.40 m (fascia + tile edge) | inferred | — |
| hip ridges | tiled ridge 0.34 × 0.36 m with round cap; onigawara and toribusuma at the lower end | observed | *Gion - Nineizaka (48923269328).jpg*. |
| wind bells (futaku) | 20 in total, one under each roof corner, 0.31 m bell + wind plate | observed | *Kyoto Pagoda.jpg*, *Gion - Nineizaka (48923801861).jpg*. |
| balconies | storeys 2–5: 0.78 m deep, kumi-kōran railing 0.72 m high with upturned corner rails; storey 1 has none | observed (presence) / inferred (sizes) | *150124 … 02n.jpg*, *Yasakanoto Tower of Hokanji Temple.jpg*. |
| sōrin parts | roban 1.7 m square × 0.85 m; fukubachi Ø 1.1 m; lotus ukebana; **9 kurin rings** Ø 1.1 m at 0.66 m pitch with small bells; 4 openwork suien panels about 1.5 m; ryūsha; hōju; spike | observed (9 rings, silhouette) / estimated (proportions from the crop of *Yasaka Pagoda (24922466195).jpg*) | — |
| colours | timber #2e2420 (unpainted, weathered dark brown-black, **no vermilion**); tiles #7f8279; sōrin #504c43 dark bronze with patina; plaster #e8e2d4 (toned down) | observed | Spec `colours` (median pixel samples). |

## Collision proxy

`LM_Yasaka_Pagoda_COLLIDER` has two boxes:

* the platform, 9.6 m square;
* the storey-1 body, 6.84 m square, up to the first bracket zone.

It carries `collide=True` and `collider_for`. It is hidden in renders and invisible to the camera and shadows.

## Triangle counts

* `high`: 229,728 triangles.
* `web`: 47,472 triangles, with 27 nodes under `LM_Yasaka_Pagoda_HERO`.
  * 7 PBR base-colour materials named `PAG_*_web`, multiplied by the `COLOR_0` per-element tint.
  * Hidden top and inner faces are dropped.
  * Rafter and round-tile pitch is doubled.
  * File size 2.40 MB.

## Inferred or unverified

* The **38.8 m total height** is a documented figure chosen by the lead. The popular 46 m figure is disputed and recorded.
* The **first-storey width** has two published values, 6.4 m and 5.5 m. No official survey (修理工事報告書) was found.
* **Eave heights** come from PLATEAU's generalised stepped LOD2 model. It is unclear whether its tier tops are eave lips or roof surfaces. The model treats them as the top of the eave edge.
* The following are inferred from typical wayō practice:
  * kidan size and height, and steps on four sides;
  * column diameters;
  * bracket projection (1.45 m) and bracket size;
  * rafter and tile pitches;
  * eave-edge thickness and plan kick;
  * balcony depth and railing height;
  * bracket-set heights and the resulting wall heights;
  * the roof rise of roofs 1–4.
* **Sōrin part proportions** were read from a single photo crop. Whether the hōju and suien are gilded is unverified; the photos show dark metal.
* **Not modelled:** the lightning conductor cable (observed), the interior, floodlights and the precinct fence. The fence belongs to the street and walls workstream.

## Photos used

All photos are Wikimedia Commons; licences and geotags are in `docs/references/commons_geotagged.json`:

* *150124 At Yasakakamimachi Kyoto Japan01n.jpg* (663highland, CC BY 2.5)
* *Yasaka Pagoda (24922466195).jpg*
* *Kyoto Pagoda.jpg*
* *Yasakanoto Tower of Hokanji Temple.jpg*
* *Gojunoto Tower (Yasaka Tower) of Hokanji Temple from Sanneizaka.jpg*
* *Yasaka no Tō.jpg*
* *八坂の塔 - panoramio.jpg*
* *JP-Kyoto-Tower-Of-Hokan-Ji(Temple).jpg*
* *Hokan-ji, Goju-no-to (Five-storied Pagoda) -1 (March 2016) - panoramio.jpg*
* the 3D photo-cross view (panoramio)
* the photos cited in `yasaka_pagoda_spec.json`
