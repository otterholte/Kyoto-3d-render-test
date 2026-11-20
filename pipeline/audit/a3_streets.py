"""A3: streets. Raw OSM highway ways in the box; connectivity; cross-sections vs GSI RdEdg / RdCompt / PLATEAU road;
surface-mask representation; OSM centreline offset from the GSI road-edge midline.
Writes out/a3_streets.json and out/xsections.json (consumed by the bpy ray-cast script c_scene_probe.py)."""
import json
import os
import numpy as np
from PIL import Image
from lxml import etree
from shapely.geometry import LineString, Point, Polygon, box
from shapely.ops import unary_union
from shapely.strtree import STRtree
from acommon import ROOT, RAW, OUT, osm_raw, osm_xy, gsi_fgd, jgd_xy, save

BOX = box(-200, -200, 200, 200)
nodes, ways, rels = osm_raw()
EXCL = {"construction", "proposed", "platform", "bus_stop", "razed", "abandoned"}
hw = {}
for wid, (nds, t) in ways.items():
    if "highway" not in t or t["highway"] in EXCL:
        continue
    xy = osm_xy(nodes, nds)
    if len(xy) < 2:
        continue
    ln = LineString(xy)
    if ln.intersects(BOX):
        hw[wid] = dict(nds=nds, tags=t, line=ln, xy=xy)
R = dict(n_highway_ways_in_box=len(hw))
from collections import Counter
R["by_type"] = dict(Counter(v["tags"]["highway"] for v in hw.values()))
# ---- connectivity (nodes inside the box, all highway ways)
inb = {}
for wid, v in hw.items():
    for i, nid in enumerate(v["nds"]):
        if nid in nodes:
            p = osm_xy(nodes, [nid])[0]
            if abs(p[0]) <= 200 and abs(p[1]) <= 200:
                inb[nid] = p
adj = {n: set() for n in inb}
for wid, v in hw.items():
    for a, b in zip(v["nds"][:-1], v["nds"][1:]):
        if a in adj and b in adj:
            adj[a].add(b); adj[b].add(a)
comp, cid = {}, 0
for s in adj:
    if s in comp:
        continue
    st = [s]; comp[s] = cid
    while st:
        u = st.pop()
        for w in adj[u]:
            if w not in comp:
                comp[w] = cid; st.append(w)
    cid += 1
sizes = Counter(comp.values())
main = sizes.most_common(1)[0][0]
iso = []
for wid, v in hw.items():
    cs = {comp[n] for n in v["nds"] if n in comp}
    if cs and main not in cs:
        iso.append(dict(osm_id=wid, highway=v["tags"]["highway"], access=v["tags"].get("access"), name=v["tags"].get("name"),
                        len_in_box=round(v["line"].intersection(BOX).length, 1), comp_size=max(sizes[c] for c in cs)))
R["connectivity"] = dict(components=len(sizes), sizes=sorted(sizes.values(), reverse=True)[:10], isolated_ways=iso)
# components only via steps/pedestrian? check whether all steps ways connect at both ends
steps = {wid: v for wid, v in hw.items() if v["tags"]["highway"] == "steps"}
R["steps"] = []
for wid, v in steps.items():
    ends = [v["nds"][0], v["nds"][-1]]
    deg = []
    for e in ends:
        n_ways = sum(1 for w2, v2 in hw.items() if w2 != wid and e in v2["nds"])
        deg.append(n_ways)
    R["steps"].append(dict(osm_id=wid, name=v["tags"].get("name"), step_count=v["tags"].get("step_count"),
                           incline=v["tags"].get("incline"), width=v["tags"].get("width"),
                           end_connections=deg, length=round(v["line"].length, 2),
                           in_box_fully=v["line"].within(BOX), xy0=v["xy"][0].round(2).tolist(), xy1=v["xy"][-1].round(2).tolist()))
# ---- surface mask representation (the scene's terrain texture)
mask = np.asarray(Image.open(os.path.join(ROOT, "data", "processed", "surface_mask.png")))
EXT = json.load(open(os.path.join(ROOT, "data", "processed", "steps.json")))["extent"]


def mclass(x, y):
    c = int((x - EXT[0]) / 0.5); r = int((EXT[3] - y) / 0.5)
    if not (0 <= r < mask.shape[0] and 0 <= c < mask.shape[1]):
        return "outside"
    px = mask[r, c]
    return "R" if px[0] > 127 else "G" if px[1] > 127 else "B" if px[2] > 127 else "soil"


cov = []
for wid, v in hw.items():
    li = v["line"].intersection(BOX)
    if li.is_empty:
        continue
    L = li.length
    pts = [li.interpolate(d) for d in np.arange(0, L + 1e-6, 2.0)] if L > 0 else []
    cls = [mclass(p.x, p.y) for p in pts]
    soil = sum(c == "soil" for c in cls)
    cov.append(dict(osm_id=wid, highway=v["tags"]["highway"], name=v["tags"].get("name"), surface=v["tags"].get("surface"),
                    n=len(cls), frac_paved=1 - soil / max(1, len(cls)), counts=dict(Counter(cls))))
R["surface_mask"] = dict(n_ways=len(cov), ways_fully_paved=sum(c["frac_paved"] == 1 for c in cov),
                         ways_below_90pct=[c for c in cov if c["frac_paved"] < 0.9],
                         points=sum(c["n"] for c in cov), points_soil=sum(c["counts"].get("soil", 0) for c in cov))
# ---- cross-sections
rde = gsi_fgd("RdEdg"); rdc = gsi_fgd("RdCompt")
rlines = [LineString(f["xy"]) for f in rde if len(f["xy"]) >= 2]
clines = [LineString(f["xy"]) for f in rdc if len(f["xy"]) >= 2]
rtree = STRtree(rlines); ctree = STRtree(clines)
NS = {"gml": "http://www.opengis.net/gml", "tran": "http://www.opengis.net/citygml/transportation/2.0"}
troot = etree.parse(os.path.join(RAW, "plateau", "udx", "tran", "52353692_tran_6697_op.gml")).getroot()
rp = []
for pl in troot.iter("{http://www.opengis.net/gml}Polygon"):
    ext = np.array(pl.find("gml:exterior//gml:posList", NS).text.split(), float).reshape(-1, 3)
    x, y = jgd_xy(ext[:, 1], ext[:, 0])
    g = Polygon(np.c_[x, y]).buffer(0)
    if g.intersects(BOX.buffer(50)):
        rp.append(g)
road = unary_union(rp)
PROC_STREETS = {s["osm_id"]: s for s in json.load(open(os.path.join(ROOT, "data", "processed", "streets.json")))["streets"]}
STREETS = {"Yasaka-dori": [24516359, 710696944], "Ninenzaka": [30913263, 30882783, 550360170, 1491152444, 1569088149],
           "Sannenzaka": [526198271, 1569088146, 1569088147, 179116810, 1251544286], "Higashioji": [174762077, 1193882822]}


def side_hits(p, nrm, lines, tree, reach):
    seg = LineString([(p.x - nrm[0] * reach, p.y - nrm[1] * reach), (p.x + nrm[0] * reach, p.y + nrm[1] * reach)])
    L, Rr = None, None
    for i in tree.query(seg):
        it = seg.intersection(lines[i])
        for g in getattr(it, "geoms", [it]):
            if g.is_empty or g.geom_type != "Point":
                continue
            s = (g.x - p.x) * nrm[0] + (g.y - p.y) * nrm[1]
            if s > 0.3 and (Rr is None or s < Rr):
                Rr = s
            if s < -0.3 and (L is None or -s < L):
                L = -s
    return L, Rr


def area_extent(p, nrm, poly, reach):
    seg = LineString([(p.x - nrm[0] * reach, p.y - nrm[1] * reach), (p.x + nrm[0] * reach, p.y + nrm[1] * reach)])
    it = seg.intersection(poly)
    best = None
    for g in getattr(it, "geoms", [it]):
        if g.is_empty or g.geom_type != "LineString":
            continue
        if g.distance(p) < 0.6:
            best = g.length if best is None else max(best, g.length)
    return best


def mask_extent(p, nrm, reach):
    """contiguous non-soil extent through the centreline point (0.25 m steps)"""
    c0 = mclass(p.x, p.y)
    if c0 == "soil":
        return 0.0
    ext = []
    for sg in (-1, 1):
        d = 0.0
        while d < reach and mclass(p.x + sg * nrm[0] * (d + 0.25), p.y + sg * nrm[1] * (d + 0.25)) != "soil":
            d += 0.25
        ext.append(d)
    return sum(ext)


xs = []
for name, wids in STREETS.items():
    reach = 25 if name == "Higashioji" else 12
    for wid in wids:
        v = hw.get(wid)
        if v is None:
            continue
        li = v["line"].intersection(BOX)
        for g in getattr(li, "geoms", [li]):
            if g.length < 2:
                continue
            step = 10.0 if name == "Higashioji" else 6.0
            for d in np.arange(1.0, g.length - 0.5, step):
                p = g.interpolate(d); q = g.interpolate(min(d + 0.5, g.length)); q0 = g.interpolate(max(d - 0.5, 0))
                t = np.array([q.x - q0.x, q.y - q0.y]); t /= np.linalg.norm(t)
                nrm = np.array([-t[1], t[0]])
                L, Rr = side_hits(p, nrm, rlines, rtree, reach)
                cl, cr = side_hits(p, nrm, clines, ctree, reach)
                rec = dict(street=name, osm_id=wid, highway=v["tags"]["highway"], x=p.x, y=p.y, nx=nrm[0], ny=nrm[1],
                           gsi_left=L, gsi_right=Rr, gsi_width=(L + Rr) if (L and Rr) else None,
                           gsi_mid_offset=((Rr - L) / 2) if (L and Rr) else None,
                           sidewalk_left=cl, sidewalk_right=cr,
                           plateau_width=area_extent(p, nrm, road, reach),
                           scene_width_used=PROC_STREETS.get(wid, {}).get("width_m"),
                           scene_width_src=PROC_STREETS.get(wid, {}).get("width_src"),
                           osm_width_tag=v["tags"].get("width"), mask_width=mask_extent(p, nrm, reach))
                xs.append(rec)
json.dump(xs, open(os.path.join(OUT, "xsections.json"), "w"), indent=0, ensure_ascii=False)


def st(v):
    v = np.array([x for x in v if x is not None], float)
    return dict(n=len(v), median=round(float(np.median(v)), 2), p10=round(float(np.percentile(v, 10)), 2),
                p90=round(float(np.percentile(v, 90)), 2)) if len(v) else dict(n=0)


R["xsections"] = {}
for name in STREETS:
    X = [x for x in xs if x["street"] == name]
    R["xsections"][name] = dict(n=len(X), gsi_width=st([x["gsi_width"] for x in X]), plateau_width=st([x["plateau_width"] for x in X]),
                                mask_width=st([x["mask_width"] for x in X]), scene_width_used=st([x["scene_width_used"] for x in X]),
                                osm_offset_from_gsi_mid=st([abs(x["gsi_mid_offset"]) if x["gsi_mid_offset"] is not None else None for x in X]),
                                n_with_both_gsi_edges=sum(x["gsi_width"] is not None for x in X))
save("a3_streets.json", R)
print(json.dumps({k: v for k, v in R.items() if k not in ("steps",)}, indent=1, ensure_ascii=False, default=str)[:7000])
