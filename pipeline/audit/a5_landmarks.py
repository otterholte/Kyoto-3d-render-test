"""A5: hero pagoda vs OSM / PLATEAU (raw), Kōshin-dō position."""
import json
import math
import os
import pickle
import numpy as np
from shapely.geometry import Polygon, MultiPoint, Point
from acommon import OUT, osm_raw, osm_xy, save

P = pickle.load(open(os.path.join(OUT, "plateau_bldg.pkl"), "rb"))
S = pickle.load(open(os.path.join(OUT, "scene_art.pkl"), "rb"))
nodes, ways, rels = osm_raw()
R = {}
pid = "bldg_2b477621-2b5c-480b-a960-d2b3972db237"
pr = P[pid]
osm = Polygon(osm_xy(nodes, ways[371717416][0]))


def mrr_angle(poly):
    c = np.array(poly.minimum_rotated_rectangle.exterior.coords)
    e = c[1] - c[0]
    a = math.degrees(math.atan2(e[1], e[0])) % 90
    return a if a < 45 else a - 90, sorted([np.linalg.norm(c[1] - c[0]), np.linalg.norm(c[2] - c[1])])


h = S["hero"]
root = h["root"][0]
R["hero_root"] = dict(loc=root["loc"], rot_deg=math.degrees(root["rot"][2]))
R["hero_height_m"] = float(h["bbmax"][2] - root["loc"][2])
R["hero_bbox"] = dict(min=h["bbmin"].tolist(), max=h["bbmax"].tolist())
R["osm"] = dict(centroid=(osm.centroid.x, osm.centroid.y), area=osm.area, mrr=mrr_angle(osm))
R["plateau"] = dict(centroid=(pr["roof_edge"].centroid.x, pr["roof_edge"].centroid.y), area=pr["roof_edge"].area,
                    mrr=mrr_angle(pr["roof_edge"]), measuredHeight=pr["measuredHeight"], lod1_zmin=pr["lod1_zmin"],
                    lod2_zmax=pr["lod2_zmax"], lod1_zmax=pr["lod1_zmax"])
R["osm_vs_plateau_centroid_m"] = osm.centroid.distance(pr["roof_edge"].centroid)
R["hero_vs_osm_centroid_m"] = Point(root["loc"][:2]).distance(osm.centroid)
R["hero_vs_plateau_centroid_m"] = Point(root["loc"][:2]).distance(pr["roof_edge"].centroid)
# PLATEAU tier levels from raw LOD2 roof surfaces (distinct horizontal-ish z levels)
# (re-parse wall tops: use wall polygon z maxima)
zs = np.round(np.concatenate([w[:, 2] for w in pr["walls"]]) - pr["lod1_zmin"], 2)
R["plateau_wall_z_levels_above_base"] = sorted(set(np.round(zs, 1).tolist()))
# hero lowest eave outline: slices within 7.0 .. 9.0 m above base
pts = np.concatenate([v for k, v in h["slices"].items() if 7.0 <= k + (root["loc"][2] - h["bbmin"][2]) <= 9.0] or [np.zeros((0, 2))])
if len(pts) > 3:
    hull = MultiPoint([tuple(p) for p in pts]).convex_hull
    R["hero_eave1_hull_vs_plateau_roofedge"] = dict(area_hull=hull.area, area_plateau=pr["roof_edge"].area,
                                                     iou=hull.intersection(pr["roof_edge"]).area / hull.union(pr["roof_edge"]).area,
                                                     mrr=mrr_angle(hull))
# widest slice per metre for profile
prof = {}
for k, v in sorted(h["slices"].items()):
    if len(v) > 3:
        mp = MultiPoint([tuple(p) for p in v]).minimum_rotated_rectangle
        c = np.array(mp.exterior.coords)
        prof[k] = round(float(max(np.linalg.norm(c[1] - c[0]), np.linalg.norm(c[2] - c[1]))), 2)
R["hero_width_profile_by_0.5m"] = prof
# Kōshin-dō
k = []
for wid, (nds, t) in ways.items():
    if "庚申" in (t.get("name") or ""):
        poly = osm_xy(nodes, nds)
        k.append(dict(type="way", id=wid, tags=t, centroid=Polygon(poly).centroid.coords[0] if len(poly) > 3 else poly.mean(0).tolist()))
for nid, (lon, lat, t) in nodes.items():
    if "庚申" in (t.get("name") or ""):
        k.append(dict(type="node", id=nid, tags=t, xy=osm_xy(nodes, [nid])[0].tolist()))
R["koshindo_osm"] = k
for kk in k:
    if kk["type"] == "way":
        poly = Polygon(osm_xy(nodes, ways[kk["id"]][0]))
        ov = []
        for bid, r in P.items():
            a = r["roof_edge"].intersection(poly).area
            if a > 1:
                ov.append((bid, round(a, 1), round(r["roof_edge"].area, 1), r["measuredHeight"], r["name"],
                           bid in S["buildings"], S["buildings"][bid][0]["colls"] if bid in S["buildings"] else None))
        kk["osm_area"] = poly.area
        kk["plateau_overlaps"] = sorted(ov, key=lambda x: -x[1])[:8]
save("a5_landmarks.json", R)
print(json.dumps({k: v for k, v in R.items() if k != "hero_width_profile_by_0.5m"}, indent=1, ensure_ascii=False, default=str))
print(R["hero_width_profile_by_0.5m"])
