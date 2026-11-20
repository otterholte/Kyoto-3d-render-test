# Building & street evidence: Higashiyama / Yasaka box

Machine-readable data is in `building_evidence.json`: every item there has a confidence class and a source, and
it lists 123 street-fronting buildings with their OSM way, PLATEAU ID, height, storeys, eave height, pitch and ridge
orientation. The pagoda spec is in `yasaka_pagoda_spec.json`, and the photo records are in `../references/commons_geotagged.json`.

Coordinates use the local scene frame (x = east, y = north, metres from the box centre; see `data/processed/boundary.json`).

## Confidence classes

| class | meaning |
|---|---|
| **measured** | PLATEAU CityGML attributes or LOD2 geometry, or OSM traced geometry and tags |
| **documented** | published source with a URL. JP sites were readable only through web-search snippets in this sandbox, so treat them as "cited, not re-read" |
| **observed** | seen in a cited CC-licensed Commons photo (file title given), by eye only |
| **inferred** | typical Kyoto machiya or temple vocabulary, no direct evidence |

## Key numbers for builders (measured, PLATEAU LOD2 / attributes)

The statistics cover buildings within 6 m of each OSM street centreline. "Eave" is the lowest sloped main-roof face
above ground. PLATEAU LOD2 does **not** model hisashi, so take the 1F pent-roof height from the photos (about 2.7–3.2 m, *inferred*).

| segment (OSM ways) | n | height median (p10–p90) m | main eave median m | pitch median ° | storeys (known) | ridge: hirairi / tsumairi | structure |
|---|---|---|---|---|---|---|---|
| Yasaka-dōri west, Higashiōji→Kōshin-dō (24516359) | 28 | 9.4 (7.0–11.8) | 6.5 | 24.2 | 2F×15, 3F×8, 1F×2 | 16 / 8 | 20 wood, 5 steel, 3 unk.; 14 % flat roofs |
| Yasaka-dōri east, pagoda→Ninenzaka (710696944) | 31 | 9.7 (3.8–11.4) | 6.2 | 24.2 | 2F×16, 1F×2 | 16 / 4 | 16 wood, 2 steel, 13 unk. |
| Ninenzaka (30913263, 30882783, 550360170) | 17 | 8.1 (7.2–9.3) | 5.7 | 24.6 | 2F×7, 1F×1 | 10 / 4 | 7 wood, 10 unk. |
| Sannenzaka (526198271, 1569088146/7, 179116810, 1251544286) | 35 | 9.7 (7.4–12.1) | 7.0* | 24.1 | 2F×15, 1F×3 | 24 / 3 | 12 wood, 3 RC, 2 steel, 18 unk. |
| Ichinenzaka (157527438) | 12 | 8.6 (7.5–9.1) | 6.5 | 23.0 | 2F×7, 3F×1 | 8 / 1 | 8 wood, 4 unk. |

\* On stepped or sloping plots the eave value is biased high, because it is measured from the lowest ground point.

What this means for the models:
* The typical frontage is a 2-storey timber machiya: main eave at about 5.7–6.5 m, ridge at about 8–10 m, and roof pitch of about 24° (about 4.5-sun).
* Ridges run parallel to the street (hirairi) in most cases: about 2:1 on Yasaka-dōri west, 4:1 on Yasaka-dōri east and 6:1 on Sannenzaka. Ninenzaka has
  more street-facing gables (tsumairi) than the others, and the photos show cross-gables with round windows.
* Yasaka-dōri west is the most modern segment: 3–4 storey RC and steel blocks with flat roofs, utility poles, and
  lightbox signs.

## Documented district standards (Sanneizaka preservation district)
Source: Kyoto City, 産寧坂伝統的建造物群保存地区保存計画, https://www.city.kyoto.lg.jp/tokei/page/0000281761.html, *documented*.
* The district was designated a 重要伝統的建造物群保存地区 in 1976 (about 5.3 ha). The Ishibe-kōji area was added in 1996 (about 8.2 ha in total). About 65 % of its buildings are traditional.
* Rules for the むしこ造り町家 type: 真壁 timber frame, 中2階 low upper storey, **平入 (hirairi)**, **切妻 (gable) roof in 日本瓦 (grey clay tile)**, tiled 庇,
  漆喰 or plaster walls (Sanneizaka machiya often keep bare 土壁), **虫籠窓 on the upper floor**, 出格子 or 平格子 on the ground floor, and べんがら-stained timber.
  Meiji 本2階建 (full two-storey) and Taishō variants also occur.

## Paving and stairs
| segment | paving | stairs | class |
|---|---|---|---|
| Yasaka-dōri west | small granite setts / rough-flamed granite blocks in running bond, narrow side gutter (OSM `surface=sett`) | none | observed + measured (OSM tag) |
| Yasaka-dōri east | larger rectangular granite slabs (ishidatami) in running bond, granite kerbs (OSM `paving_stones`) | none | observed |
| Ninenzaka | granite slab ishidatami (about 0.3×0.6 m by eye), granite kerbs, gutters with grates | one flight at the south end: OSM `step_count=17` (width 4 m). JR West article says "about 15 steps" | documented / measured |
| Sannenzaka | granite slabs on the gentle north part, rough-flamed slabs near Kiyomizu-zaka, cobble strips in places | **46 steps** (OSM way 179116810 `step_count=46`, width 4 m, plus several published sources), in flights with landings | documented / measured / observed |
| Ishin-no-michi / Kōdai-ji Minamimon-dōri | asphalt with white edge lines | — | observed |

The photos show these retaining walls along the slopes: rough granite boulder walls (野面積み) on the Sannenzaka upper stair (east side) and
along Yasaka-dōri east, and a cut-granite ashlar base under Akebonotei.

## Façade vocabulary (observed, with photo references)
* **Upper storey:** cream to pale-ochre plaster (聚楽-like) between dark-brown posts and beams. Glazed wooden lattice windows; sudare
  blinds; wooden balcony railings on many 2F fronts; round 丸窓 windows in some gables.
  Photos: *150124 At Yasakakamimachi Kyoto Japan01n.jpg*, *Gion - Nineizaka (Ninenzaka) … (48924001697).jpg*, *Ninen-zaka 2018-04-14.jpg*, *Starbucks Coffee Kyoto Ninenzaka Yasaka Chaya.jpg*.
* **Ground floor:** open shopfronts with glazed wooden sliding doors, noren (indigo, pink or white cloth banners), and sen-koshi
  (fine vertical lattice) on closed bays. Vertical dark-stained board walls (板張り). A tiled hisashi runs at 1F head height.
  Photos: *Gion - Nineizaka (Ninenzaka) … (48924003837).jpg*, *(48923334473).jpg*.
* **Fences:** tall board fences (板塀) with a plaster upper band and tile coping on rubble plinths, mainly along Yasaka-dōri east (south side).
* **Street items:** black hanging lanterns with white panels; red paper chōchin; white wagasa umbrellas on a Ninenzaka façade;
  a wooden "二寧坂（二年坂）" sign on a granite post; old-style lamp posts with hexagonal glass heads; a green octagonal
  lantern near the pagoda bend; potted plants; bamboo screens. A bamboo **inuyarai** is seen on the Ishin-no-michi row
  (*A street in Kyoto (52411170563).jpg*). It is not clearly seen on the main slopes, so treat it as *inferred* there.
* **Mushiko-mado:** documented as a district rule. The available thumbnails do not show clear examples on the main
  slopes; most 2F fronts seen are glazed lattice windows. Place mushiko-mado sparingly (*documented / inferred*).

Colour starting points (*observed*, median samples that depend on lighting): plaster cream `#e6d6b0`, ochre `#c8a878`,
dark timber `#5a3418`, kawara `#7d8085`, granite slab `#a9a39a`, west-segment setts `#8a857a`.

## Landmarks
* **Yasaka Kōshin-dō (Kongō-ji)**, OSM 1316622873, local (-36, 60), on the south side of Yasaka-dōri:
  * Small tiled gable gate with its ridge parallel to the street. Posts, beams and doors are painted vermilion (`#c0503a`), with white beam ends and black iron straps. White plaster walls with vermilion side doors flank it.
  * A natural-stone stele 「庚申尊」 stands to the left and a granite 「夢見坂」 pillar to the right.
  * Dense multi-coloured **kukuri-zaru** clusters hang in front of the main hall and around a small green-roofed jizō shelter. The main hall is unpainted dark timber with white plaster (PLATEAU 26100-bldg-494505, 9.0 m).
  * All *observed*: *Yasaka Koshin-do on Yumemizaka of Kyoto.jpg*, *八坂庚申堂 - panoramio.jpg*, *Kongoji (Yasaka Kōshindō) Temple (51473114223).jpg*.
* **Hōkan-ji precinct**, OSM 371717423, about 35×43 m:
  * Street side: a timber slat fence between granite posts on a stone plinth, and a gate with stone steps.
  * Minor halls: 太子堂 (OSM 371717418) and 薬師堂 (371717424), about 3.3×4.1 m each, and 八坂稲荷大明神 (371717417).
* **Bunnosuke-chaya (文の助茶屋)**, local (53, 69): large red and white paper lanterns, 千社札 stickers (*observed*).
* **Starbucks Ninenzaka Yasaka Chaya**, local (152, 53): traditional ochre machiya with a 2F round lattice window (*observed*).
* **Akebonotei (明保野亭)** at the Sannenzaka stair: a tall black vertical signboard and a weeping willow (*observed*).
* **Kiyomizu Sannenzaka Museum**, OSM 550360162: white kura-style plastered building (*observed*).

## Yumemi-zaka naming
Commons uses "Yumemi-zaka" for the Yasaka-dōri slope **west** of the pagoda. A 「夢見坂」 marker stands at the Kōshin-dō gate (OSM
node 14102317343), and one guide (https://co-trip.jp/article/676277) calls the street west of the pagoda 夢見坂 (*documented*, weak).
The unnamed lane running north from Kōshin-dō (OSM 30882777) is a different street. It is not evidenced as Yumemi-zaka.

## Not evidenced / could not verify
* **Ishibe-kōji (石塀小路)** is outside the 400 m box, north of Kōdai-ji Minamimon-dōri.
* No licensed photo found in the box shows **Ichinenzaka** itself. Its façades are *inferred* from Ninenzaka.
* Stair riser heights and exact paving slab sizes are not verified. The quoted riser of about 14.5 cm comes from a single unverified site.
* Per-building koshi type and mushiko-mado presence cannot be matched to individual OSM ways from the available photos,
  because many Commons geotags are batch or approximate (see `geotag_note`).
