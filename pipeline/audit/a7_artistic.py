"""A7: artistic content: flags present? does any artistic / kit / vegetation instance stand in a real street
(OSM centreline buffer at mapped width, or GSI road-edge polygon) or inside a building?"""
import json
import os
import pickle
import collections
import numpy as np
from shapely.geometry import LineString, Point, box
from shapely.ops import unary_union, polygonize
from shapely.strtree import STRtree
from acommon import OUT, osm_raw, osm_xy, gsi_fgd, save

S = pickle.load(open(os.path.join(OUT, "scene_art.pkl"), "rb"))
E = S["empties"]
BOX = box(-200, -200, 200, 200)
R = {}
# ---- flags
by = collections.defaultdict(lambda: collections.Counter())
for e in E:
    c = e["colls"][0] if e["colls"] else "?"
    p = e["props"]
    key = "artistic=%s|detail_class=%s" % (p.get("artistic"), p.get("detail_class"))
    by[c][key] += 1
R["empties_flags_by_collection"] = {k: dict(v) for k, v in by.items()}
unflagged = [e["name"] for e in E if e["props"].get("artistic") is None and e["props"].get("detail_class") is None and e["inst"]]
R["empties_without_any_flag"] = dict(n=len(unflagged), examples=unflagged[:10])
om = S["other_meshes"]
mb = collections.defaultdict(lambda: collections.Counter())
for o in om:
    c = o["colls"][0] if o["colls"] else "?"
    mb[c]["artistic=%s|detail_class=%s" % (o["props"].get("artistic"), o["props"].get("detail_class"))] += 1
R["meshes_flags_by_collection"] = {k: dict(v) for k, v in mb.items()}
# ---- street corridors
nodes, ways, rels = osm_raw()
PROC = {s["osm_id"]: s for s in json.load(open(os.path.join(os.path.dirname(OUT), "..", "..", "data", "processed", "streets.json")))["streets"]}
corr = []
for wid, (nds, t) in ways.items():
    if "highway" not in t or t["highway"] in ("construction", "proposed", "platform", "bus_stop"):
        continue
    xy = osm_xy(nodes, nds)
    if len(xy) < 2:
        continue
    ln = LineString(xy)
    if not ln.intersects(BOX):
        continue
    w = PROC.get(wid, {}).get("width_m") or 2.0
    corr.append((wid, t["highway"], ln.buffer(max(0.6, w / 2 - 0.3), cap_style=2)))
ctree = STRtree([c[2] for c in corr])
rl = [LineString(f["xy"]) for f in gsi_fgd("RdEdg") if len(f["xy"]) >= 2]
roadpolys = [p for p in polygonize(unary_union(rl)) if p.area < 20000]
B = S["buildings"]
walls = [(k, v[0]["wall15"]) for k, v in B.items() if v[0]["wall15"] is not None]
wtree = STRtree([w[1] for w in walls])
hits = collections.Counter(); samples = collections.defaultdict(list)
for e in E:
    x, y, z = e["loc"]
    if abs(x) > 200 or abs(y) > 200:
        continue
    c = e["colls"][0] if e["colls"] else "?"
    piece = e["props"].get("kit_piece") or e["inst"]
    art = e["props"].get("artistic") or e["props"].get("detail_class") == "artistic"
    pt = Point(x, y)
    instreet = [corr[i] for i in ctree.query(pt) if corr[i][2].contains(pt)]
    inbld = [walls[i][0] for i in wtree.query(pt) if walls[i][1].buffer(-0.3).contains(pt)]
    grp = "%s|%s|artistic=%s" % (c, (piece or "?").split(".")[0], bool(art))
    hits[(grp, "total")] += 1
    if instreet:
        hits[(grp, "in_osm_corridor")] += 1
        if len(samples[grp + "/street"]) < 4:
            samples[grp + "/street"].append((e["name"], round(x, 1), round(y, 1), instreet[0][0], instreet[0][1]))
    if inbld:
        hits[(grp, "inside_building")] += 1
        if len(samples[grp + "/bld"]) < 3:
            samples[grp + "/bld"].append((e["name"], round(x, 1), round(y, 1), inbld[0]))
tab = collections.defaultdict(dict)
for (g, k), v in hits.items():
    tab[g][k] = v
R["placement"] = dict(tab)
R["placement_examples"] = dict(samples)
save("a7_artistic.json", R)
print(json.dumps(R, indent=1, default=str)[:9000])
