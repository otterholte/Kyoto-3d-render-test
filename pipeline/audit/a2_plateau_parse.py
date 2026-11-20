"""A2a: independent parse of the raw PLATEAU bldg GML (EPSG:6697 -> 6674 via EPSG:6668) for every building
whose roof-edge polygon centroid lies within 300 m of the box centre."""
import os
import pickle
import numpy as np
from lxml import etree
from shapely.geometry import Polygon
from shapely.ops import unary_union
from acommon import RAW, OUT, jgd_xy

NS = {"gml": "http://www.opengis.net/gml", "bldg": "http://www.opengis.net/citygml/building/2.0"}
G = "{http://www.opengis.net/gml}"
root = etree.parse(os.path.join(RAW, "plateau", "udx", "bldg", "52353692_bldg_6697_op.gml")).getroot()


def pl(txt):
    v = np.array(txt.split(), float).reshape(-1, 3)
    x, y = jgd_xy(v[:, 1], v[:, 0])
    return np.c_[x, y, v[:, 2]]


recs = {}
for el in root.iter("{http://www.opengis.net/citygml/building/2.0}Building"):
    gid = el.get(G + "id")
    re = el.find("bldg:lod0RoofEdge//gml:posList", NS)
    ring = pl(re.text)
    poly = Polygon(ring[:, :2]).buffer(0)
    c = poly.centroid
    if abs(c.x) > 300 or abs(c.y) > 300:
        continue
    z1 = np.concatenate([pl(p.text)[:, 2] for p in el.findall("bldg:lod1Solid//gml:posList", NS)])
    walls, grounds, roofs = [], [], []
    for kind, store in (("WallSurface", walls), ("GroundSurface", grounds), ("RoofSurface", roofs)):
        for s in el.findall("bldg:boundedBy/bldg:%s" % kind, NS):
            for p in s.findall(".//gml:posList", NS):
                store.append(pl(p.text))
    gpoly = None
    if grounds:
        gpoly = unary_union([Polygon(g[:, :2]).buffer(0) for g in grounds if len(g) >= 4])
    rz = np.concatenate([r[:, 2] for r in roofs]) if roofs else np.array([np.nan])
    recs[gid] = dict(id=gid, roof_edge=poly, roof_edge_ring=ring, ground=gpoly, walls=walls,
                     lod1_zmin=float(z1.min()), lod1_zmax=float(z1.max()),
                     lod2_zmax=float(np.nanmax(rz)),
                     measuredHeight=float(el.findtext("bldg:measuredHeight", namespaces=NS) or "nan"),
                     storeys=el.findtext("bldg:storeysAboveGround", namespaces=NS),
                     name=el.findtext("gml:name", namespaces=NS),
                     centroid=(c.x, c.y), in_box=bool(abs(c.x) <= 200 and abs(c.y) <= 200))
pickle.dump(recs, open(os.path.join(OUT, "plateau_bldg.pkl"), "wb"))
inb = [r for r in recs.values() if r["in_box"]]
print("parsed", len(recs), "in box (polygon centroid)", len(inb), "lod2", sum(bool(r["walls"]) for r in inb))
# straddling the boundary
strad = [r["id"] for r in recs.values() if r["roof_edge"].intersects(Polygon([(-200, -200), (200, -200), (200, 200), (-200, 200)]))
         and not r["roof_edge"].within(Polygon([(-200, -200), (200, -200), (200, 200), (-200, 200)]))]
print("buildings straddling the box edge", len(strad))
