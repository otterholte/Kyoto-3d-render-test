"""Procedural garments built from the MakeHuman body surface.

Every garment is a shell derived from a region of the body mesh (so it inherits
clean quad topology and UVs), smoothed (Taubin) to remove anatomical detail,
pushed out with an 'ease' offset, then reshaped with simple drape envelopes
(fabric hanging straight from the chest / straight leg tubes), procedural folds
and quilting. Hems get an inward turned band so edges read as cloth thickness.
Shoes and boots are lofted parametric shells fitted to the foot.
"""
import math
import numpy as np
import bpy

import geo

BONES_ARM = ("upperarm", "lowerarm")
EXTRA = {}
BONES_HAND = ("hand", "thumb", "index", "middle", "ring", "pinky")


class BodyData:
    def __init__(self, body, arm):
        self.ob = body
        co, faces, uv = geo.mesh_arrays(body)
        self.co, self.faces, self.uv = co, faces, uv
        self.loop_start = np.cumsum([0] + [len(f) for f in faces])
        self.nv = len(co)
        self.names = [g.name for g in body.vertex_groups]
        W = np.zeros((self.nv, len(self.names)))
        for v in body.data.vertices:
            for g in v.groups:
                W[v.index, g.group] = g.weight
        self.W = W
        self.A = geo.adjacency(self.nv, faces)
        self.nrm = geo.vertex_normals_fast(co, faces)
        self.bones = {b.name: (np.array(b.head_local), np.array(b.tail_local)) for b in arm.data.bones}

    def w(self, *prefixes):
        idx = [i for i, n in enumerate(self.names) if n.startswith(prefixes)]
        return self.W[:, idx].sum(axis=1) if idx else np.zeros(self.nv)

    def side(self):
        return np.sign(self.co[:, 0])


def seg_param(p, a, b):
    ab = b - a
    t = ((p - a) @ ab) / (ab @ ab)
    foot = a + t[:, None] * ab
    rv = p - foot
    r = np.linalg.norm(rv, axis=1)
    return t, r, rv / np.maximum(r, 1e-9)[:, None]


def smoothstep(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0), 0, 1)
    return t * t * (3 - 2 * t)


# ------------------------------------------------------------------ shell from body region
class Shell:
    def __init__(self, bd, vmask, name):
        """vmask: bool per body vertex; faces kept when all their verts are in mask."""
        keep = [i for i, f in enumerate(bd.faces) if vmask[f].all()]
        used = sorted(set(v for i in keep for v in bd.faces[i]))
        remap = -np.ones(bd.nv, dtype=np.int64)
        remap[used] = np.arange(len(used))
        self.src = np.array(used)
        self.faces = [list(remap[bd.faces[i]]) for i in keep]
        self.uv = np.concatenate([bd.uv[bd.loop_start[i]:bd.loop_start[i + 1]] for i in keep])
        self.co = bd.co[used].copy()
        self.base = self.co.copy()
        self.nv = len(used)
        self.A = geo.adjacency(self.nv, self.faces)
        self.name = name
        self.bd = bd
        self.fields = {}

    def normals(self):
        return geo.vertex_normals_fast(self.co, self.faces)

    def smooth(self, iters, weights=None, fixed=None):
        self.co = geo.taubin(self.co, self.A, iters=iters, weights=weights, fixed=fixed)

    def offset(self, d):
        n = self.normals()
        self.co = self.co + n * np.asarray(d).reshape(-1, 1)

    def field(self, f):
        return f[self.src]

    def hem(self, depth=0.010, lift=0.0, select=None):
        """Turn every open boundary inward (towards the body) as a band of quads."""
        loops = geo.boundary_loops(self.faces)
        n = self.normals()
        co = list(self.co)
        uv_extra = []
        faces = list(self.faces)
        uv = list(self.uv)
        vuv = np.zeros((self.nv, 2))
        # per-vertex uv (any loop)
        k = 0
        for f in self.faces:
            for v in f:
                vuv[v] = self.uv[k]
                k += 1
        nv0 = len(co)
        new_src = list(self.src)
        fl = {k: list(v) for k, v in self.fields.items()}
        for loop in loops:
            if select is not None and not select(np.array([self.co[i] for i in loop])):
                continue
            new_idx = []
            for v in loop:
                p = self.co[v] - n[v] * depth + np.array([0, 0, lift])
                co.append(p)
                new_src.append(self.src[v])
                for k in fl:
                    fl[k].append(fl[k][v])
                new_idx.append(len(co) - 1)
            L = len(loop)
            for i in range(L):
                a, b = loop[i], loop[(i + 1) % L]
                na, nb = new_idx[i], new_idx[(i + 1) % L]
                faces.append([a, b, nb, na])
                uv.extend([vuv[a], vuv[b], vuv[b] + 1e-4, vuv[a] + 1e-4])
        self.co = np.array(co)
        self.faces = faces
        self.uv = np.array(uv)
        self.src = np.array(new_src)
        self.fields = {k: np.array(v) for k, v in fl.items()}
        self.nv = len(self.co)
        self.A = geo.adjacency(self.nv, self.faces)

    def clean_hems(self, ring_smooth=8, falloff=4, select=None):
        """Project each open boundary loop onto its best-fit plane and smooth it,
        then relax the neighbouring rows so the cut reads as a straight hem."""
        loops = geo.boundary_loops(self.faces)
        fixed = np.zeros(self.nv, bool)
        for loop in loops:
            P = self.co[loop]
            if select is not None and not select(P):
                continue
            c = P.mean(axis=0)
            u, s, vt = np.linalg.svd(P - c)
            nrm = vt[2]
            P = P - ((P - c) @ nrm)[:, None] * nrm[None, :]
            for _ in range(ring_smooth):
                P = 0.5 * P + 0.25 * (np.roll(P, 1, 0) + np.roll(P, -1, 0))
            self.co[loop] = P
            fixed[loop] = True
        # relax rows next to the hem
        dist = np.where(fixed, 0, 99)
        L = geo.laplacian_avg(self.A)
        A = self.A.tocsr()
        for k in range(1, falloff + 1):
            nb = (A @ (dist == k - 1).astype(float)) > 0
            dist = np.where(nb & (dist > k), k, dist)
        w = np.clip(1 - dist / (falloff + 1), 0, 1) * (dist > 0)
        self.co = geo.taubin(self.co, self.A, iters=6, weights=w, fixed=np.where(fixed)[0])

    def to_object(self, collection, atlas_rect=None):
        EXTRA[self.name] = self.fields
        uv = self.uv.copy()
        ob = geo.make_object(self.name, self.co, self.faces, collection, uv_loops=uv, uv_name="UVBody")
        if atlas_rect is not None:
            x0, y0, x1, y1 = atlas_rect
            mn, mx = uv.min(axis=0), uv.max(axis=0)
            s = min((x1 - x0) / (mx[0] - mn[0]), (y1 - y0) / (mx[1] - mn[1])) * 0.98
            off = np.array([x0 + (x1 - x0 - (mx[0] - mn[0]) * s) / 2, y0 + (y1 - y0 - (mx[1] - mn[1]) * s) / 2])
            auv = (uv - mn) * s + off
            l = ob.data.uv_layers.new(name="UVMap")
            l.data.foreach_set("uv", auv.astype(np.float32).ravel())
            ob.data.uv_layers.active = l
            l.active_render = True
        return ob


# ------------------------------------------------------------------ drape helpers
def chest_table(bd, zlo, zhi, mask, nb=96):
    sel = mask & (bd.co[:, 2] > zlo) & (bd.co[:, 2] < zhi)
    p = bd.co[sel]
    cy = p[:, 1].mean()
    th = np.arctan2(p[:, 1] - cy, p[:, 0])
    r = np.hypot(p[:, 0], p[:, 1] - cy)
    bins = ((th + np.pi) / (2 * np.pi) * nb).astype(int) % nb
    tab = np.zeros(nb)
    np.maximum.at(tab, bins, r)
    # fill empty bins / smooth circularly
    for _ in range(3):
        tab = np.maximum(tab, 0.5 * (np.roll(tab, 1) + np.roll(tab, -1)) * (tab == 0))
    tab = np.max([np.roll(tab, k) for k in range(-4, 5)], axis=0)
    for _ in range(3):
        tab = 0.25 * np.roll(tab, 1) + 0.5 * tab + 0.25 * np.roll(tab, -1)
    return tab, cy


def drape_torso(co, tab, cy, z_top, z_bottom, ease, shrink=0.02, active=None):
    """Push torso points out to the chest silhouette below z_top (fabric hangs)."""
    nb = len(tab)
    th = np.arctan2(co[:, 1] - cy, co[:, 0])
    r = np.hypot(co[:, 0], co[:, 1] - cy)
    f = (th + np.pi) / (2 * np.pi) * nb
    i0 = np.floor(f).astype(int) % nb
    fr = f - np.floor(f)
    rt = tab[i0] * (1 - fr) + tab[(i0 + 1) % nb] * fr
    h = np.clip((z_top - co[:, 2]) / max(z_top - z_bottom, 1e-6), 0, 1)
    target = (rt + ease) * (1 - shrink * h)
    a = smoothstep(z_top + 0.02, z_top - 0.06, co[:, 2])
    if active is not None:
        a = a * active
    newr = np.where(target > r, r + (target - r) * a, r)
    s = newr / np.maximum(r, 1e-9)
    out = co.copy()
    out[:, 0] = co[:, 0] * s
    out[:, 1] = cy + (co[:, 1] - cy) * s
    return out


def tube(co, a, b, active, r_fn, keep_out=True):
    """Make points around axis a->b at least r_fn(t) from the axis."""
    t, r, d = seg_param(co, a, b)
    rt = r_fn(t)
    newr = np.where(rt > r, r + (rt - r) * active, r) if keep_out else r + (rt - r) * active
    ab = b - a
    foot = a + t[:, None] * ab
    return foot + d * newr[:, None], t, d


# ------------------------------------------------------------------ garments
def tshirt(bd, collection, rect):
    co = bd.co
    armw = bd.w(*BONES_ARM)
    handw = bd.w(*BONES_HAND)
    headw = bd.w("head", "neck")
    legw = bd.w("thigh", "calf", "foot", "ball")
    pel = bd.bones["pelvis"][0]
    neck = bd.bones["neck_01"][0]
    hem_z = pel[2] - 0.045
    # crew neckline: low in front, higher at back
    rel = co - neck
    rho = np.hypot(rel[:, 0], rel[:, 1] + 0.012)
    front = np.clip(-(rel[:, 1] + 0.01) / 0.07, 0, 1)
    neck_ok = (rel[:, 2] < -0.004 - 0.05 * front) | (rho > 0.105)
    sleeve = np.zeros(bd.nv, bool)
    tparam = np.zeros(bd.nv)
    for s, sfx in ((1, "_l"), (-1, "_r")):
        h, t = bd.bones["upperarm" + sfx]
        tt, _, _ = seg_param(co, h, t)
        m = np.sign(co[:, 0]) == s
        tparam[m] = tt[m]
    is_arm = (armw + handw) > 0.45
    sleeve_end = 0.46
    m = (~is_arm & (co[:, 2] > hem_z) & neck_ok & (headw < 0.6) & (legw < 0.97)) | \
        (is_arm & (tparam < sleeve_end) & (handw < 0.1))
    sh = Shell(bd, m, "Summer_Tshirt")
    s_arm = sh.field((armw + handw) > 0.3)
    s_t = sh.field(tparam)
    # remove anatomy
    sh.smooth(60)
    sh.offset(0.005)
    # torso drape from the chest/shoulder-blade silhouette
    torso_mask = (armw + handw < 0.3) & (headw < 0.3)
    sp3 = bd.bones["spine_03"][0]
    tab, cy = chest_table(bd, sp3[2] + 0.09, sp3[2] + 0.19, torso_mask)
    act = (1 - sh.field(np.clip(armw + handw, 0, 1)))
    sh.co = drape_torso(sh.co, tab, cy, z_top=sp3[2] + 0.12, z_bottom=hem_z, ease=0.004, shrink=0.07, active=act)
    # sleeves: loose tube, opening hangs slightly under gravity
    for s, sfx in ((1, "_l"), (-1, "_r")):
        h, t = bd.bones["upperarm" + sfx]
        sel = (np.sign(sh.co[:, 0]) == s) & s_arm
        tt, r, d = seg_param(sh.co, h, t)
        ropen = np.percentile(r[sel & (tt > sleeve_end - 0.12)], 92) + 0.012 if sel.any() else 0.06
        act = sel * smoothstep(0.05, 0.3, tt)
        new, _, d = tube(sh.co, h, t, act, lambda t_: np.full_like(t_, ropen))
        sag = np.clip(-d[:, 2], 0, 1) * 0.008 * act
        sh.co = new - np.array([0, 0, 1.0]) * sag[:, None]
    sh.smooth(4)
    # folds: soft horizontal ripples above the hem + sleeve creases + noise
    n = sh.normals()
    z = sh.co[:, 2]
    rip = np.sin((z - hem_z) * 2 * np.pi / 0.055 + geo.fbm3(sh.co, 6, 2, 3) * 2.5)
    amp = 0.0012 * smoothstep(hem_z + 0.25, hem_z + 0.05, z) * (1 - s_arm)
    disp = rip * amp + geo.fbm3(sh.co, 7, 3, 11) * 0.0030
    sh.co = sh.co + n * disp[:, None]
    sh.clean_hems()
    sh.hem(depth=0.012)
    return sh.to_object(collection, rect)


def jeans(bd, collection, rect, baggy=False, name="Summer_Jeans"):
    co = bd.co
    legw = bd.w("thigh", "calf")
    footw = bd.w("foot", "ball")
    armw = bd.w(*BONES_ARM, *BONES_HAND)
    pel = bd.bones["pelvis"][0]
    # waist: jeans sit a little below the natural waist, lower at the front
    front = np.clip(-(co[:, 1] - 0.0) / 0.09, 0, 1)
    waist_z = pel[2] + (0.085 if not baggy else 0.13) - 0.025 * front
    hem_z = 0.075 if not baggy else 0.11
    m = (co[:, 2] < waist_z) & (co[:, 2] > hem_z) & (footw < 0.5) & (armw < 0.2)
    sh = Shell(bd, m, name)
    sh.smooth(60)
    sh.offset(0.007 if not baggy else 0.014)
    for s, sfx in ((1, "_l"), (-1, "_r")):
        a = bd.bones["thigh" + sfx][0]
        b = bd.bones["foot" + sfx][0].copy()
        b[2] = 0.0
        sel = (np.sign(sh.co[:, 0]) == s)
        tt, r, _ = seg_param(sh.co, a, b)
        # straight leg: from just above the knee the leg opening is a constant tube
        if baggy:
            r_knee, r_hem = 0.088, 0.092
        else:
            r_knee, r_hem = 0.066, 0.068
        def rfn(t_):
            return np.where(t_ < 0.45, 0.0, r_knee + (r_hem - r_knee) * np.clip((t_ - 0.45) / 0.55, 0, 1))
        act = sel * smoothstep(0.30, 0.47, tt)
        sh.co, _, _ = tube(sh.co, a, b, act, rfn)
        # thigh ease
        act2 = sel * smoothstep(0.02, 0.15, tt) * (1 - smoothstep(0.35, 0.5, tt))
        t2, r2, d2 = seg_param(sh.co, a, b)
        sh.co = sh.co + d2 * (act2 * (0.004 if not baggy else 0.012))[:, None]
    sh.smooth(6)
    # stacking folds at the hem, knee and crotch whiskers
    n = sh.normals()
    z = sh.co[:, 2]
    noise = geo.fbm3(sh.co, 7, 3, 21)
    stack = np.sin((z - hem_z) * 2 * np.pi / (0.045 if not baggy else 0.06) + noise * 3.0)
    amp = 0.004 * smoothstep(hem_z + 0.16, hem_z + 0.02, z)
    kz = bd.bones["calf_l"][0][2]
    knee = np.abs(z - kz) < 0.06
    kn = np.sin(z * 2 * np.pi / 0.03 + noise * 4) * 0.0018 * (1 - np.abs(z - kz) / 0.06) * knee
    disp = stack * amp + kn + noise * (0.0025 if not baggy else 0.004)
    sh.co = sh.co + n * disp[:, None]
    # waistband: lift + band
    sh.clean_hems()
    sh.hem(depth=0.010)
    return sh.to_object(collection, rect)


def puffer(bd, collection, rect):
    co = bd.co
    armw = bd.w(*BONES_ARM)
    handw = bd.w(*BONES_HAND)
    headw = bd.w("head")
    neckw = bd.w("neck")
    legw = bd.w("thigh", "calf", "foot", "ball")
    pel = bd.bones["pelvis"][0]
    neck = bd.bones["neck_01"]
    hem_z = pel[2] - 0.07
    rel = co - neck[0]
    collar_ok = rel[:, 2] < 0.065
    lt = np.zeros(bd.nv)
    for s, sfx in ((1, "_l"), (-1, "_r")):
        h, t = bd.bones["lowerarm" + sfx]
        tt, _, _ = seg_param(co, h, t)
        mm = np.sign(co[:, 0]) == s
        lt[mm] = tt[mm]
    is_arm = (armw + handw) > 0.45
    m = (~is_arm & (co[:, 2] > hem_z) & collar_ok & (headw < 0.5) & (legw < 0.97)) | \
        (is_arm & (handw < 0.35) & (lt < 0.98))
    sh = Shell(bd, m, "Winter_Jacket")
    s_arm = sh.field((armw + handw) > 0.3)
    s_neck = sh.field(neckw + headw)
    sh.smooth(60)
    sh.offset(0.016)
    sp3 = bd.bones["spine_03"][0]
    tab, cy = chest_table(bd, sp3[2] + 0.08, sp3[2] + 0.20, (armw + handw < 0.3) & (headw + neckw < 0.3))
    act = 1 - sh.field(np.clip(armw + handw, 0, 1))
    sh.co = drape_torso(sh.co, tab, cy, z_top=sp3[2] + 0.13, z_bottom=hem_z, ease=0.03, shrink=0.02, active=act)
    # stand collar: tube around the neck
    na, nb_ = neck
    act_n = np.clip(s_neck * 2, 0, 1) * smoothstep(neck[0][2] - 0.06, neck[0][2] - 0.01, sh.co[:, 2])
    sh.co, _, _ = tube(sh.co, na - np.array([0, 0, 0.1]), nb_, act_n, lambda t_: np.full_like(t_, 0.072))
    # sleeves: generous tube shoulder->wrist
    for s, sfx in ((1, "_l"), (-1, "_r")):
        ua, ub = bd.bones["upperarm" + sfx]
        la, lb = bd.bones["lowerarm" + sfx]
        sel = (np.sign(sh.co[:, 0]) == s) & s_arm
        act = sel * 1.0
        tt, r, d = seg_param(sh.co, ua, ub)
        upper = sel & (tt < 1.0)
        sh.co, _, _ = tube(sh.co, ua, ub, upper * smoothstep(0.0, 0.25, tt), lambda t_: np.full_like(t_, 0.072))
        tt2, _, _ = seg_param(sh.co, la, lb)
        lower = sel & (tt2 > 0.0)
        sh.co, _, _ = tube(sh.co, la, lb, lower * 1.0, lambda t_: 0.066 - 0.012 * np.clip(t_, 0, 1))
    sh.smooth(6)
    # quilting baffles: torso horizontal, sleeves ring-wise
    n = sh.normals()
    z = sh.co[:, 2]
    q = np.abs(np.sin((z - hem_z) * np.pi / 0.085)) ** 0.55
    qa = np.zeros(sh.nv)
    for s, sfx in ((1, "_l"), (-1, "_r")):
        ua = bd.bones["upperarm" + sfx][0]
        lb = bd.bones["lowerarm" + sfx][1]
        el = bd.bones["lowerarm" + sfx][0]
        # arc length along shoulder->elbow->wrist
        t1, _, _ = seg_param(sh.co, ua, el)
        t2, _, _ = seg_param(sh.co, el, lb)
        L1 = np.linalg.norm(el - ua)
        L2 = np.linalg.norm(lb - el)
        sarc = np.where(t1 < 1, t1 * L1, L1 + t2 * L2)
        sel = (np.sign(sh.co[:, 0]) == s) & s_arm
        qa[sel] = np.abs(np.sin(sarc[sel] * np.pi / 0.075)) ** 0.55
    quilt = np.where(s_arm, qa, q)
    neckzone = smoothstep(neck[0][2] - 0.07, neck[0][2] - 0.03, z)
    disp = 0.010 * quilt * (1 - neckzone) + geo.fbm3(sh.co, 8, 3, 5) * 0.003
    sh.fields["quilt"] = np.clip(quilt + neckzone, 0, 1)
    sh.co = sh.co + n * disp[:, None]
    sh.smooth(1)
    sh.clean_hems()
    sh.hem(depth=0.016)
    return sh.to_object(collection, rect)


def gloves(bd, collection, rect):
    co = bd.co
    handw = bd.w(*BONES_HAND)
    lt = np.zeros(bd.nv)
    for s, sfx in ((1, "_l"), (-1, "_r")):
        h, t = bd.bones["lowerarm" + sfx]
        tt, _, _ = seg_param(co, h, t)
        mm = np.sign(co[:, 0]) == s
        lt[mm] = tt[mm]
    m = (handw > 0.3) | (lt > 0.78)
    sh = Shell(bd, m, "Winter_Gloves")
    sh.smooth(6)
    sh.offset(0.0045)
    s_lt = sh.field(lt)
    s_hand = sh.field(handw)
    # gauntlet cuff
    for s, sfx in ((1, "_l"), (-1, "_r")):
        h, t = bd.bones["lowerarm" + sfx]
        sel = (np.sign(sh.co[:, 0]) == s) & (s_hand < 0.5)
        sh.co, _, _ = tube(sh.co, h, t, sel * smoothstep(0.85, 0.80, s_lt), lambda t_: np.full_like(t_, 0.050))
    sh.smooth(2)
    n = sh.normals()
    sh.co = sh.co + n * (geo.fbm3(sh.co, 30, 2, 8) * 0.0012)[:, None]
    sh.clean_hems()
    sh.hem(depth=0.008)
    return sh.to_object(collection, rect)


def beanie(bd, collection, rect):
    co = bd.co
    headw = bd.w("head")
    hd = bd.bones["head"][0]
    # cut plane: forehead (front, ~2.5cm above brows) down to occiput at the back
    rel = co - hd
    # plane z = a + b*y  (y negative = front)
    zf, zb = 0.080, 0.020      # heights above head joint at front / back
    yf, yb = -0.10, 0.08
    zc = zf + (rel[:, 1] - yf) * (zb - zf) / (yb - yf)
    m = (headw > 0.5) & (rel[:, 2] > zc)
    sh = Shell(bd, m, "Winter_Beanie")
    sh.smooth(25)
    rel_s = sh.co - hd
    zc_s = zf + (rel_s[:, 1] - yf) * (zb - zf) / (yb - yf)
    dist_rim = rel_s[:, 2] - zc_s
    off = 0.016 + 0.006 * smoothstep(0.045, 0.040, dist_rim)   # folded cuff band
    # slouch: a little extra volume at the crown/back
    off += 0.012 * smoothstep(0.10, 0.17, rel_s[:, 2]) * smoothstep(-0.05, 0.05, rel_s[:, 1])
    sh.offset(off)
    sh.smooth(3)
    n = sh.normals()
    sh.co = sh.co + n * (geo.fbm3(sh.co, 14, 2, 31) * 0.0012)[:, None]
    sh.clean_hems()
    sh.hem(depth=0.010)
    return sh.to_object(collection, rect)


# ------------------------------------------------------------------ footwear (lofted)
def foot_frame(bd, sfx):
    fa, fb = bd.bones["foot" + sfx]
    ba, bb = bd.bones["ball" + sfx]
    footw = bd.w("foot" + sfx, "ball" + sfx)
    calfw = bd.w("calf" + sfx)
    sel = (footw > 0.4) & (bd.co[:, 2] < 0.12)
    p = bd.co[sel]
    fwd = np.array([bb[0] - fa[0], bb[1] - fa[1], 0])
    fwd /= np.linalg.norm(fwd)
    up = np.array([0, 0, 1.0])
    side = np.cross(fwd, up)
    org = np.array([fa[0], fa[1], 0])
    loc = np.stack([(p - org) @ side, (p - org) @ fwd, p[:, 2]], axis=1)
    return org, fwd, side, loc


def shoe(bd, collection, sfx, rect, kind="sneaker"):
    org, fwd, side, loc = foot_frame(bd, sfx)
    sign = 1 if sfx == "_l" else -1
    ymin, ymax = loc[:, 1].min(), loc[:, 1].max()
    boot = kind == "boot"
    ease = 0.010 if not boot else 0.016
    y0, y1 = ymin - ease - (0.004 if boot else 0.002), ymax + ease + (0.012 if boot else 0.016)
    nu, nv = 40, 32
    sole_t = 0.028 if not boot else 0.036
    L = y1 - y0
    # width / height profiles from the foot
    us = np.linspace(0, 1, nu)
    wl = np.zeros(nu); wr = np.zeros(nu); top = np.zeros(nu)
    for i, u in enumerate(us):
        yy = y0 + u * L
        s = np.abs(loc[:, 1] - yy) < 0.012
        if s.sum() < 3:
            s = np.argsort(np.abs(loc[:, 1] - yy))[:12]
        wl[i] = loc[s, 0].min()
        wr[i] = loc[s, 0].max()
        top[i] = loc[s, 2].max()
    for arr in (wl, wr, top):
        arr[:] = np.convolve(np.pad(arr, 3, mode="edge"), np.ones(7) / 7, mode="valid")
    wl -= ease; wr += ease
    top += ease * 0.8
    # toe box: flatter and rounder than the bare toes
    toe = smoothstep(0.70, 1.0, us)
    top = top * (1 - toe) + (top * 0.55 + 0.035) * toe
    top = np.maximum(top, 0.045 if not boot else 0.06)
    bottom = sole_t - 0.004
    # collar / shaft
    collar_h = 0.085 if not boot else 0.23
    verts = []
    uvs = []
    for i, u in enumerate(us):
        yy = y0 + u * L
        # end rounding in plan view
        k = 6 if u < 0.5 else 3.2
        endsc = (1 - abs(2 * u - 1) ** k) ** (1 / k) if 0 < u < 1 else 0.0
        endsc = max(endsc, 0.02)
        cx = 0.5 * (wl[i] + wr[i])
        hw = 0.5 * (wr[i] - wl[i]) * endsc
        hz = top[i]
        if u < 0.52:
            # shaft region rises towards the ankle
            hz = max(hz, collar_h * smoothstep(0.52, 0.30, u) + hz * (1 - smoothstep(0.52, 0.30, u)))
        hz = bottom + (hz - bottom) * (endsc ** 0.35)
        for j in range(nv):
            a = 2 * np.pi * j / nv
            c, s = np.cos(a), np.sin(a)
            # superellipse section, flat bottom
            e = 2.6
            sx = np.sign(c) * abs(c) ** (2 / e)
            sz = np.sign(s) * abs(s) ** (2 / e)
            x = cx + hw * sx
            if sz < 0:
                z = bottom + 0.004 * (1 + sz)
            else:
                z = bottom + 0.004 + (hz - bottom - 0.004) * sz
            verts.append((x, yy, z))
            uvs.append((u, j / nv))
    verts = np.array(verts)
    faces = []
    fuv = []
    # opening: remove faces at the top in the collar region
    for i in range(nu - 1):
        for j in range(nv):
            jn = (j + 1) % nv
            a, b, c_, d = i * nv + j, i * nv + jn, (i + 1) * nv + jn, (i + 1) * nv + j
            ang = 2 * np.pi * (j + 0.5) / nv
            u = (us[i] + us[i + 1]) / 2
            open_w = 0.55 if not boot else 0.62
            if u < (0.50 if not boot else 0.46) and u > 0.06 and np.sin(ang) > open_w:
                continue
            faces.append([a, d, c_, b])
            fuv.append([(us[i], j / nv), (us[i + 1], j / nv), (us[i + 1], (j + 1) / nv), (us[i], (j + 1) / nv)])
    # to world
    W = org[None, :] + verts[:, 0:1] * side[None, :] + verts[:, 1:2] * fwd[None, :]
    W[:, 2] = verts[:, 2]
    name = ("Summer_Sneaker" if not boot else "Winter_Boot") + sfx
    # sole: separate loft (outline slightly wider), extruded down to the ground with toe spring
    sole_v, sole_f, sole_uv = [], [], []
    ring = []
    for i, u in enumerate(us):
        yy = y0 + u * L
        k = 6 if u < 0.5 else 3.2
        endsc = (1 - abs(2 * u - 1) ** k) ** (1 / k) if 0 < u < 1 else 0.0
        cx = 0.5 * (wl[i] + wr[i])
        hw = 0.5 * (wr[i] - wl[i]) * max(endsc, 0.02) + (0.004 if not boot else 0.007)
        ring.append((cx, yy, hw))
    # outline polygon: left side heel->toe then right side toe->heel
    outline = [(cx - hw, yy) for cx, yy, hw in ring] + [(cx + hw, yy) for cx, yy, hw in ring[::-1]]
    outline = np.array(outline)
    m = len(outline)
    spring = lambda y: 0.012 * smoothstep(0.75, 1.0, (y - y0) / L) + (0.004 if not boot else 0.0) * smoothstep(0.15, 0.0, (y - y0) / L)
    layers = [0.0, 0.004, sole_t * 0.55, sole_t, sole_t + 0.003]
    insets = [0.004, 0.0, 0.0, 0.001, 0.006]
    cen = outline.mean(axis=0)
    for li, (zz, ins) in enumerate(zip(layers, insets)):
        for k, (x, y) in enumerate(outline):
            dvec = np.array([x, y]) - cen
            dvec = dvec / max(np.linalg.norm(dvec), 1e-9)
            xx, yy_ = np.array([x, y]) - dvec * ins
            sole_v.append((xx, yy_, zz + spring(yy_)))
    for li in range(len(layers) - 1):
        for k in range(m):
            kn = (k + 1) % m
            a, b = li * m + k, li * m + kn
            sole_f.append([a, b, b + m, a + m])
            sole_uv.append([(k / m, li / 5), (kn / m, li / 5), (kn / m, (li + 1) / 5), (k / m, (li + 1) / 5)])
    # bottom cap (fan from centre)
    sole_v.append((cen[0], cen[1], 0.0 + spring(cen[1])))
    c0 = len(sole_v) - 1
    for k in range(m):
        kn = (k + 1) % m
        sole_f.append([c0, kn, k])
        sole_uv.append([(0.5, 0.0), (kn / m, 0.0), (k / m, 0.0)])
    sole_v = np.array(sole_v)
    SW = org[None, :] + sole_v[:, 0:1] * side[None, :] + sole_v[:, 1:2] * fwd[None, :]
    SW[:, 2] = sole_v[:, 2]
    # upper also gets toe spring
    yl = verts[:, 1]
    W[:, 2] += np.array([spring(y) for y in yl])
    # merge
    allv = np.concatenate([W, SW])
    off = len(W)
    allf = faces + [[i + off for i in f] for f in sole_f]
    # UV regions: upper in [0,0.75] of the slot, sole in [0.75,1]
    auv = []
    for f in fuv:
        auv.extend([(uu * 0.75, vv) for uu, vv in f])
    for f in sole_uv:
        auv.extend([(0.75 + vv * 0.25 * 0.999, uu) for uu, vv in f])
    ob = geo.make_object(name, allv, allf, collection, uv_loops=np.array(auv), uv_name="UVBody")
    x0, y0r, x1, y1r = rect
    a = np.array(auv)
    l = ob.data.uv_layers.new(name="UVMap")
    l.data.foreach_set("uv", np.stack([x0 + a[:, 0] * (x1 - x0), y0r + a[:, 1] * (y1r - y0r)], 1).astype(np.float32).ravel())
    ob.data.uv_layers.active = l
    # collar hem: turn open boundary inward
    return ob


def transfer_weights(src_body, dst, max_dist=0.25):
    """Copy deform weights from the body to a garment (nearest face, interpolated)."""
    for g in src_body.vertex_groups:
        if dst.vertex_groups.get(g.name) is None:
            dst.vertex_groups.new(name=g.name)
    m = dst.modifiers.new("dt", "DATA_TRANSFER")
    m.object = src_body
    m.use_vert_data = True
    m.data_types_verts = {"VGROUP_WEIGHTS"}
    m.vert_mapping = "POLYINTERP_NEAREST"
    m.layers_vgroup_select_src = "ALL"
    m.layers_vgroup_select_dst = "NAME"
    with bpy.context.temp_override(object=dst, active_object=dst):
        bpy.ops.object.modifier_apply(modifier=m.name)
    normalize_weights(dst)


def normalize_weights(ob, limit=4):
    me = ob.data
    for v in me.vertices:
        gs = sorted([(g.weight, g.group) for g in v.groups], reverse=True)
        keep = gs[:limit]
        tot = sum(w for w, _ in keep) or 1.0
        for w, gi in gs[limit:]:
            ob.vertex_groups[gi].remove([v.index])
        for w, gi in keep:
            ob.vertex_groups[gi].add([v.index], w / tot, "REPLACE")
