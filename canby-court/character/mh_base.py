"""MakeHuman hm08 base-mesh loader for Blender (bpy 5.2, headless).

Reads the CC0 MakeHuman assets fetched by fetch_assets.sh, applies macro and
detail morph targets with numpy (re-implementing MakeHuman's macro weighting),
fits proxies (.mhclo, used for the eyes) and builds the game-engine skeleton
from the joint cubes. Everything stays in base-mesh vertex order so that the
MakeHuman skin weights can be applied directly.

Coordinates: MakeHuman obj is Y-up in decimetres; Blender is Z-up metres,
character faces -Y (= glTF +Z).
"""
import json
import os
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "_mh_cache")


def mh_to_blender(co):
    co = np.asarray(co, dtype=np.float64)
    return np.stack([co[..., 0], -co[..., 2], co[..., 1]], axis=-1) * 0.1


# ---------------------------------------------------------------- obj parsing
def load_obj(path):
    verts, uvs, faces, fuv, fgroup = [], [], [], [], []
    group = None
    groups = []
    with open(path) as f:
        for line in f:
            if line.startswith("v "):
                verts.append([float(x) for x in line.split()[1:4]])
            elif line.startswith("vt "):
                uvs.append([float(x) for x in line.split()[1:3]])
            elif line.startswith("g "):
                group = line.split(None, 1)[1].strip()
                if group not in groups:
                    groups.append(group)
            elif line.startswith("f "):
                vi, ti = [], []
                for tok in line.split()[1:]:
                    p = tok.split("/")
                    vi.append(int(p[0]) - 1)
                    ti.append(int(p[1]) - 1 if len(p) > 1 and p[1] else -1)
                faces.append(vi)
                fuv.append(ti)
                fgroup.append(group)
    return dict(verts=np.array(verts), uvs=np.array(uvs) if uvs else np.zeros((0, 2)),
                faces=faces, fuv=fuv, fgroup=fgroup, groups=groups)


# ---------------------------------------------------------------- targets
class Targets:
    def __init__(self):
        self.npz = np.load(os.path.join(CACHE, "targets.npz"))

    def has(self, name):
        return f"targets/{name}.index" in self.npz

    def get(self, name):
        idx = self.npz[f"targets/{name}.index"].astype(np.int64)
        vec = self.npz[f"targets/{name}.vector"].astype(np.float64) * 1e-3
        return idx, vec


def macro_weights(gender=1.0, age_years=35, muscle=0.5, weight=0.5, height=0.5,
                  proportions=0.5, race=None):
    """Return {target_name: weight} following MakeHuman 1.1 macro logic."""
    race = race or {"caucasian": 1 / 3, "african": 1 / 3, "asian": 1 / 3}
    g = {"male": gender, "female": 1 - gender}
    # age: 1y baby, 10y child, 25y young, 90y old
    if age_years < 25:
        a = (age_years - 1) / ((25 - 1) * 2)
    else:
        a = (age_years - 25) / ((90 - 25) * 2) + 0.5
    if a < 0.5:
        old = 0.0
        baby = max(0.0, 1 - a * 5.333)
        young = max(0.0, (a - 0.1875) * 3.2)
        child = max(0.0, min(1.0, 5.333 * a) - young)
    else:
        child = baby = 0.0
        old = max(0.0, a * 2 - 1)
        young = 1 - old
    ag = {"baby": baby, "child": child, "young": young, "old": old}

    def tri(v, lo, mid, hi):
        if v < 0.5:
            return {lo: 1 - v * 2, mid: v * 2, hi: 0.0}
        return {lo: 0.0, mid: 1 - (v - 0.5) * 2, hi: (v - 0.5) * 2}

    mu = tri(muscle, "minmuscle", "averagemuscle", "maxmuscle")
    we = tri(weight, "minweight", "averageweight", "maxweight")
    he = {"minheight": max(0.0, 1 - height * 2), "maxheight": max(0.0, height * 2 - 1)}
    pr = {"uncommonproportions": max(0.0, 1 - proportions * 2),
          "idealproportions": max(0.0, proportions * 2 - 1)}
    out = {}
    for gn, gv in g.items():
        for an, av in ag.items():
            if gv * av == 0:
                continue
            for rn, rv in race.items():
                out[f"macrodetails/{rn}-{gn}-{an}"] = rv * gv * av
            for mn, mv in mu.items():
                for wn, wv in we.items():
                    base = gv * av * mv * wv
                    if base == 0:
                        continue
                    out[f"macrodetails/universal-{gn}-{an}-{mn}-{wn}"] = base
                    for hn, hv in he.items():
                        if hv:
                            out[f"macrodetails/height/{gn}-{an}-{mn}-{wn}-{hn}"] = base * hv
                    for pn, pv in pr.items():
                        if pv:
                            out[f"macrodetails/proportions/{gn}-{an}-{mn}-{wn}-{pn}"] = base * pv
    return {k: v for k, v in out.items() if v > 1e-6}


def apply_targets(co, targets, weights):
    co = co.copy()
    missing = []
    for name, w in weights.items():
        if not targets.has(name):
            missing.append(name)
            continue
        idx, vec = targets.get(name)
        co[idx] += vec * w
    return co, missing


def detail_modifier(name, value):
    """'head/head-oval' style single targets or 'group/name-decr|incr' pairs."""
    if "|" in name:
        stem, pair = name.rsplit("/", 1)[0], name.rsplit("/", 1)[1]
        base, opts = pair.rsplit("-", 1)
        lo, hi = opts.split("|")
        return {f"{stem}/{base}-{hi if value > 0 else lo}": abs(value)}
    return {name: value}


# ---------------------------------------------------------------- mhclo proxy fitting
def load_mhclo(path):
    refs, scales = [], {}
    obj_file = None
    with open(path) as f:
        lines = f.read().splitlines()
    in_verts = False
    for ln in lines:
        s = ln.strip()
        if not s or s.startswith("#"):
            continue
        tok = s.split()
        if tok[0] in ("x_scale", "y_scale", "z_scale"):
            scales[tok[0][0]] = (int(tok[1]), int(tok[2]), float(tok[3]))
        elif tok[0] == "obj_file":
            obj_file = tok[1]
        elif tok[0] == "verts":
            in_verts = True
            continue
        elif in_verts:
            if len(tok) == 9:
                refs.append([int(tok[0]), int(tok[1]), int(tok[2])] + [float(x) for x in tok[3:]])
            elif len(tok) == 1:
                refs.append([int(tok[0]), int(tok[0]), int(tok[0]), 1, 0, 0, 0, 0, 0])
            else:
                in_verts = False
    return dict(refs=np.array(refs), scales=scales, obj_file=obj_file)


def fit_mhclo(clo, base_co_mh):
    r = clo["refs"]
    v = r[:, :3].astype(np.int64)
    w = r[:, 3:6]
    d = r[:, 6:9].copy()
    sc = np.ones(3)
    for i, ax in enumerate("xyz"):
        if ax in clo["scales"]:
            a, b, ref = clo["scales"][ax]
            sc[i] = abs(base_co_mh[a, i] - base_co_mh[b, i]) / ref
    pos = (base_co_mh[v[:, 0]] * w[:, 0:1] + base_co_mh[v[:, 1]] * w[:, 1:2]
           + base_co_mh[v[:, 2]] * w[:, 2:3]) + d * sc
    return pos


# ---------------------------------------------------------------- skeleton
def load_rig():
    with open(os.path.join(CACHE, "rig.game_engine.json")) as f:
        return json.load(f)


def load_weights():
    with open(os.path.join(CACHE, "weights.game_engine.json")) as f:
        return json.load(f)["weights"]


def load_vgroups():
    with open(os.path.join(CACHE, "basemesh_vertex_groups.json")) as f:
        d = json.load(f)
    out = {}
    for k, ranges in d.items():
        idx = []
        for a, b in ranges:
            idx.extend(range(a, b + 1))
        out[k] = np.array(idx, dtype=np.int64)
    return out


def joint_positions(rig, vgroups, co_bl):
    """Bone head/tail positions (Blender space) from joint cube means."""
    def pt(spec):
        if spec["strategy"] == "CUBE":
            return co_bl[vgroups[spec["cube_name"]]].mean(axis=0)
        if spec["strategy"] == "MEAN":
            return co_bl[np.array(spec["vertex_indices"])].mean(axis=0)
        if spec["strategy"] == "VERTEX":
            return co_bl[spec["vertex_index"]]
        raise ValueError(spec)
    return {n: (pt(b["head"]), pt(b["tail"]), b["roll"], b["parent"]) for n, b in rig.items()}
