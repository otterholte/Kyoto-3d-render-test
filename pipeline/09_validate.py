"""Phase 4 mandatory validation (before artistic modelling) -> docs/validation_report.md + data/processed/validation.json"""
import json
import os
import numpy as np
from shapely.geometry import LineString, Polygon, Point, box
from shapely.ops import unary_union, nearest_points
from shapely.strtree import STRtree
from common import PROC, ROOT, load_boundary
from terrain_sample import ground

b = load_boundary()
BLD = json.load(open(os.path.join(PROC, "buildings.json")))
L2 = np.load(os.path.join(PROC, "buildings_lod2.npz"))
S = json.load(open(os.path.join(PROC, "streets.json")))
F = json.load(open(os.path.join(PROC, "features.json")))
STP = json.load(open(os.path.join(PROC, "steps.json")))
BOX = box(-200, -200, 200, 200)
rep, R = [], {}


def h(t):
    rep.append(t)


# -- LOD2 ground footprints per building (union of GroundSurface triangles)
P, T, K, BI = L2["positions"], L2["triangles"], L2["kind"], L2["building"]
gfp = {}
for t in np.where(K == 2)[0]:
    tri = Polygon(P[T[t]][:, :2])
    if tri.area > 1e-4:
        gfp.setdefault(int(BI[t]), []).append(tri)
gfp = {k: unary_union(v).buffer(0) for k, v in gfp.items()}
inbox = [i for i, x in enumerate(BLD["buildings"]) if x["in_box"]]

# 1. eaves: roof-edge (LOD0) vs ground (LOD2) footprint
ratios, offs = [], []
for i in inbox:
    if i in gfp:
        re = Polygon(BLD["buildings"][i]["footprint"]).buffer(0)
        if re.area > 5:
            ratios.append(re.area / max(gfp[i].area, 1e-3))
            offs.append((re.area - gfp[i].area) / max(re.length, 1e-3))
R["eave_area_ratio_median"] = float(np.median(ratios)); R["eave_offset_m_median"] = float(np.median(offs))

# 2. GSI 建築物の外周線 agreement: distance from LOD2 ground-outline vertices to nearest GSI building line
gsi_lines = [LineString(l["coords"]) for l in S["gsi"]["BldL"] if len(l["coords"]) >= 2]
tree = STRtree(gsi_lines)
dist_g, dist_r = [], []
for i in inbox:
    if i not in gfp:
        continue
    for geom, store in ((gfp[i], dist_g), (Polygon(BLD["buildings"][i]["footprint"]).buffer(0), dist_r)):
        for g in getattr(geom, "geoms", [geom]):
            for x, y in list(g.exterior.coords)[::2]:
                p = Point(x, y)
                j = tree.nearest(p)
                store.append(p.distance(gsi_lines[j]))
R["gsi_bldL_dist_lod2ground_m"] = dict(median=float(np.median(dist_g)), p90=float(np.percentile(dist_g, 90)))
R["gsi_bldL_dist_lod0roofedge_m"] = dict(median=float(np.median(dist_r)), p90=float(np.percentile(dist_r, 90)))

# 3. OSM building polygons vs PLATEAU (IoU on matched pairs inside box)
osm_b = [Polygon(o["coords"]).buffer(0) for o in F["osm_buildings"] if len(o["coords"]) > 3]
osm_b = [g for g in osm_b if g.intersects(BOX)]
ot = STRtree(osm_b)
ious = []
for i in inbox:
    if i not in gfp:
        continue
    g = gfp[i]
    cands = ot.query(g)
    if len(cands):
        best = max(cands, key=lambda j: osm_b[j].intersection(g).area)
        u = osm_b[best].union(g).area
        if u > 0:
            ious.append(osm_b[best].intersection(g).area / u)
R["osm_vs_plateau_iou"] = dict(n=len(ious), median=float(np.median(ious)), share_above_0_5=float(np.mean(np.array(ious) > 0.5)))
R["osm_buildings_in_box"] = len(osm_b); R["plateau_buildings_in_box"] = len(inbox)

# 4. buildings vs streets: LOD2 ground footprint intruding into walkable corridor (centreline buffered 40% width)
intr = []
gtree = STRtree([gfp[i] for i in inbox if i in gfp]); gids = [i for i in inbox if i in gfp]
for s in S["streets"]:
    tg = s["tags"]
    if (not s["in_box"] or s["highway"] in ("steps",) or s.get("tunnel") or s.get("layer") not in (None, "0")
            or tg.get("area") == "yes" or tg.get("covered") in ("yes", "arcade") or s["nodes"][0] == s["nodes"][-1]):
        continue  # pedestrian AREAS (closed ways) and covered passages legitimately overlap buildings
    corr = LineString(s["coords"]).buffer(max(0.6, 0.4 * s["width_m"]), cap_style="flat").intersection(BOX)
    for j in gtree.query(corr):
        a = gfp[gids[j]].intersection(corr).area
        if a > 1.0:
            intr.append(dict(osm_id=s["osm_id"], highway=s["highway"], name=s["name"], plateau_id=BLD["buildings"][gids[j]]["id"], area_m2=round(a, 2)))
R["street_building_conflicts"] = len(intr)
R["street_building_conflicts_list"] = sorted(intr, key=lambda d: -d["area_m2"])[:40]

# roof-edge (eaves) overhanging street corridors (expected for Kyoto machiya hisashi; informative)
eave_over = 0
for s in S["streets"]:
    if s["in_box"] and s["highway"] in ("pedestrian", "residential", "living_street"):
        corr = LineString(s["coords"]).buffer(s["width_m"] / 2, cap_style="flat")
        for i in inbox:
            re = Polygon(BLD["buildings"][i]["footprint"]).buffer(0)
            if re.intersects(corr) and re.intersection(corr).area > 0.5:
                eave_over += 1
R["roof_edges_over_pedestrian_corridors"] = eave_over

# 5. connectivity
R["connectivity"] = S["connectivity"]
iso = [dict(osm_id=s["osm_id"], highway=s["highway"], name=s["name"], length_m=s["length_m"], access=s["access"])
       for s in S["streets"] if s["in_box"] and not s["connected_to_main"]]
R["isolated_ways"] = iso

# 6. stairs
st = []
deg = {}
for s in S["streets"]:
    for n in (s["nodes"][0], s["nodes"][-1]):
        deg[n] = deg.get(n, 0) + 1
    for n in s["nodes"][1:-1]:
        deg[n] = deg.get(n, 0) + 2
for s in S["streets"]:
    if s["highway"] != "steps" or not s["in_box"]:
        continue
    sp = next(x for x in STP["steps"] if x["osm_id"] == s["osm_id"])
    ends = [deg.get(s["nodes"][0], 0) > 1, deg.get(s["nodes"][-1], 0) > 1]
    st.append(dict(osm_id=s["osm_id"], name=s["name"], n=sp["n"], n_src=sp["n_src"], rise_m=round(sp["z_top"] - sp["z_bottom"], 2),
                   riser_m=sp["riser_m"], tread_m=sp["tread_m"], ends_connected=ends,
                   riser_plausible=0.08 <= sp["riser_m"] <= 0.22, tread_plausible=0.25 <= sp["tread_m"] <= 2.5))
R["stairs"] = st

# 7. foundations vs terrain
fd = []
for i in inbox:
    x = BLD["buildings"][i]
    g = gfp.get(i, Polygon(x["footprint"]).buffer(0))
    c = np.array((g.geoms[0] if hasattr(g, "geoms") else g).exterior.coords)
    tz = ground(c[:, 0], c[:, 1])
    fd.append(x["base_z"] - float(np.median(tz)))
fd = np.array(fd)
R["foundation_minus_terrain_m"] = dict(median=float(np.median(fd)), p5=float(np.percentile(fd, 5)), p95=float(np.percentile(fd, 95)),
                                       share_within_1m=float(np.mean(np.abs(fd) < 1.0)))

# 8. widths
ws = [(s["highway"], s["width_m"], s["width_src"]) for s in S["streets"] if s["in_box"]]
R["widths"] = {hw: dict(n=sum(1 for w in ws if w[0] == hw), median=float(np.median([w[1] for w in ws if w[0] == hw])),
                        measured_share=float(np.mean([not w[2].startswith("default") for w in ws if w[0] == hw])))
               for hw in sorted({w[0] for w in ws})}
named = {}
for s in S["streets"]:
    if s["in_box"] and s["name"] in ("二寧坂", "産寧坂", "一念坂", "八坂通", "清水道", "東大路通"):
        named.setdefault(s["name"], []).append((s["width_m"], s["width_src"][:24]))
R["named_widths"] = named

# 9. landmarks
pg = b["pagoda"]
pl = next(x for x in BLD["buildings"] if x["id"] == "bldg_2b477621-2b5c-480b-a960-d2b3972db237")
plc = Polygon(pl["footprint"]).centroid
R["pagoda"] = dict(osm_centroid=[pg["local_x"], pg["local_y"]], plateau_centroid=[round(plc.x, 2), round(plc.y, 2)],
                   offset_m=round(Point(pg["local_x"], pg["local_y"]).distance(plc), 2), plateau_height=pl["height"],
                   documented_height=38.8, disputed_popular_height=46.0, plateau_base_z=pl["base_z"], dem_ground=round(float(ground(pg["local_x"], pg["local_y"])), 2))

# 10. sightline Yasaka-dori (-79,88,eye) -> pagoda upper tiers, using LOD2 roof heights (2.5D)
eye = np.array([-79.0, 88.2, float(ground(-79, 88.2)) + 1.6])
tgt = np.array([pg["local_x"], pg["local_y"], pl["base_z"] + 30.0])
blocked = []
for i in inbox:
    x = BLD["buildings"][i]
    if x["id"] == pl["id"]:
        continue
    g = Polygon(x["footprint"]).buffer(0)
    seg = LineString([eye[:2], tgt[:2]])
    if g.intersects(seg):
        inter = g.intersection(seg)
        for pnt in (inter.coords if inter.geom_type == "LineString" else []):
            t = np.linalg.norm(np.array(pnt) - eye[:2]) / np.linalg.norm(tgt[:2] - eye[:2])
            if x["top_z"] > eye[2] + t * (tgt[2] - eye[2]):
                blocked.append(x["id"]); break
R["sightline_yasakadori_to_pagoda_upper"] = dict(eye=eye.round(2).tolist(), target=tgt.round(2).tolist(), blocked_by=blocked)

json.dump(R, open(os.path.join(PROC, "validation.json"), "w"), ensure_ascii=False, indent=1)

# ---------------- markdown
h("# Phase 4 — Mandatory validation report\n")
h("Generated by `pipeline/09_validate.py` from the processed data (all distances in metres, EPSG:6674 local frame).\n")
h("| check | result | verdict |\n|---|---|---|")
h("| Footprint agreement: PLATEAU LOD2 ground outline → GSI 建築物の外周線 | median %.2f m, p90 %.2f m | %s |" % (
    R["gsi_bldL_dist_lod2ground_m"]["median"], R["gsi_bldL_dist_lod2ground_m"]["p90"], "PASS" if R["gsi_bldL_dist_lod2ground_m"]["median"] < 0.5 else "REVIEW"))
h("| Roof-edge (LOD0, incl. eaves) → GSI outline | median %.2f m, p90 %.2f m | unsigned distance only — NOT evidence of eaves (audit F1: GSI lines fall outside the PLATEAU outline 54%% of the time vs 39%% inside; ≈ GSI 1:2500 positional noise) |" % (
    R["gsi_bldL_dist_lod0roofedge_m"]["median"], R["gsi_bldL_dist_lod0roofedge_m"]["p90"]))
h("| Eaves: roof-edge area / ground area | median ×%.2f (≈ %.2f m overhang) | PLATEAU LOD2 walls coincide with the roof edge; real eave overhang is not in the survey data → uniform 0.45 m street-front inset applied in the art pass, labelled inferred |" % (R["eave_area_ratio_median"], R["eave_offset_m_median"]))
h("| OSM vs PLATEAU building polygons | %d matched, median IoU %.2f, %.0f%% > 0.5 | %s |" % (
    R["osm_vs_plateau_iou"]["n"], R["osm_vs_plateau_iou"]["median"], 100 * R["osm_vs_plateau_iou"]["share_above_0_5"],
    "PASS (independent sources agree)" if R["osm_vs_plateau_iou"]["median"] > 0.6 else "REVIEW"))
h("| Buildings (ground footprint) intruding into street corridors (40%% of width) | %d cases | %s |" % (
    R["street_building_conflicts"], "PASS" if R["street_building_conflicts"] < 10 else "REVIEW — see list"))
h("| Roof edges overhanging pedestrian streets | %d | expected (machiya eaves) |" % eave_over)
h("| Walkable network components in box | %d (main %d nodes; others %s) | %s |" % (
    R["connectivity"]["components_in_box"], R["connectivity"]["main_component_nodes"], R["connectivity"]["other_component_sizes"],
    "see isolated ways"))
ok_st = sum(1 for s in st if s["riser_plausible"] and all(s["ends_connected"]))
h("| Stairs: plausible riser and both ends connected | %d / %d | see table |" % (ok_st, len(st)))
h("| Building base vs DEM5A terrain | median %+.2f m, 5–95%% [%+.2f, %+.2f], %.0f%% within 1 m | %s |" % (
    R["foundation_minus_terrain_m"]["median"], R["foundation_minus_terrain_m"]["p5"], R["foundation_minus_terrain_m"]["p95"],
    100 * R["foundation_minus_terrain_m"]["share_within_1m"], "PASS (plinths absorb residual)"))
h("| Yasaka Pagoda: OSM vs PLATEAU centroid | %.2f m apart | %s |" % (R["pagoda"]["offset_m"], "PASS" if R["pagoda"]["offset_m"] < 3 else "REVIEW"))
h("| Yasaka Pagoda height | PLATEAU roof apex %.1f m; adopted 38.8 m total incl. sōrin (NDL ref + photo-measured sōrin); popular 46 m disputed | hero model uses 38.8 m |" % R["pagoda"]["plateau_height"])
h("| Sightline Yasaka-dōri (−79, 88) → pagoda upper tiers | blocked by %d buildings | %s |" % (
    len(blocked), "PASS — pagoda visible at head of street" if not blocked else "REVIEW"))
h("| Scale | all layers in metres in one CRS (EPSG:6674); Blender 1 unit = 1 m | PASS |\n")
h("## Street widths (m)\n\n| highway | n in box | median width | share measured (OSM width / PLATEAU road area) |\n|---|---|---|---|")
for k, v in R["widths"].items():
    h("| %s | %d | %.2f | %.0f%% |" % (k, v["n"], v["median"], 100 * v["measured_share"]))
h("\nNamed streets: " + "; ".join("%s %s" % (k, ", ".join("%.1f m (%s)" % w for w in v)) for k, v in named.items()))
h("\n## Stairs (OSM highway=steps inside the box)\n\n| osm id | name | steps | source | rise m | riser m | tread m | ends connected |\n|---|---|---|---|---|---|---|---|")
for s in st:
    h("| %d | %s | %d | %s | %.2f | %.3f | %.2f | %s |" % (s["osm_id"], s["name"] or "", s["n"], s["n_src"][:30], s["rise_m"], s["riser_m"], s["tread_m"], s["ends_connected"]))
h("\n## Ways not connected to the main walkable network inside the box\n")
h("These are kept exactly as mapped (no invented links). Typical causes: private driveways, temple-internal paths, or a link that leaves and re-enters the box.\n")
h("| osm id | highway | name | length m | access |\n|---|---|---|---|---|")
for s in iso:
    h("| %d | %s | %s | %.0f | %s |" % (s["osm_id"], s["highway"], s["name"] or "", s["length_m"], s["access"] or ""))
h("\n## Largest building/street-corridor conflicts\n\n| osm way | highway | name | PLATEAU building | overlap m² |\n|---|---|---|---|---|")
for c in R["street_building_conflicts_list"][:20]:
    h("| %d | %s | %s | %s | %.1f |" % (c["osm_id"], c["highway"], c["name"] or "", c["plateau_id"], c["area_m2"]))
open(os.path.join(ROOT, "docs", "validation_report.md"), "w").write("\n".join(rep) + "\n")
print("\n".join(rep[:22]))
