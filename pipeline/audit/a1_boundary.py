"""A1: re-derive the boundary from raw OSM; verify the box is metric (EPSG:6674), corners, mesh code."""
import json
import math
import os
import numpy as np
from pyproj import Geod, Transformer
from shapely.geometry import Polygon
from acommon import ROOT, osm_raw, T_OSM, save

nodes, ways, rels = osm_raw()
cands = [(wid, t) for wid, (nds, t) in ways.items() if t.get("building") == "pagoda" or t.get("name") == "八坂の塔"]
res = dict(candidates=[(w, t.get("name"), t.get("building"), t.get("height")) for w, t in cands])
wid = 371717416
nds, tags = ways[wid]
ll = np.array([nodes[i][:2] for i in nds])
e, n = T_OSM.transform(ll[:, 0], ll[:, 1])
poly = Polygon(np.c_[e, n])
pe, pn = poly.centroid.x, poly.centroid.y
inv = Transformer.from_crs(6674, 4326, always_xy=True)
plon, plat = inv.transform(pe, pn)
res["pagoda"] = dict(osm_way=wid, tags=tags, centroid_e=pe, centroid_n=pn, lon=plon, lat=plat, area=poly.area)
B = json.load(open(os.path.join(ROOT, "data", "processed", "boundary.json")))
OE, ON = B["origin_e"], B["origin_n"]
res["origin_offset_from_pagoda_m"] = dict(dE=OE - pe, dN=ON - pn)
corners = [(OE - 200, ON - 200), (OE + 200, ON - 200), (OE + 200, ON + 200), (OE - 200, ON + 200)]
cll = [inv.transform(*c) for c in corners]
res["corners_lonlat_rederived"] = cll
res["corners_lonlat_doc"] = B["corners_lonlat"]
res["corner_max_diff_deg"] = float(np.max(np.abs(np.array(cll) - np.array(B["corners_lonlat"]))))
g = Geod(ellps="GRS80")
sides = []
for a, b in zip(cll, cll[1:] + cll[:1]):
    sides.append(g.inv(a[0], a[1], b[0], b[1])[2])
res["geodesic_side_lengths_m"] = sides
# if the box were degree-based, S and N edges would have identical latitudes
res["lat_SW_minus_lat_SE_deg"] = cll[0][1] - cll[1][1]
res["lon_SW_minus_lon_NW_deg"] = cll[0][0] - cll[3][0]
lat0, lon0 = inv.transform(OE, ON)[::-1]
e1, n1 = T_OSM.transform(lon0, lat0 + 0.001)
res["grid_convergence_deg"] = math.degrees(math.atan2(e1 - OE, n1 - ON))
res["pagoda_local"] = (pe - OE, pn - ON)


def mesh3(lat, lon):
    p = int(lat * 1.5); u = int(lon - 100)
    q = int((lat * 1.5 - p) * 8); v = int((lon - 100 - u) * 8)
    r = int(((lat * 1.5 - p) * 8 - q) * 10 + 1e-9); w = int(((lon - 100 - u) * 8 - v) * 10 + 1e-9)
    return f"{p:02d}{u:02d}{q}{v}{r}{w}"


meshes = set()
for i in range(41):
    for j in range(41):
        lo, la = inv.transform(OE - 200 + 10 * i, ON - 200 + 10 * j)
        meshes.add(mesh3(la, lo))
res["mesh3_in_box"] = sorted(meshes)
# 100 m backdrop margin: which meshes would be needed?
mm = set()
for i in range(61):
    for j in range(61):
        lo, la = inv.transform(OE - 300 + 10 * i, ON - 300 + 10 * j)
        mm.add(mesh3(la, lo))
res["mesh3_in_box_plus_100m_margin"] = sorted(mm)
# mesh 52353692 bounds
res["mesh_52353692_bounds"] = dict(lat=[34 + 11 / 12 + 0.075, 35.0], lon=[135.775, 135.7875])
save("a1_boundary.json", res)
print(json.dumps(res, indent=1, ensure_ascii=False, default=str))
