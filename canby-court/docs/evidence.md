# Evidence register — what is measured, documented, observed, inferred

Classes: **measured** (computed from GIS/raster data) · **documented** (public record: City
assessor-derived building layer, listing data) · **observed** (seen by a person on the 2022 City and
2024 County orthophotos, 5–7.5 cm) · **inferred** (rule of thumb) · **gap** (no evidence).

## Site-wide

| topic | class | evidence |
|---|---|---|
| footprints, parcels, street, sidewalks, curbs | measured/documented | City GIS (footprints 2019 edit). Street 26 ft curb-to-curb, asphalt (ACP), curb & gutter; 5 ft concrete (PCC) sidewalks both sides of Canby Ct; 6 curb ramps; hydrant at E end of Canby Ct; decorative HPS street lights |
| terrain | measured | 3DEP bare earth from 2006 lidar, 0.5 m resample. Validated: vs 20 GPS catch-basin rims mean −0.31 m, RMSE 0.38 m; vs City 2013-lidar 5-ft contours (4 906 samples) mean −0.23 m, RMSE 0.56 m. Ground falls east→west (~165 → 114 m over the context). Core mean slope 7.3°. Steepest yard ground: 3802's west embankment to 38th St (p90 27°, 32 % of lot > 15°) and the 3807/3811 rear terraces. |
| sledding run | measured | see below |
| trees | observed position/type; modelled or inferred height | 69 trees digitised in/near the core on the 2024 leaf-off ortho (type = evergreen if green crown in leaf-off spring); 73 context trees from Meta CHM peaks. Heights: Meta CHM (imagery-derived, ~2016, **underestimates tall conifers** — greenbelt Douglas-firs read 15–19 m, likely 25–35 m in reality) or allometry. 12 hedge rows (several columnar-arborvitae screens). |
| ground cover | observed (automated, rough ~70–85 %) | rule-based on 2024 ortho + 2017 NAIP NDVI; lawns in spring 2024 are yellow-green so lawn/bed confusion is common; use it as a mask hint, not truth |
| roof material | documented (3802, 3813, 3909: "composition") / observed (others: shingle texture) | |
| roof colour | measured (pixel medians) | illumination-dependent; 2024 Pictometry is bright/hazy → treat `sunlit_planes_hex` as an upper bound; NAIP 2017 values are too blue/dark |
| roof heights & pitch | **inferred** | no DSM/lidar obtainable (see sources.md). Eave = storeys × 2.75 m + 0.45 m stem wall (+0.15); ridge = eave + min(width/2, 7 m) × pitch; pitch 6:12 (8:12 for the 2016 Craftsman) |
| facade colours / window layout / doors | **gap for all houses** | nadir orthos only show roofs; no street-level imagery source was available |

## Sledding run (measured on the DTM)

Recommended: **Canby Ct itself**, from the top of the bulb (SE apron by the 3904/3909 driveways,
local (4.9, −38.1), z ≈ 146.5) down the street's steepest-descent line to the 38th St junction
(−124.1, −9.4). **Length 134.5 m, drop 14.8 m, average 11.0 %, max 24 % over 5 m** (the max is
the short apron/driveway lip at the top; on the street proper the 5 m gradient peaks at 13–14 %).
86 % of the line lies on the Canby Ct pavement. Along the City centreline (bulb centre → 38th St):
105.5 m, 142.65 → 131.70 m, drop 10.95 m, avg 10.4 %, max 14.4 % at ~18 m and a second steep
stretch at 35–50 m (12–13 %). The run ends at the 38th St T-junction — the game needs a run-out.
Off-street alternatives (shorter, steeper, obstacle-ridden): 3807/3811 rear terraces westward
(64–71 m, 9–11 m drop, avg 14–15 %, pitches to ~25° in places) and 3802's west embankment (47 m,
6.7 m drop, very steep ~38° lip onto 38th St — not sledable safely).

## Per house

All 10 are on City parcels (land use "RES n BDRM"); footprints from the City layer (measured);
floors/year/style/SF from the City layer (documented).

| addr | floors · style · year (doc) | footprint m² (meas) | roof form & ridge (obs) | roof colour 2024 sunlit / median (meas) | listing facts (doc) | eave / ridge above grade (inf) | main gaps |
|---|---|---|---|---|---|---|---|
| 3802 | 1 · 1 STY · 1984 | 327 | hip, two hipped wings, stepped L; ridge ~120° | #b7b6a9 / #888984 light grey | rambler, 2 304 ft², composition roof, **wood exterior**, attached garage, partial bay view; sold 2023-08 | 3.4 / 6.9 | siding colour, window pattern |
| 3803 | 2 · 2 STY · 1986 | 227 | side gable E-W, 3 small gables on street plane; rear ribbed low-slope addition, pergola, octagonal gazebo | #d3cfbe / #898986 (tan-grey) | none found | 6.2 / 9.7 | all exterior materials/colours |
| 3806 | 2 · SPLIT · 1986 | 279 | complex hip; skylight | #b1b0a3 / #868782 grey | none found | 6.2 / 9.7 (split-level: real heights differ by half a storey) | materials, colours, split-level geometry |
| 3807 | 2 · SPLIT · 1984 | 296 | hip, **brown** shingles, chimney, skylights, rear deck white railing | #c2b8a9 / #9d948b (brown-grey) | none found | 6.2 / 9.7 (split) | as 3806 |
| 3811 | 2 · 2 STY · 1986 (+1 066 ft² bsmt) | 232 | side gable E-W + street cross-gable, chimney W end | #bbbeb8 / #9ca2a0 grey | none found | 6.2 / 9.7 | materials, colours |
| 3813 | 2 · 2 STY · 2015/16 (+bsmt) | 203 | compact hip/gable, grey | #a5a8a6 / #797e7a mid-grey | **Craftsman**, 3 380 ft², composition roof, **cement-planked (fibre-cement) + wood siding**, deck, skylights, attached garage; sold 2023-09 | 6.2 / 10.7 (8:12) | siding colour; DTM predates the house |
| 3900 | 1.5 · 1&H F · 1988 (+bsmt) | 341 | cross-gable, 3 dormers N, **large solar PV array** S | #a6a8a4 / #6b7074 grey + PV | none found | 4.6 / 8.1 | materials, colours |
| 3904 | 1 · 1 STY · 1988 | 318 | large hip rotated ~45°, skylights | #c5c1b5 / #a9a597 light grey | none found | 3.4 / 6.9 | materials, colours |
| **3905** | 2 · 2 STY · 1988 | 276 | complex: main hip (ridge ~155°), lower roof strip on SW face, hipped bay N, light low-slope section in NE corner, E garage wing (ridge E-W); chimney; vents | **#dbdcd5 / #97a0a7 light grey** (2022: #bdc1bc) | **none found** (search 2026-11 returned only the street index) | 6.2 / 9.7 | **see below** |
| 3909 | 2 · 2 STY · 1988 (+1 744 ft² bsmt) | 280 | long side gable, ridge N-S, light grey | #c0bdb1 / #b3afa2 light grey | **cement-planked + wood exterior**, composition roof | 6.2 / 9.7 | colours, sale record |

### 3905 Canby Ct (parents' house) — detail

* **Measured:** footprint 276 m² (OBB 24.1 × 15.8 m); ground around the house 144.7–146.1 m
  (1.4 m fall, lowest to the S/SW toward the bulb); parcel 0.32 ac, gently sloping (mean 4.7°,
  only 3 % > 15°) — the flattest lot on the court, good for walking round the house; roof light grey.
* **Documented (City):** 2 storeys, built 1988, '2 STY', SF 1st 1 856, 2nd 1 404, basement 0,
  TOTAL_SF 5 954 (inconsistent with the floor sums — probably includes garage/decks), 4-bedroom
  land-use code.
* **Observed (2022 + 2024 orthos):** light-grey composition shingles; complex hip roof (see table);
  chimney on the NW part; attached garage wing on the east with doors facing south onto a concrete
  drive from the bulb; front walk from the SW corner to the bulb sidewalk; large lawns N and W;
  play structure with a red roof + swing set at about (−12, 20); diagonal row of ~9 columnar
  arborvitae across the west lawn; low clipped hedge on the curved west lawn edge; flowering cherry
  (pink in spring 2022) and red-leaf ornamental by the street at the SW; paved path NE to a ~5 × 4 m
  grey-roofed garden shed at about (14, 25); raised vegetable beds to the north; patio with
  furniture in the NE re-entrant corner; east side: ~5 m strip to the property line, then a tall
  conifer hedge, a neighbour's gravel drive and a sport court (not 3905's).
* **Inferred:** eave ≈ 6.2 m, main ridge ≈ 9.7 m above grade (≈ 151.9 / 155.4 m NAVD88), 6:12 pitch.
* **Gaps:** **no facade evidence at all** — siding material and colour, trim colour, window and
  door positions, front-door style, garage-door count/style (2 or 3 bays?), deck/railing details on
  the north side, fence type and height, exact chimney material. No listing exists online for 3905.
  **Recommended fix: a few phone photos of each elevation from the family** (or a street-level
  imagery source the user can view) — this is the highest-value missing evidence for the project.

### Most useful next evidence (all houses)
1. Lidar point cloud (WA DNR `Cascades North Wali 2023`, manual download) → measured ridge/eave
   heights, roof planes, tree heights, decks, fences.
2. Street-level photos (family / user) → facade materials and colours for all ten houses.
3. Allow-listing windermere.com / estately.com / orchard.com in the session → read the full listing
   text for 3802, 3813, 3909.
