# Canby Court — boundary, CRS and data index

## Coordinate system

| item | value |
|---|---|
| horizontal CRS | **NAD83(2011) / UTM zone 10N — EPSG:6339**, metres |
| vertical | NAVD88 metres (catch-basin survey and 3DEP both NAVD88) |
| local origin | **E 539320, N 5396840** (EPSG:6339) = 3905 Canby Ct City address point (48.72334394 N, −122.4653697 E) rounded to 1 m |
| local axes | x = E − 539320 (east), y = N − 5396840 (north), z = NAVD88 m (absolute; ground at origin ≈ 145.9 m) |

Rasters fetched in NAD83 / UTM 10N (EPSG:26910) or Web Mercator are labelled/warped as EPSG:6339; the
NAD83 realisation difference (<1 m) is below the footprint accuracy and is ignored.

## Extents

| name | local bounds (x0, y0, x1, y1) m | size | meaning |
|---|---|---|---|
| **core** | polygon, bbox (−163.1, −110.1, 55.6, 64.4) | 34 465 m² | Canby Ct right-of-way + the 10 Canby Ct parcels, buffered 30 m (`boundary.json › core.local`) |
| **context** | (−210, −160, 110, 110) | 320 × 270 m | core bbox + 45 m, rounded to 10 m: 38th St entrance, Viewmont Ct to the north, the 40th St backs to the east, wooded greenbelt to the south |
| raster pad | (−230, −180, 130, 130) | 360 × 310 m | context + 20 m; all rasters (DTM, orthos, class map) cover this |

Lon/lat of the context: −122.46824, 48.72190 → −122.46387, 48.72435.

Canby Ct leaves 38th St at about (−126, −9) and climbs east ~105 m (centreline) to the cul-de-sac
bulb centred near (−27, −27). Houses: north side 3803, 3807, 3811, 3813, 3905; bulb/south side 3909,
3904, 3900, 3806, 3802 (see `docs/master_map.png`).

## Files

| file | content |
|---|---|
| `data/processed/boundary.json` | CRS, origin, core polygon, context box, parcel polygons (local), Canby Ct centreline and road polygon |
| `data/processed/terrain/dtm_0p5m.tif` | bare-earth DTM 0.5 m, EPSG:6339, NAVD88 (720 × 620 px over the raster pad) |
| `data/processed/terrain/slope_deg_0p5m.tif` | slope in degrees |
| `data/processed/terrain/heightmap_u16.png` | 16-bit heightmap of the DTM (decode in `terrain.json`) |
| `data/processed/terrain.json` | DTM metadata, validation, per-parcel slope stats, ground z around each house |
| `data/processed/sledding.json` | recommended sledding run (path, length, drop, gradients) + street profile + other candidates |
| `data/processed/houses.json` | per-house evidence (footprint, assessor fields, roof form/colour/heights, garage, features, listing facts, gaps) |
| `data/processed/context_buildings.json` | 180 neighbouring footprints with floors/year (massing only) |
| `data/processed/trees.json` | 142 trees (69 digitised + 73 CHM context) and 12 hedge polylines |
| `data/processed/groundcover/` | 0.3 m class raster, preview, vector polygons (local), legend + method |
| `docs/master_map.png`, `docs/master_map_naip.png`, `docs/terrain_map.png` | maps |
| `data/raw/city/*.geojson` | City of Bellingham layers (owner fields never requested), EPSG:4326 |
| `data/raw/rasters/` | 3DEP DEM, NAIP, Meta CHM, City 2022 + County 2024 ortho mosaics (orthos git-ignored) |
| `pipeline/01…08_*.py` | reproducible pipeline (`common.py` holds CRS/origin) |

Run order: `01_fetch_city → 02_boundary → 03_fetch_rasters → 04_terrain → 06_trees → 05_groundcover → 07_houses → 08_master_map`
(05 uses trees.json). Use `/home/user/venv/bin/python`.
