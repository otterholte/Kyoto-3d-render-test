# Higashiyama, Kyoto — geographically accurate painterly 3D world

A 400 × 400 m reconstruction of the historic Higashiyama district around **Yasaka Pagoda (八坂の塔)**,
built from open government and community geodata first, then art-directed in a painterly
"storybook realism" style.

**Accuracy first, stylisation second.** Streets, steps, building footprints, heights and terrain come
from surveyed data, never from guesswork. Anything inferred or artistic is labelled as such in
`docs/evidence/` and `docs/accuracy_report.md`.

## Layout

| path | contents |
|---|---|
| `pipeline/` | Reproducible Python data pipeline (fetch → project → validate) |
| `data/raw/` | Source downloads: OSM XML, GSI tiles (PLATEAU is re-fetched by script, too large for git) |
| `data/processed/` | Boundary, terrain grid, buildings, streets, features in the local metric frame |
| `docs/` | Master map, boundary + CRS record, evidence record, licences, accuracy report |
| `blender/` | Blender (bpy 5.2 LTS) scene build scripts, `.blend`, render scripts |
| `web/` | Browser explorer (Three.js): third-person, desktop + mobile |
| `renders/` | Cycles renders |

## Rebuild

```bash
uv venv -p 3.13 venv && uv pip install -p venv/bin/python pyproj shapely numpy lxml scipy pillow mapbox-earcut matplotlib requests bpy==5.2.4
cd pipeline
python 01_boundary.py        # boundary.json (needs data/raw/osm/osm_wide.osm)
python 02_fetch_plateau.py   # ranged extraction of mesh 52353692 from the 2.7 GB Kyoto PLATEAU zip
python 03_fetch_gsi.py       # DEM5A, base-map vectors, map tiles
python 04_terrain.py         # 2 m terrain grid
python 05_buildings.py       # PLATEAU LOD2 buildings -> local meshes + real facade colours
python 06_streets.py         # streets / steps / widths / connectivity / barriers / trees
python 08_master_map.py      # docs/master_map*.png
```

See [docs/boundary.md](docs/boundary.md) for the exact boundary, CRS and datasets.

Data © OpenStreetMap contributors (ODbL) · 国土地理院 (GSI) · PLATEAU / MLIT · Wikimedia Commons contributors (per-file licences in `docs/references/`).
