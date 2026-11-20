"""A4b/A8: building burial (terrain vs PLATEAU base) with DEM5A-derived scene terrain vs PLATEAU TIN; scale checks."""
import json
import os
import pickle
import numpy as np
from scipy.ndimage import map_coordinates
from shapely.geometry import Point
from matplotlib.tri import Triangulation, LinearTriInterpolator
from acommon import ROOT, OUT, save

t = np.load(os.path.join(ROOT, "data", "processed", "terrain.npz"))
H = t["heights"]; X0 = float(t["x0"]); ST = float(t["step"])


def g(x, y):
    return map_coordinates(H, [(np.asarray(y) - X0) / ST, (np.asarray(x) - X0) / ST], order=1)


D = np.load(os.path.join(OUT, "dem_ref.npz"))
T = D["tin"]
pts = T.reshape(-1, 3)
uniq, inv = np.unique(np.round(pts[:, :2], 3), axis=0, return_inverse=True)
zz = np.zeros(len(uniq)); zz[inv.ravel()] = pts[:, 2]
tri = Triangulation(uniq[:, 0], uniq[:, 1], inv.reshape(-1, 3))
tin = LinearTriInterpolator(tri, zz)
P = pickle.load(open(os.path.join(OUT, "plateau_bldg.pkl"), "rb"))
R = {}
rows = []
for k, r in P.items():
    if not r["in_box"]:
        continue
    ring = r["roof_edge_ring"][:, :2]
    # sample the outline densely (where walls meet the ground)
    s = []
    for a, b in zip(ring[:-1], ring[1:]):
        n = max(1, int(np.linalg.norm(b - a) / 1.0))
        s += [a + (b - a) * i / n for i in range(n)]
    s = np.array(s)
    zt = g(s[:, 0], s[:, 1]); zp = np.asarray(tin(s[:, 0], s[:, 1]).filled(np.nan))
    rows.append(dict(id=k, base=r["lod1_zmin"], height=r["measuredHeight"], area=r["roof_edge"].area,
                     scene_min=float(zt.min()), scene_med=float(np.median(zt)), tin_min=float(np.nanmin(zp)) if np.isfinite(zp).any() else np.nan,
                     tin_med=float(np.nanmedian(zp)) if np.isfinite(zp).any() else np.nan, cx=r["centroid"][0], cy=r["centroid"][1]))
b = np.array([[x["scene_min"] - x["base"], x["tin_min"] - x["base"], x["scene_med"] - x["tin_med"]] for x in rows])
R["outline_min_terrain_minus_plateau_base"] = dict(
    scene=dict(median=float(np.median(b[:, 0])), p95=float(np.percentile(b[:, 0], 95)), n_gt_1m=int((b[:, 0] > 1).sum()), n_gt_2m=int((b[:, 0] > 2).sum())),
    plateau_tin=dict(median=float(np.nanmedian(b[:, 1])), p95=float(np.nanpercentile(b[:, 1], 95)), n_gt_1m=int((b[:, 1] > 1).sum()), n_gt_2m=int((b[:, 1] > 2).sum())))
worst = sorted(rows, key=lambda x: -(x["scene_min"] - x["base"]))[:10]
R["most_buried_buildings"] = [dict(id=x["id"], centroid=(round(x["cx"], 1), round(x["cy"], 1)), base=x["base"], height=x["height"],
                                   area=round(x["area"]), scene_min_above_base=round(x["scene_min"] - x["base"], 2),
                                   tin_min_above_base=round(x["tin_min"] - x["base"], 2),
                                   buried_fraction_of_height_at_lowest_wall=round((x["scene_min"] - x["base"]) / x["height"], 2) if x["height"] else None)
                              for x in worst]
pickle.dump(rows, open(os.path.join(OUT, "a8_rows.pkl"), "wb"))
# ---- scale: storeys
st = {}
for r in P.values():
    if r["in_box"] and r["storeys"] and not np.isnan(r["measuredHeight"]):
        st.setdefault(int(r["storeys"]), []).append(r["measuredHeight"])
R["plateau_height_by_storeys"] = {k: dict(n=len(v), median=float(np.median(v)), p10=float(np.percentile(v, 10)), p90=float(np.percentile(v, 90))) for k, v in sorted(st.items())}
S = pickle.load(open(os.path.join(OUT, "scene_art.pkl"), "rb"))
kit = {}
for e in S["empties"]:
    kp = e["props"].get("kit_piece")
    if kp in ("K_Hisashi", "K_Door", "K_Koshi", "K_Window2F", "K_Mushiko"):
        x, y, z = e["loc"]
        kit.setdefault(kp, []).append(z - float(g([x], [y])[0]))
R["kit_height_above_terrain"] = {k: dict(n=len(v), median=float(np.median(v)), p10=float(np.percentile(v, 10)), p90=float(np.percentile(v, 90))) for k, v in kit.items()}
save("a8_scale_terrain.json", R)
print(json.dumps(R, indent=1, default=str))
