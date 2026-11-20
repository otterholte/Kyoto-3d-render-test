"""Phase 2C/4: PLATEAU 2025 Kyoto (mesh 52353692) buildings -> local-frame meshes + attributes.

For every bldg:Building whose footprint centroid lies inside the box (+backdrop margin):
  * attributes: gml id, name, class, usage, yearOfConstruction, measuredHeight, storeysAboveGround,
    structure type, survey year
  * footprint: lod0RoofEdge (roof-edge outline, i.e. includes eaves) in local x/y
  * base_z: LOD1 solid bottom (ground elevation used by PLATEAU), top_z: LOD1 top
  * lod2: triangulated Roof/Wall/Ground surfaces (local x, y, z), surface kind per triangle,
    and mean RGB per surface sampled from the PLATEAU photo texture (if textured)
Outputs data/processed/buildings.json (+ .npz with the big arrays).
"""
import json
import os
import numpy as np
import mapbox_earcut as earcut
from lxml import etree
from PIL import Image
from shapely.geometry import Polygon
from common import RAW, PROC, load_boundary, ll2en

NS = {
    "gml": "http://www.opengis.net/gml",
    "bldg": "http://www.opengis.net/citygml/building/2.0",
    "app": "http://www.opengis.net/citygml/appearance/2.0",
    "uro": "https://www.geospatial.jp/iur/uro/3.1",
    "core": "http://www.opengis.net/citygml/2.0",
}
b = load_boundary()
OE, ON = b["origin_e"], b["origin_n"]
MARGIN = 100.0
GML = os.path.join(RAW, "plateau", "udx", "bldg", "52353692_bldg_6697_op.gml")
APPDIR = os.path.join(RAW, "plateau", "udx", "bldg")

USAGE = {"401": "業務施設", "402": "商業施設", "403": "宿泊施設", "404": "商業系複合施設", "411": "住宅", "412": "共同住宅",
         "413": "店舗等併用住宅", "414": "店舗等併用共同住宅", "415": "作業所併用住宅", "421": "官公庁施設", "422": "文教厚生施設",
         "431": "運輸倉庫施設", "441": "工場", "454": "その他", "461": "不明"}


def parse_poslist(txt):
    v = np.array(txt.split(), dtype=float).reshape(-1, 3)  # lat lon h
    e, n = ll2en(v[:, 1], v[:, 0])
    return np.c_[np.asarray(e) - OE, np.asarray(n) - ON, v[:, 2]]


def triangulate(ring3):
    r = ring3[:-1] if np.allclose(ring3[0], ring3[-1]) else ring3
    if len(r) < 3:
        return r, np.zeros((0, 3), int)
    # Newell normal -> drop dominant axis
    nrm = np.zeros(3)
    for i in range(len(r)):
        a, c = r[i], r[(i + 1) % len(r)]
        nrm += [(a[1] - c[1]) * (a[2] + c[2]), (a[2] - c[2]) * (a[0] + c[0]), (a[0] - c[0]) * (a[1] + c[1])]
    ax = int(np.argmax(np.abs(nrm)))
    p2 = np.delete(r, ax, axis=1)
    try:
        idx = earcut.triangulate_float64(p2.astype(np.float64), np.array([len(p2)], np.uint32))
    except Exception:
        return r, np.zeros((0, 3), int)
    return r, np.asarray(idx, int).reshape(-1, 3)


# ---- pass 1: appearance (texture + uv per polygon id) ----
tree = etree.parse(GML)
root = tree.getroot()
tex_of_poly = {}
for pt in root.iter("{%s}ParameterizedTexture" % NS["app"]):
    uri = pt.findtext("app:imageURI", namespaces=NS)
    for tgt in pt.findall("app:target", NS):
        pid = tgt.get("uri").lstrip("#")
        tc = tgt.find(".//app:textureCoordinates", NS)
        if tc is not None:
            tex_of_poly[pid] = (uri, np.array(tc.text.split(), float).reshape(-1, 2))

_img_cache = {}


def mean_colour(uri, uv):
    """Average texture colour inside the polygon's UV footprint (bbox sampling, centre-weighted)."""
    if uri not in _img_cache:
        try:
            _img_cache[uri] = np.asarray(Image.open(os.path.join(APPDIR, uri)).convert("RGB"), dtype=np.float32)
        except Exception:
            _img_cache[uri] = None
        if len(_img_cache) > 64:
            _img_cache.pop(next(iter(_img_cache)))
    im = _img_cache[uri]
    if im is None:
        return None
    h, w, _ = im.shape
    poly = Polygon(uv)
    if poly.area <= 0:
        return None
    rng = np.random.default_rng(0)
    x0, y0, x1, y1 = poly.bounds
    pts = np.c_[rng.uniform(x0, x1, 200), rng.uniform(y0, y1, 200)]
    from shapely import contains_xy
    inside = pts[contains_xy(poly, pts[:, 0], pts[:, 1])]
    if len(inside) < 3:
        inside = np.array([poly.representative_point().coords[0]])
    px = np.clip((inside[:, 0] * (w - 1)).astype(int), 0, w - 1)
    py = np.clip(((1 - inside[:, 1]) * (h - 1)).astype(int), 0, h - 1)
    c = im[py, px].mean(axis=0)
    return [int(round(x)) for x in c]


# ---- pass 2: buildings ----
KIND = {"RoofSurface": 0, "WallSurface": 1, "GroundSurface": 2}
buildings, P, T, K, C, BID = [], [], [], [], [], []
voff = 0
for bi, el in enumerate(root.iter("{%s}Building" % NS["bldg"])):
    gid = el.get("{%s}id" % NS["gml"])
    fp_el = el.find("bldg:lod0RoofEdge//gml:posList", NS)
    if fp_el is None:
        continue
    fp = parse_poslist(fp_el.text)
    cx, cy = fp[:, 0].mean(), fp[:, 1].mean()
    if abs(cx) > 200 + MARGIN or abs(cy) > 200 + MARGIN:
        continue
    l1 = el.findall("bldg:lod1Solid//gml:posList", NS)
    zs = np.concatenate([parse_poslist(p.text)[:, 2] for p in l1]) if l1 else np.array([np.nan])
    rec = dict(
        id=gid, name=el.findtext("gml:name", namespaces=NS),
        cls=el.findtext("bldg:class", namespaces=NS), usage=el.findtext("bldg:usage", namespaces=NS),
        usage_ja=USAGE.get(el.findtext("bldg:usage", namespaces=NS) or "", None),
        year=el.findtext("bldg:yearOfConstruction", namespaces=NS),
        height=float(el.findtext("bldg:measuredHeight", namespaces=NS) or "nan"),
        storeys=int(el.findtext("bldg:storeysAboveGround", namespaces=NS) or 0),
        structure=el.findtext(".//uro:buildingStructureType", namespaces=NS),
        footprint=np.round(fp[:, :2], 3).tolist(),
        base_z=round(float(np.nanmin(zs)), 3), top_z=round(float(np.nanmax(zs)), 3),
        in_box=bool(abs(cx) <= 200 and abs(cy) <= 200),
        centroid=[round(cx, 2), round(cy, 2)],
        has_lod2=False, tri_start=None, tri_count=0,
    )
    tstart = len(T)
    for kind, k in KIND.items():
        for surf in el.findall("bldg:boundedBy/bldg:%s" % kind, NS):
            for poly in surf.findall(".//gml:Polygon", NS):
                pid = poly.get("{%s}id" % NS["gml"])
                ring = parse_poslist(poly.find(".//gml:posList", NS).text)
                verts, tris = triangulate(ring)
                if len(tris) == 0:
                    continue
                col = None
                if pid in tex_of_poly:
                    col = mean_colour(*tex_of_poly[pid])
                P.append(verts); T.append(tris + voff); voff += len(verts)
                K += [k] * len(tris); C += [col or [-1, -1, -1]] * len(tris); BID += [len(buildings)] * len(tris)
    nt = sum(len(t) for t in T[tstart:])
    if nt:
        rec.update(has_lod2=True, tri_count=int(nt))
    buildings.append(rec)

P = np.concatenate(P).astype(np.float32); T = np.concatenate(T).astype(np.int32)
np.savez_compressed(os.path.join(PROC, "buildings_lod2.npz"), positions=P, triangles=T,
                    kind=np.array(K, np.uint8), colour=np.array(C, np.int16), building=np.array(BID, np.int32))
with open(os.path.join(PROC, "buildings.json"), "w") as f:
    json.dump(dict(source="PLATEAU 2025 Kyoto City CityGML v5, mesh 52353692 (bldg)", crs_local=b["crs"],
                   origin=[OE, ON], buildings=buildings), f, ensure_ascii=False)
inb = [x for x in buildings if x["in_box"]]
print("buildings total", len(buildings), "in box", len(inb), "lod2 in box", sum(x["has_lod2"] for x in inb),
      "tris", len(T), "verts", len(P))
print("heights in box: max", max(x["height"] for x in inb), "storeys dist",
      {s: sum(1 for x in inb if x["storeys"] == s) for s in range(0, 8)})
print("named:", [x["name"] for x in buildings if x["name"]])
