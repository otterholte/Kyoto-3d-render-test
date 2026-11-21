# Sources, licences and access notes

Accessed 2026-11-21. Privacy: no owner, taxpayer or other person names are requested, stored or
published. Every City query uses an explicit field whitelist; `pipeline/common.py › scrub()` drops
any OWNER/TAXPAYER/TITLE_OWNER/editor-user/subdivision/legal-description field that slips through.
(Subdivision/plat names were dropped because some are named after people.)

## Used

| source | what | how | licence / terms |
|---|---|---|---|
| City of Bellingham — `Bellingham_Buildings_With_Addresses` FeatureServer/0 (services5.arcgis.com/cuQhNeNcUrgLmYGD) | footprints, NUM_FLOORS, YRBUILT, STYLE, SF_* , address, parcel code | REST query, bbox | City GIS data, published for public use "as is"; metadata: cartographic purpose, no integrity testing. Attribute the City. |
| City of Bellingham ArcGIS Server maps.cob.org (arcgis3/arcgis4) | tax parcels (geometry, address, land use, acreage — owner fields NOT requested), address points, sidewalks (PCC, 5 ft), street pavement (ACP), street centrelines (26 ft wide, C&G curb), curb ramps, hydrants, streetlights, catch basins (GPS rim elevations, NAVD88 ft), 2013-lidar 5-ft contours, 2022-lidar % slope polygons, tree inventory (no trees inside the site) | REST query | same City terms; disclaimer: not survey-grade |
| City of Bellingham `Imagery/Photo_2022` | 2-inch EagleView ortho, spring 2022 | map tiles (z20, z21 for the core) | © City of Bellingham / Whatcom County / EagleView — used for analysis only; mosaics are git-ignored, do not redistribute |
| Whatcom County `Imagery/2024_WhatcomAerialImagery_Web` (wcgis.whatcomcounty.us) | Pictometry ortho, captured Mar–Jun 2024 (leaf-off at the site) | map tiles | © Whatcom County / Pictometry (EagleView) — analysis/reference only, git-ignored |
| USGS 3DEP dynamic elevation ImageServer | bare-earth DEM; best source at the site = NED 1/9″ `ned19_n48x75_w122x50_wa_northpugetsound_2006` (North Puget Sound 2006 lidar) | exportImage 1 m | US public domain (credit USGS) |
| USGS NAIP Plus ImageServer | NAIP `m_4812221_nw_10_1_20170902` (2017-09-02, 1 m, RGB+NIR) | exportImage 0.5 m | US public domain (USDA FSA / USGS) |
| Meta / WRI global canopy height v1 (`dataforgood-fb-data` S3, tile 021230001) | 1 m canopy height model from ~2016 satellite imagery (acq.-date raster value 16.42) | COG window read | CC BY 4.0 — credit "Meta and World Resources Institute (WRI)" |
| OpenStreetMap (way 5264724 + surroundings, extract in scratch) | street names/topology cross-check | — | ODbL 1.0 — "© OpenStreetMap contributors"; derived DBs must stay ODbL |
| Real-estate listing pages (Windermere, Orchard, Estately, Wicklund, withwre.com mirrors) | exterior facts for 3802, 3813, 3909 | **only web-search result snippets were read** — the sites are not reachable from this environment (DNS blocked). No scraping, no photos saved. | Human-read reference only; facts recorded with URLs; nothing copied beyond short factual phrases |
| Redfin street index (search snippet) | confirms the 10 Canby Ct addresses; street average lot 12 927 ft² | search snippet | reference only |

## Tried but not obtainable

| source | result |
|---|---|
| USGS 3DEP lidar point clouds (usgs-lidar-public EPT, prd-tnm LPC) | **No coverage of Bellingham proper.** `WA_Western_North_2016` has a hole over the city (tiles q48122F4/G4 skip 48.69–48.82 N); no EPT resource contains the site. 3DEP 1 m DEM tile x53y540 is NoData here. |
| WA DNR Lidar Portal (lidarportal.dnr.wa.gov) | Lists `Bellingham 2013` and `Cascades North Wali 2023` (DTM, DSM, point cloud) covering the site, but `/download` returns HTTP 403 and **robots.txt disallows /download, /query and /arcgis/** — not used further (two `/query` calls were made before robots.txt was read; nothing was downloaded). A human can download them manually (≈250 MB of 2023 LAZ for the core). This is the single biggest upgrade available: it would turn roof heights/pitches and tree heights from *inferred/modelled* into *measured*. |
| City 2013 contours as a DTM source | features are city-wide polylines (~200 k vertices each); 40 lines were fetched and clipped, used for validation only |
| Listing pages via WebFetch | windermere.com, estately.com, orchard.com: host not allowed in this session's network (would need allow-listing). |
