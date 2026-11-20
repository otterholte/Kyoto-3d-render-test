"""A2b: scene buildings vs raw PLATEAU GML vs GSI BldL; art-pass wall inset effect."""
import json
import os
import pickle
import collections
import numpy as np
from shapely.geometry import Polygon, LineString, Point, box
from shapely.ops import unary_union, polygonize
from shapely.strtree import STRtree
from acommon import OUT, gsi_fgd, save

P = pickle.load(open(os.path.join(OUT, "plateau_bldg.pkl"), "rb"))
SB = pickle.load(open(os.path.join(OUT, "scene_blockout.pkl"), "rb"))["buildings"]
SA = pickle.load(open(os.path.join(OUT, "scene_art.pkl"), "rb"))["buildings"]
BOX = box(-200, -200, 200, 200)
R = {}


def iou(a, b):
    if a is None or b is None or a.is_empty or b.is_empty:
        return np.nan
    return a.intersection(b).area / a.union(b).area


def hausdorff(a, b):
    return a.exterior.hausdorff_distance(b.exterior) if a.geom_type == "Polygon" and b.geom_type == "Polygon" else a.hausdorff_distance(b)


# ---- inventory
inbox_gml = {k for k, r in P.items() if r["in_box"]}
scene_ids_b = set(SB); scene_ids_a = set(SA)
dup_b = {k: len(v) for k, v in SB.items() if len(v) > 1}
dup_a = {k: len(v) for k, v in SA.items() if len(v) > 1}
inbox_scene_b = {k for k, v in SB.items() if any(c.startswith("30_") or c == "35_Landmarks" for c in v[0]["colls"])}
R["inventory"] = dict(gml_within_300m=len(P), gml_in_box_by_polygon_centroid=len(inbox_gml),
                      scene_blockout_ids=len(scene_ids_b), scene_art_ids=len(scene_ids_a),
                      duplicates_blockout=dup_b, duplicates_art=dup_a,
                      in_box_collections_blockout=len(inbox_scene_b),
                      gml_not_in_scene=sorted(set(P) - scene_ids_b),
                      scene_not_in_gml=sorted(scene_ids_b - set(P)),
                      in_box_gml_but_scene_backdrop=sorted(inbox_gml - inbox_scene_b),
                      scene_inbox_but_gml_centroid_outside=sorted(inbox_scene_b - inbox_gml))
for k in R["inventory"]["in_box_gml_but_scene_backdrop"] + R["inventory"]["scene_inbox_but_gml_centroid_outside"]:
    r = P[k]
    R.setdefault("boundary_class_mismatch", []).append(dict(id=k, centroid=np.round(r["centroid"], 2).tolist(),
                                                            area=round(r["roof_edge"].area, 1),
                                                            frac_inside_box=round(r["roof_edge"].intersection(BOX).area / r["roof_edge"].area, 2)))
# ---- blockout & art roof outline vs GML roof edge
rows = []
for k in sorted(inbox_gml & scene_ids_b):
    g = P[k]["roof_edge"]
    for tag, S in (("blockout", SB), ("art", SA)):
        if k not in S:
            continue
        s = S[k][0]
        ro = s["roof"]
        if ro is None or ro.is_empty:
            rows.append(dict(id=k, scene=tag, iou=np.nan)); continue
        c0, c1 = g.centroid, ro.centroid
        rows.append(dict(id=k, scene=tag, iou=iou(g, ro), dc=float(np.hypot(c1.x - c0.x, c1.y - c0.y)),
                         dx=c1.x - c0.x, dy=c1.y - c0.y, haus=float(ro.hausdorff_distance(g)),
                         area_ratio=ro.area / g.area,
                         dz_top=s["zmax"] - P[k]["lod2_zmax"] if not np.isnan(P[k]["lod2_zmax"]) else s["zmax"] - P[k]["lod1_zmax"],
                         prio=s["props"].get("priority")))


def stats(v):
    v = np.asarray([x for x in v if not np.isnan(x)])
    return dict(n=len(v), median=float(np.median(v)), p90=float(np.percentile(v, 90)), p99=float(np.percentile(v, 99)),
                max=float(v.max()), mean=float(v.mean())) if len(v) else {}


for tag in ("blockout", "art"):
    rr = [r for r in rows if r["scene"] == tag]
    R["roof_vs_gml_" + tag] = dict(iou=stats([r["iou"] for r in rr]), centroid_offset=stats([r.get("dc", np.nan) for r in rr]),
                                   hausdorff=stats([r.get("haus", np.nan) for r in rr]),
                                   area_ratio=stats([r.get("area_ratio", np.nan) for r in rr]),
                                   dz_top=stats([r.get("dz_top", np.nan) for r in rr]),
                                   worst=sorted([r for r in rr if not np.isnan(r["iou"])], key=lambda r: r["iou"])[:8])
# ---- wall cross-section (1.5 m above base): blockout vs GML LOD2 walls vs art
def gml_wall_cut(rec, z):
    segs = []
    for w in rec["walls"]:
        d = w[:, 2] - z
        pts = []
        for i in range(len(w) - 1):
            if (d[i] < 0) != (d[i + 1] < 0):
                t = d[i] / (d[i] - d[i + 1]); pts.append(w[i, :2] + (w[i + 1, :2] - w[i, :2]) * t)
        if len(pts) >= 2:
            segs.append(LineString(pts[:2]))
    return unary_union(segs) if segs else None


wrows = []
for k in sorted(inbox_gml & scene_ids_a):
    a = SA[k][0]; b = SB[k][0]
    pr = a["props"].get("priority")
    ins = json.loads(a["props"]["wall_inset_m"]) if "wall_inset_m" in a["props"] else None
    wa, wb = a["wall15"], b["wall15"]
    row = dict(id=k, prio=pr, inset_mean=float(np.mean(ins)) if ins else 0.0, inset_max=float(np.max(ins)) if ins else 0.0)
    if wa is not None and wb is not None:
        row.update(area_b=wb.area, area_a=wa.area, area_loss=1 - wa.area / wb.area,
                   centroid_shift=float(wa.centroid.distance(wb.centroid)),
                   shift_dx=wa.centroid.x - wb.centroid.x, shift_dy=wa.centroid.y - wb.centroid.y,
                   iou_ab=iou(wa, wb), roof_minus_wall_a=float(a["roof"].area - wa.area) if a["roof"] is not None else np.nan)
    wrows.append(row)
p2 = [r for r in wrows if r["prio"] == 2 and "area_b" in r]
p3 = [r for r in wrows if r["prio"] == 3 and "area_b" in r]
R["art_wall_inset_P2"] = dict(n_P2=len([r for r in wrows if r["prio"] == 2]), n_with_closed_outline=len(p2),
                             area_loss=stats([r["area_loss"] for r in p2]), centroid_shift=stats([r["centroid_shift"] for r in p2]),
                             inset_mean=stats([r["inset_mean"] for r in p2]), inset_max=stats([r["inset_max"] for r in p2]),
                             worst_shift=sorted(p2, key=lambda r: -r["centroid_shift"])[:8])
R["art_wall_P3_unchanged"] = dict(n=len(p3), centroid_shift=stats([r["centroid_shift"] for r in p3]), area_loss=stats([r["area_loss"] for r in p3]))
R["wall_outline_closed_fraction"] = dict(blockout=float(np.mean([SB[k][0]["wall15"] is not None for k in inbox_gml & scene_ids_b])),
                                         art=float(np.mean([SA[k][0]["wall15"] is not None for k in inbox_gml & scene_ids_a])))

# ---- GSI BldL vs PLATEAU roof edge (independent source)
bl = gsi_fgd("BldL")
lines = [LineString(f["xy"]) for f in bl if len(f["xy"]) >= 2]
polys = list(polygonize(unary_union(lines)))
polys = [p for p in polys if p.area > 4 and p.intersects(BOX.buffer(20))]
tree = STRtree(polys)
grow = []
for k in sorted(inbox_gml):
    g = P[k]["roof_edge"]
    best = None
    for i in tree.query(g):
        v = iou(g, polys[i])
        if best is None or v > best[0]:
            best = (v, i)
    if best is None or best[0] < 0.3:
        grow.append(dict(id=k, iou=best[0] if best else 0.0, matched=False, area=g.area)); continue
    q = polys[best[1]]
    grow.append(dict(id=k, iou=best[0], matched=True, dx=q.centroid.x - g.centroid.x, dy=q.centroid.y - g.centroid.y,
                     area_ratio=q.area / g.area, haus=float(q.exterior.hausdorff_distance(g.exterior))))
m = [r for r in grow if r["matched"]]
dx = np.array([r["dx"] for r in m]); dy = np.array([r["dy"] for r in m])
# vertex-to-line distance from PLATEAU roof edge vertices to nearest BldL (all lines)
lt = STRtree(lines)
dists, signed = [], []
for k in sorted(inbox_gml):
    ring = P[k]["roof_edge_ring"][:, :2]
    g = P[k]["roof_edge"]
    for p in ring[:-1]:
        pt = Point(p)
        i = lt.nearest(pt)
        d = lines[i].distance(pt)
        if d < 3:
            dists.append(d)
            # sign: is the nearest BldL point inside (+) or outside (-) the PLATEAU polygon?
            q = lines[i].interpolate(lines[i].project(pt))
            signed.append(d if g.buffer(1e-3).contains(q) else -d)
R["gsi_bldl_vs_plateau"] = dict(n_bldl_lines=len(lines), n_bldl_polys=len(polys), n_plateau_in_box=len(inbox_gml),
                                n_matched_iou_gt_0_3=len(m), unmatched=[r["id"] for r in grow if not r["matched"]][:40],
                                n_unmatched=len(grow) - len(m),
                                iou=stats([r["iou"] for r in m]), centroid_dx_mean=float(dx.mean()), centroid_dy_mean=float(dy.mean()),
                                centroid_dx_median=float(np.median(dx)), centroid_dy_median=float(np.median(dy)),
                                centroid_offset=stats(np.hypot(dx, dy)), area_ratio=stats([r["area_ratio"] for r in m]),
                                hausdorff=stats([r["haus"] for r in m]),
                                vertex_to_bldl=stats(dists), signed_vertex_to_bldl=stats(signed),
                                frac_bldl_inside_plateau=float(np.mean(np.array(signed) > 0.05)),
                                frac_bldl_outside_plateau=float(np.mean(np.array(signed) < -0.05)))
pickle.dump(dict(rows=rows, wrows=wrows, grow=grow, gsi_polys=polys), open(os.path.join(OUT, "a2_rows.pkl"), "wb"))
save("a2_footprints.json", R)
print(json.dumps({k: v for k, v in R.items() if k != "inventory"}, indent=1, default=str)[:6000])
print(json.dumps({k: (v if not isinstance(v, list) or len(v) < 30 else (len(v), v[:10])) for k, v in R["inventory"].items()}, indent=1))
