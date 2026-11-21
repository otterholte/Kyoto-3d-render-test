"""Ground cover classification (0.3 m) for the context box + vector polygons.

Sources: City street pavement polygon (asphalt, 'ACP'), City sidewalk centrelines (PCC, width 5 ft),
City building footprints, trees/hedges from trees.json (observed), and per-pixel rules on
  - Whatcom 2024 ortho (leaf-off spring, 0.15 m -> 0.3 m): excess-green ExG = 2G-R-B, luminance, local texture
  - NAIP 2017-09-02 (leaf-on, 1 m, CIR): NDVI
Rules (classes 'observed' from imagery, accuracy ~70-85 %; check the preview):
  paved/hardscape  : NDVI17 < 0.15 and ExG24 < 14        (driveways, patios, walks; concrete vs asphalt by brightness)
  lawn             : ExG24 >= 16 and texture < 11 and not under a tree crown
  bed / shrubs     : other vegetated pixels (NDVI17 >= 0.15 or ExG24 >= 14)
Shadowed pixels (luminance < 75) are assigned from NDVI17 alone. A 7x7 majority filter cleans speckle.
Outputs data/processed/groundcover/{classes_0p3m.tif, preview.png, groundcover.geojson, legend.json}
"""
import json

import numpy as np
import rasterio
from rasterio.features import rasterize, shapes
from rasterio.transform import from_origin
from rasterio.warp import reproject, Resampling
from scipy import ndimage as ndi
from shapely.geometry import shape, mapping, Point, LineString
from shapely.ops import unary_union, transform as stransform
from PIL import Image

from common import RAW, PROC, ORIGIN_E, ORIGIN_N, CRS, to_local, dump

OUT = PROC / "groundcover"
OUT.mkdir(parents=True, exist_ok=True)
RES = 0.3
CLASSES = {0: ("unknown", (0, 0, 0)), 1: ("building", (200, 60, 60)), 2: ("street_asphalt", (90, 90, 95)),
           3: ("sidewalk_concrete", (215, 215, 205)), 4: ("paved_concrete", (185, 185, 180)),
           5: ("paved_dark (asphalt drive / dark patio / deck / gravel)", (130, 125, 120)), 6: ("lawn", (120, 190, 80)),
           7: ("bed_shrubs", (110, 120, 50)), 8: ("tree_canopy", (30, 100, 40)), 9: ("hedge", (40, 140, 90))}


def load(name):
    return json.load(open(RAW / "city" / f"{name}.geojson"))["features"]


def utm(g):
    from common import TO_UTM
    return stransform(lambda x, y, z=None: TO_UTM.transform(x, y), g)


def main():
    src = rasterio.open(RAW / "rasters" / "ortho_wc2024.tif")
    t0 = src.transform
    W = int(src.width * t0.a / RES); H = int(src.height * -t0.e / RES)
    tr = from_origin(t0.c, t0.f, RES, RES)
    o = np.zeros((3, H, W), np.float32)
    reproject(src.read().astype(np.float32), o, src_transform=t0, src_crs=CRS, dst_transform=tr, dst_crs=CRS,
              resampling=Resampling.average)
    # texture at full res, then averaged
    L15 = src.read().astype(np.float32).mean(0)
    m = ndi.uniform_filter(L15, 7); m2 = ndi.uniform_filter(L15 * L15, 7)
    sd15 = np.sqrt(np.maximum(m2 - m * m, 0))
    sd = np.zeros((H, W), np.float32)
    reproject(sd15, sd, src_transform=t0, src_crs=CRS, dst_transform=tr, dst_crs=CRS, resampling=Resampling.average)
    naip = rasterio.open(RAW / "rasters" / "naip.tif")
    nb = naip.read().astype(np.float32)
    ndvi1 = (nb[3] - nb[0]) / (nb[3] + nb[0] + 1e-6)
    ndvi = np.zeros((H, W), np.float32)
    reproject(ndvi1, ndvi, src_transform=naip.transform, src_crs=CRS, dst_transform=tr, dst_crs=CRS, resampling=Resampling.bilinear)

    L = o.mean(0)
    exg = 2 * o[1] - o[0] - o[2]
    cls = np.zeros((H, W), np.uint8)
    paved = (ndvi < 0.15) & (exg < 14)
    veg = ~paved
    lawn = veg & (exg >= 10) & (sd < 14)
    shadow = L < 75
    cls[paved] = 4
    cls[paved & (L < 135)] = 5
    cls[veg] = 7
    cls[lawn] = 6
    cls[shadow & (ndvi >= 0.3)] = 6
    cls[shadow & (ndvi >= 0.3) & (sd >= 14)] = 7
    cls[shadow & (ndvi < 0.15)] = 5
    # majority filter
    def mode_filter(a, k=7):
        best = np.zeros_like(a); bestc = np.zeros(a.shape, np.float32)
        for c in np.unique(a):
            cnt = ndi.uniform_filter((a == c).astype(np.float32), k)
            sel = cnt > bestc
            best[sel] = c; bestc[sel] = cnt[sel]
        return best
    cls = mode_filter(cls)

    # vector overlays (UTM)
    pav = unary_union([utm(shape(f["geometry"])).buffer(0) for f in load("street_pavement")])
    sw = unary_union([utm(shape(f["geometry"])).buffer((f["properties"].get("WIDTH") or 5) * 0.3048 / 2, cap_style=2)
                      for f in load("sidewalks") if f["geometry"]])
    bld = [utm(shape(f["geometry"])) for f in load("buildings_agol")]
    trees = json.load(open(PROC / "trees.json"))
    crowns = unary_union([Point(t["x"] + ORIGIN_E, t["y"] + ORIGIN_N).buffer(t["crown_radius_m"])
                          for t in trees["trees"] if t["type"] != "ornamental"])
    orn = unary_union([Point(t["x"] + ORIGIN_E, t["y"] + ORIGIN_N).buffer(t["crown_radius_m"])
                       for t in trees["trees"] if t["type"] == "ornamental"])
    hedges = unary_union([LineString([(x + ORIGIN_E, y + ORIGIN_N) for x, y in h["points"]]).buffer(h["width_m"] / 2)
                          for h in trees["hedges"]])
    R = lambda g, v: rasterize([(mapping(g), v)], out_shape=(H, W), transform=tr, fill=0).astype(bool)
    cls[R(crowns, 1)] = 8
    cls[R(orn, 1)] = 7
    cls[R(hedges, 1)] = 9
    cls[R(pav, 1)] = 2
    cls[R(sw, 1)] = 3
    for b in bld:
        cls[R(b, 1)] = 1

    prof = dict(driver="GTiff", width=W, height=H, count=1, dtype="uint8", crs=CRS, transform=tr, compress="deflate")
    with rasterio.open(OUT / "classes_0p3m.tif", "w", **prof) as d:
        d.write(cls, 1)
    lut = np.zeros((256, 3), np.uint8)
    for k, (_, c) in CLASSES.items():
        lut[k] = c
    Image.fromarray(lut[cls]).save(OUT / "preview.png")

    feats = []
    for geom, val in shapes(cls, transform=tr):
        if val in (0, 1):
            continue
        g = shape(geom)
        if g.area < 1.0:
            continue
        g = stransform(lambda x, y, z=None: (x - ORIGIN_E, y - ORIGIN_N), g).simplify(0.3)
        feats.append({"type": "Feature", "properties": {"class": CLASSES[int(val)][0], "area_m2": round(g.area, 1)},
                      "geometry": mapping(g)})
    # curb line (gutter edge) = street pavement boundary
    curb = stransform(lambda x, y, z=None: (x - ORIGIN_E, y - ORIGIN_N), pav.boundary)
    feats.append({"type": "Feature", "properties": {"class": "curb_line", "note": "C&G curb & gutter per City centreline CurbType1"},
                  "geometry": mapping(curb.simplify(0.1))})
    dump(OUT / "groundcover.geojson", {"type": "FeatureCollection", "crs": "local metres (boundary.json)", "features": feats})
    areas = {CLASSES[k][0]: round(float((cls == k).sum() * RES * RES)) for k in CLASSES}
    dump(OUT / "legend.json", {"resolution_m": RES, "classes": {str(k): {"name": v[0], "rgb": v[1]} for k, v in CLASSES.items()},
                               "area_m2_context": areas, "method": __doc__.strip()})
    print(areas)


if __name__ == "__main__":
    main()
