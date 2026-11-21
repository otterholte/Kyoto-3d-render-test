"""Fetch raster evidence for the context box (+20 m) and resample to EPSG:6339 grids.

  ortho_cob2022.tif   City of Bellingham 2022 ortho (EagleView, 2-inch, spring 2022)   0.15 m RGB
  ortho_wc2024.tif    Whatcom County 2024 ortho (Pictometry, Mar-Jun 2024)             0.15 m RGB
  naip.tif            USGS NAIP Plus (RGB+NIR), native ~0.6 m                          0.5 m 4-band
  dem_3dep.tif        USGS 3DEP dynamic elevation service (bare earth, best available) 1.0 m
  chm_meta.tif        Meta/WRI global canopy height (1 m, imagery-derived)             1.0 m
  contours_2013.geojson  City of Bellingham 2013-lidar contours (detail, ft NAVD88)

Raw downloads go to data/raw/; rasters are written as GeoTIFF in EPSG:6339.
"""
import io
import json
import math
import os
import sys

import numpy as np
import rasterio
from rasterio.transform import from_origin
from rasterio.warp import reproject, Resampling
from PIL import Image

from common import RAW, ORIGIN_E, ORIGIN_N, CRS, TO_LL, get, dump

os.environ.setdefault("CURL_CA_BUNDLE", "/root/.ccr/ca-bundle.crt")

B = json.load(open(RAW.parent / "processed" / "boundary.json"))
X0, Y0, X1, Y1 = B["context"]["bounds_local"]
PAD = 20
E0, N0, E1, N1 = X0 - PAD + ORIGIN_E, Y0 - PAD + ORIGIN_N, X1 + PAD + ORIGIN_E, Y1 + PAD + ORIGIN_N
OUT = RAW / "rasters"
OUT.mkdir(parents=True, exist_ok=True)

R = 6378137.0


def ll2merc(lon, lat):
    return R * math.radians(lon), R * math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))


def dst_profile(res, count, dtype, bounds=None):
    e0, n0, e1, n1 = bounds or (E0, N0, E1, N1)
    w = int(round((e1 - e0) / res)); h = int(round((n1 - n0) / res))
    return dict(driver="GTiff", width=w, height=h, count=count, dtype=dtype, crs=CRS,
                transform=from_origin(e0, n1, res, res), compress="deflate", tiled=True)


def fetch_tiled(url, z, name, res=0.15, bounds=None):
    """Mosaic Web-Mercator /tile/z/y/x JPEG/PNG tiles and warp to EPSG:6339."""
    e0, n0, e1, n1 = bounds or (E0, N0, E1, N1)
    lons, lats = zip(*[TO_LL.transform(e, n) for e in (e0, e1) for n in (n0, n1)])
    mx0, my0 = ll2merc(min(lons), min(lats)); mx1, my1 = ll2merc(max(lons), max(lats))
    origin = -20037508.342787
    tres = 2 * 20037508.342787 / (256 * 2 ** z)
    tx0 = int((mx0 - origin) / (256 * tres)); tx1 = int((mx1 - origin) / (256 * tres))
    ty0 = int((-origin - my1) / (256 * tres)); ty1 = int((-origin - my0) / (256 * tres))
    W = (tx1 - tx0 + 1) * 256; H = (ty1 - ty0 + 1) * 256
    mos = np.zeros((H, W, 3), np.uint8)
    n = 0
    for ty in range(ty0, ty1 + 1):
        for tx in range(tx0, tx1 + 1):
            r = get(f"{url}/tile/{z}/{ty}/{tx}")
            im = Image.open(io.BytesIO(r.content)).convert("RGB")
            mos[(ty - ty0) * 256:(ty - ty0 + 1) * 256, (tx - tx0) * 256:(tx - tx0 + 1) * 256] = np.asarray(im)
            n += 1
    print(name, "tiles", n)
    src_t = from_origin(origin + tx0 * 256 * tres, -origin - ty0 * 256 * tres, tres, tres)
    prof = dst_profile(res, 3, "uint8", bounds)
    dst = np.zeros((3, prof["height"], prof["width"]), np.uint8)
    for b in range(3):
        reproject(mos[:, :, b], dst[b], src_transform=src_t, src_crs="EPSG:3857",
                  dst_transform=prof["transform"], dst_crs=CRS, resampling=Resampling.bilinear)
    with rasterio.open(OUT / f"{name}.tif", "w", **prof, photometric="RGB") as d:
        d.write(dst)


def export_image(url, name, res, count, dtype, extra=None, sr=26910):
    """ArcGIS ImageServer exportImage in NAD83 UTM10 (treated as EPSG:6339; <1 m datum diff)."""
    w = int(round((E1 - E0) / res)); h = int(round((N1 - N0) / res))
    p = {"bbox": f"{E0},{N0},{E1},{N1}", "bboxSR": sr, "imageSR": sr, "size": f"{w},{h}",
         "format": "tiff", "f": "image", "interpolation": "RSP_BilinearInterpolation"}
    p.update(extra or {})
    r = get(url + "/exportImage", p, timeout=300)
    raw = OUT / f"{name}_raw.tif"
    raw.write_bytes(r.content)
    with rasterio.open(raw) as s:
        a = s.read()
        print(name, s.crs, s.shape, s.count, s.dtypes[0], s.nodata, float(np.nanmin(a)), float(np.nanmax(a)))
        prof = dst_profile(res, s.count, s.dtypes[0])
        prof["nodata"] = s.nodata
        with rasterio.open(OUT / f"{name}.tif", "w", **prof) as d:
            # the export grid already equals our grid (same bbox/size); just relabel CRS
            d.write(a[:, :prof["height"], :prof["width"]])
    raw.unlink()


def fetch_chm():
    qk = "021230001"
    url = f"/vsicurl/https://dataforgood-fb-data.s3.amazonaws.com/forests/v1/alsgedi_global_v6_float/chm/{qk}.tif"
    prof = dst_profile(1.0, 1, "float32"); prof["nodata"] = -1
    dst = np.full((prof["height"], prof["width"]), -1, np.float32)
    with rasterio.open(url) as s:
        from rasterio.windows import from_bounds
        from rasterio.warp import transform_bounds
        b = transform_bounds(CRS, s.crs, E0 - 30, N0 - 30, E1 + 30, N1 + 30)
        win = from_bounds(*b, transform=s.transform).round_offsets().round_lengths()
        a = s.read(1, window=win).astype(np.float32)
        print("chm src", s.crs, s.res, a.shape, a.min(), a.max())
        reproject(a, dst, src_transform=s.window_transform(win), src_crs=s.crs,
                  dst_transform=prof["transform"], dst_crs=CRS, resampling=Resampling.bilinear,
                  src_nodata=255 if s.dtypes[0] == "uint8" else None, dst_nodata=-1)
    with rasterio.open(OUT / "chm_meta.tif", "w", **prof) as d:
        d.write(dst, 1)
    # acquisition date of the source imagery
    with rasterio.open("/vsicurl/https://dataforgood-fb-data.s3.amazonaws.com/forests/v1/alsgedi_global_v6_float/CHM_acquisition_date.tif") as s:
        e, n = (E0 + E1) / 2, (N0 + N1) / 2
        from rasterio.warp import transform as tr
        xs, ys = tr(CRS, s.crs, [e], [n])
        v = list(s.sample(zip(xs, ys)))[0]
        print("chm acquisition-date pixel", v, s.descriptions, s.tags())
        dump(OUT / "chm_meta_acqdate.json", {"value": [float(x) for x in v], "tags": s.tags()})


def fetch_contours():
    """City 2013-lidar 5 ft contours. Features are city-wide polylines (~200k vertices each),
    so fetch IDs over the core, then each feature in UTM, and clip locally to the context box."""
    from shapely.geometry import MultiLineString, box, mapping
    url = "https://maps.cob.org/arcgis4/rest/services/Maps/Contours_2013/MapServer/0/query"
    lo0, la0 = TO_LL.transform(E0, N0); lo1, la1 = TO_LL.transform(E1, N1)
    ids = get(url, {"where": "1=1", "geometry": f"{lo0},{la0},{lo1},{la1}", "geometryType": "esriGeometryEnvelope",
                    "inSR": 4326, "returnIdsOnly": "true", "f": "json"}).json()["objectIds"]
    clipbox = box(E0, N0, E1, N1)
    feats = []
    for oid in ids:
        d = get(url, {"objectIds": oid, "outFields": "OBJECTID,Contour,TYPE,INDEX_", "returnGeometry": "true",
                      "outSR": 26910, "geometryPrecision": 2, "f": "json"}, timeout=300).json()
        for f in d.get("features", []):
            g = MultiLineString(f["geometry"]["paths"]).intersection(clipbox)
            if g.is_empty:
                continue
            feats.append({"type": "Feature", "properties": f["attributes"], "geometry": mapping(g)})
        print("contour", oid, len(feats), flush=True)
    dump(RAW / "city" / "contours_2013_utm.geojson", {"type": "FeatureCollection", "crs": "EPSG:26910 (treated as EPSG:6339)",
                                                     "units": "Contour = feet NAVD88", "source": url, "features": feats})
    print("contours", len(feats), sorted({f["properties"]["Contour"] for f in feats}))


if __name__ == "__main__":
    jobs = sys.argv[1:] or ["cob2022", "wc2024", "naip", "dem", "chm", "cob2022hi", "wc2024hi", "contours"]
    if "cob2022" in jobs:
        fetch_tiled("https://maps.cob.org/arcgis4/rest/services/Imagery/Photo_2022/MapServer", 20, "ortho_cob2022")
    if "wc2024" in jobs:
        fetch_tiled("https://wcgis.whatcomcounty.us/arcgis/rest/services/Imagery/2024_WhatcomAerialImagery_Web/MapServer", 20, "ortho_wc2024")
    if "naip" in jobs:
        export_image("https://imagery.nationalmap.gov/arcgis/rest/services/USGSNAIPPlus/ImageServer", "naip", 0.5, 4, "uint8")
    if "dem" in jobs:
        export_image("https://elevation.nationalmap.gov/arcgis/rest/services/3DEPElevation/ImageServer", "dem_3dep", 1.0, 1, "float32",
                     {"pixelType": "F32", "noData": -9999})
    if "chm" in jobs:
        fetch_chm()
    cb = B["core"]["bounds_local"]
    core_b = (cb[0] + ORIGIN_E - 5, cb[1] + ORIGIN_N - 5, cb[2] + ORIGIN_E + 5, cb[3] + ORIGIN_N + 5)
    if "cob2022hi" in jobs:
        fetch_tiled("https://maps.cob.org/arcgis4/rest/services/Imagery/Photo_2022/MapServer", 21, "ortho_cob2022_core", 0.075, core_b)
    if "wc2024hi" in jobs:
        fetch_tiled("https://wcgis.whatcomcounty.us/arcgis/rest/services/Imagery/2024_WhatcomAerialImagery_Web/MapServer", 21, "ortho_wc2024_core", 0.075, core_b)
    if "contours" in jobs:
        fetch_contours()
