"""Ishidatami paving ribbons along the Priority-2 street centrelines (documented geometry: OSM centreline,
mapped width; surface=paving_stones/sett).  UVMap: u = metres along, v = metres across.
UVEdge.y = distance to the nearest street edge (m) -> gutter stones in the shader."""
import numpy as np

from kit_common import P2_STREETS, gz, mesh_obj, street_index


def ribbon(s, coll, mat, zoff=0.035):
    c = np.array(s["coords"], float)
    seg = np.diff(c, axis=0); sl = np.linalg.norm(seg, axis=1)
    keep = np.r_[True, sl > 0.05]
    c = c[keep]
    seg = np.diff(c, axis=0); sl = np.linalg.norm(seg, axis=1)
    cum = np.r_[0, np.cumsum(sl)]
    L = cum[-1]
    n = max(2, int(np.ceil(L / 0.5)) + 1)
    d = np.linspace(0, L, n)
    pts = np.c_[np.interp(d, cum, c[:, 0]), np.interp(d, cum, c[:, 1])]
    tg = np.gradient(pts, axis=0)
    tg /= np.maximum(np.linalg.norm(tg, axis=1, keepdims=True), 1e-9)
    # smooth tangents to avoid folds at sharp bends
    for _ in range(3):
        tg[1:-1] = (tg[:-2] + 2 * tg[1:-1] + tg[2:]) / 4
        tg /= np.maximum(np.linalg.norm(tg, axis=1, keepdims=True), 1e-9)
    nrm = np.c_[-tg[:, 1], tg[:, 0]]
    w = float(s["width_m"] or 4.0)
    offs = np.r_[-w / 2, np.linspace(-w / 2 + 0.3, w / 2 - 0.3, 5), w / 2]
    V, UV, UE = [], [], []
    for i in range(n):
        for o in offs:
            p = pts[i] + nrm[i] * o
            V.append((p[0], p[1], 0.0)); UV.append((d[i], o)); UE.append((o / (w / 2), w / 2 - abs(o)))
    V = np.array(V)
    V[:, 2] = gz(V[:, 0], V[:, 1]) + zoff
    m = len(offs)
    F = []
    for i in range(n - 1):
        for j in range(m - 1):
            a = i * m + j
            F.append((a, a + m, a + m + 1, a + 1))
    ob = mesh_obj("Paving_osm%d" % s["osm_id"], V, F, coll, [mat])
    me = ob.data
    vi = np.empty(len(me.loops), np.int32); me.loops.foreach_get("vertex_index", vi)
    for name, arr in (("UVMap", np.array(UV)), ("UVEdge", np.array(UE))):
        uv = me.uv_layers.new(name=name)
        uv.data.foreach_set("uv", arr[vi].ravel())
    me.uv_layers.active_index = 0
    for p in me.polygons:
        p.use_smooth = True
    ob["osm_id"] = str(s["osm_id"]); ob["name_ja"] = s["name"] or ""; ob["surface"] = s["surface"] or ""
    ob["width_m"] = w; ob["width_src"] = s["width_src"]; ob["walkable"] = True
    ob["detail_class"] = "observed"
    ob["evidence_ref"] = "osm:way/%d surface=%s width %.2f m (%s); slab pattern artistic" % (s["osm_id"], s["surface"], w, s["width_src"])
    return ob


def build(coll, mat):
    idx = street_index()
    out = []
    k = 0
    for key, d in P2_STREETS.items():
        for wid in d["ways"]:
            s = idx[wid]
            if s["highway"] == "steps" or s["surface"] not in ("paving_stones", "sett", "stone", "cobblestone"):
                continue
            out.append(ribbon(s, coll, mat, 0.035 + 0.004 * (k % 4)))
            k += 1
    return out
