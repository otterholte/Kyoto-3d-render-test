# Paused — where things stand (2026-11-21)

All agents were stopped on request. Everything below is committed on `main`.

## Higashiyama, Kyoto

Live explorer: https://claude.ai/artifact/PHsRBZiypkVmaGeBJbuStU (version 4, private to the owner's claude.ai account)

Done:
- Boundary + CRS, master map (`docs/boundary.md`), OSM / GSI / PLATEAU data pipeline (`pipeline/`)
- Blockout + validation (`blender/build_world.py`, `docs/validation_report.md`)
- Reference evidence (`docs/evidence/`, `docs/references/`), independent accuracy audit (`docs/accuracy_report.md`)
- Hero pagoda, 38.8 m (`blender/hero_pagoda.py`, `docs/evidence/yasaka_pagoda_model.md`)
- Texture library (`blender/texture_library.py`; regenerate `blender/textures/` locally, web set in `web/assets/tex/`)
- Real backdrop: city + hills (`blender/build_backdrop.py`, `docs/backdrop.md`)
- Art pass + five 4K Cycles finals (`renders/final_*.png`), web gallery (`web/assets/renders/`)
- Web explorer: realism upgrade, code-review fixes (`web/README.md`)

Next (art pass, `blender/art_pass.py` + `kit_*.py`). These were sent to the art agent, which was stopped before finishing:
1. Facade patchwork: use one coherent atlas module per storey per building; plain side walls; no doubling of the 1F kit and atlas GF modules.
2. Roof edges: fascia, eave-tile row, rafter tails and soffit on Priority-2 fronts.
3. Trees: use the library foliage atlas.
4. Stair bug in `build_world.py`: flights should follow or carve the DEM; then regenerate the blockout.
5. Re-render the five finals, re-export `world_art.glb` + gallery, then `cd web && node build.mjs` and republish `web/artifact.html`. The host serves no .glb, so publish the `dist/*.b64.txt` files.

Also open: audit F3 (pagoda visibility at the Ninenzaka junction needs a field check), audit F5/F6, real-phone fps check.

## Canby Court, Bellingham (`canby-court/`)

Privacy: owner names are never stored; the city fetch whitelists fields. County/city ortho mosaics are licence-restricted and git-ignored.

Done:
- Data foundation: `data/processed/` (boundary EPSG:6339 with origin at the 3905 address point, 0.5 m DTM, houses, trees, ground cover, sledding run), `docs/` (boundary, evidence, sources, NAIP master map)
- Shared game layout: `data/game/jumps.json` (artistic kickers + run-out berm on the measured 134.5 m run)

In progress when stopped (partial, uncommitted work was committed as WIP):
- Character (`character/`): MakeHuman-based, outfits, clips, sled. It was at the export/optimise step (`export_web.py`).
- Houses + landscaping, summer/winter (`blender/`, `data/facades.json`). It was adding marker empties to the export.
- Web game (`web/`): walk, season toggle, sled physics, jumps, boost, tricks. It was rebuilding and rendering test views.

Blocking or helpful input from the user: photos of 3905 (front, sides, back yard). No listing or record exists online. Facade colours for all houses are currently inferred (`data/facades.json` is the single place to correct them).

## Environment

The cloud environment `higashiyama-kyoto` allows the OSM, GSI, PLATEAU, Wikimedia, Bellingham/Whatcom GIS, USGS and NAIP hosts.
Setup: `uv venv -p 3.13 /home/user/venv && uv pip install -p /home/user/venv/bin/python pyproj shapely numpy lxml scipy pillow mapbox-earcut matplotlib requests bpy==5.2.4`; web: `npm install` in `web/` and `canby-court/web/`.
