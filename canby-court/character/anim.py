"""Procedural keyframed animation for the MakeHuman game-engine skeleton.

Each clip is a python function  pose_fn(t) -> Pose  evaluated every frame.
A Pose holds
  * pelvis world location / rotation (the hips drive the whole body),
  * relative FK rotations per bone, expressed about *armature rest-space* axes
    (X = character's left, -Y = forward, Z = up) so they are rig-roll agnostic,
  * two-bone IK goals for legs/arms (target, pole) with world foot orientation
    (heel / ball pivoting for foot plant).
The solver turns that into armature-space pose matrices, converts them to
local bases and writes one key per frame per bone into an Action that is
pushed to an NLA track named after the clip (glTF exporter: NLA_TRACKS mode).
"""
import math
import numpy as np
from mathutils import Matrix, Quaternion, Vector

FPS = 30
X = Vector((1, 0, 0))
Y = Vector((0, 1, 0))
Z = Vector((0, 0, 1))


def q(axis, deg):
    return Quaternion(Vector(axis).normalized(), math.radians(deg))


def qmul(*qs):
    r = Quaternion()
    for a in qs:
        r = r @ a
    return r


def ease(x):
    x = min(max(x, 0.0), 1.0)
    return x * x * (3 - 2 * x)


def ease_io(x):
    x = min(max(x, 0.0), 1.0)
    return 0.5 - 0.5 * math.cos(math.pi * x)


def lerp(a, b, t):
    return a + (b - a) * t


def slerp(a, b, t):
    return a.slerp(b, t)


class Pose:
    def __init__(self):
        self.pelvis_loc = None          # world Vector, None = rest
        self.pelvis_rot = Quaternion()  # world rotation relative to rest
        self.rot = {}                   # bone -> Quaternion (rest-space axes, relative to parent)
        self.ik = {}                    # 'leg_l' / 'arm_r' -> dict(target, pole, end_rot)

    def add(self, bone, quat):
        self.rot[bone] = quat @ self.rot.get(bone, Quaternion())


class Rig:
    def __init__(self, arm_ob):
        self.ob = arm_ob
        self.bones = {b.name: b for b in arm_ob.data.bones}
        self.order = []
        def walk(b):
            self.order.append(b.name)
            for c in b.children:
                walk(c)
        for b in arm_ob.data.bones:
            if b.parent is None:
                walk(b)
        self.rest = {n: b.matrix_local.copy() for n, b in self.bones.items()}
        self.rest_rot = {n: m.to_quaternion() for n, m in self.rest.items()}
        self.head = {n: m.translation.copy() for n, m in self.rest.items()}
        self.tail = {n: Vector(b.tail_local) for n, b in self.bones.items()}
        self.len = {n: b.length for n, b in self.bones.items()}
        # finger curl axes (rest space) and sign
        self.curl_axis = {}
        for s in ("_l", "_r"):
            kn = (self.head["index_01" + s] - self.head["pinky_01" + s]).normalized()
            palm_target = self.head["thumb_01" + s]
            for f in ("index", "middle", "ring", "pinky", "thumb"):
                for k in ("01", "02", "03"):
                    n = f"{f}_{k}{s}"
                    d = (self.tail[n] - self.head[n]).normalized()
                    ax = kn if f != "thumb" else (self.tail["index_01" + s] - self.head["thumb_01" + s]).cross(d).normalized()
                    if f != "thumb":
                        ax = (ax - d * ax.dot(d)).normalized()
                    # sign: curl should move the tip towards the palm (towards the thumb base for fingers)
                    tip = self.tail[n] - self.head[n]
                    t1 = q(ax, 30) @ tip
                    ref = (palm_target - self.head[n]) if f != "thumb" else (self.head["pinky_01" + s] - self.head[n])
                    if (t1 + self.head[n] - self.head[n]).angle(ref) > tip.angle(ref):
                        ax = -ax
                    self.curl_axis[n] = ax
        # rest pole directions for limbs
        self.rest_pole = {}
        for s in ("_l", "_r"):
            sgn = 1 if s == "_l" else -1
            self.rest_pole["leg" + s] = Vector((0, -1, 0))
            S, K, T = self.head["upperarm" + s], self.head["lowerarm" + s], self.tail["lowerarm" + s]
            d = (T - S).normalized()
            p = (K - S) - d * (K - S).dot(d)
            self.rest_pole["arm" + s] = p.normalized()

    # ---------------------------------------------------------------- FK helpers
    def local_basis(self, name, quat):
        """Relative rotation about rest-space axes -> pose-bone basis."""
        r = self.rest_rot[name]
        return (r.inverted() @ quat @ r)

    CHAINS = {"leg_l": ("thigh_l", "calf_l", "foot_l"), "leg_r": ("thigh_r", "calf_r", "foot_r"),
              "arm_l": ("upperarm_l", "lowerarm_l", "hand_l"), "arm_r": ("upperarm_r", "lowerarm_r", "hand_r")}

    def solve(self, pose):
        """Armature-space pose matrices for all bones (FK + analytic two-bone IK)."""
        M = {}
        done = set()
        ends = {}
        ups = {v[0]: k for k, v in self.CHAINS.items()}
        for n in self.order:
            b = self.bones[n]
            if n in done:
                continue
            if n == "pelvis":
                loc = pose.pelvis_loc if pose.pelvis_loc is not None else self.head[n]
                M[n] = Matrix.Translation(loc) @ (pose.pelvis_rot @ self.rest_rot[n]).to_matrix().to_4x4()
                continue
            if n in ends:
                pos, end_rot = ends[n]
                if end_rot is not None:
                    M[n] = Matrix.Translation(pos) @ (end_rot @ self.rest_rot[n]).to_matrix().to_4x4()
                    continue
            basis = self.local_basis(n, pose.rot.get(n, Quaternion())).to_matrix().to_4x4()
            if b.parent is None:
                M[n] = self.rest[n] @ basis
            else:
                p = b.parent.name
                M[n] = M[p] @ (self.rest[p].inverted() @ self.rest[n]) @ basis
            if n in ups and ups[n] in pose.ik:
                limb = ups[n]
                up, lo, end = self.CHAINS[limb]
                Tn = self._ik(M, pose, limb, up, lo)
                done.add(lo)
                ends[end] = (Tn, pose.ik[limb].get("end_rot"))
        return M

    def _ik(self, M, pose, limb, up, lo):
        g = pose.ik[limb]
        S = M[up].translation.copy()
        L1, L2 = self.len[up], self.len[lo]
        T = Vector(g["target"])
        d = (T - S)
        dist = min(max(d.length, abs(L1 - L2) + 1e-4), (L1 + L2) * 0.9995)
        dn = d.normalized()
        a = (L1 * L1 - L2 * L2 + dist * dist) / (2 * dist)
        h = math.sqrt(max(L1 * L1 - a * a, 0.0))
        P = Vector(g["pole"])
        pd = (P - S) - dn * (P - S).dot(dn)
        pd = pd.normalized() if pd.length > 1e-6 else Vector((0, -1, 0))
        K = S + dn * a + pd * h
        Tn = S + dn * dist
        p0 = self.rest_pole[limb]

        def align(rest_dir, new_dir, rest_pole, new_pole):
            sw = rest_dir.rotation_difference(new_dir)
            rp = sw @ rest_pole
            rp = rp - new_dir * rp.dot(new_dir)
            npole = new_pole - new_dir * new_pole.dot(new_dir)
            if rp.length < 1e-6 or npole.length < 1e-6:
                return sw
            rp.normalize(); npole.normalize()
            ang = rp.angle(npole)
            if rp.cross(npole).dot(new_dir) < 0:
                ang = -ang
            return Quaternion(new_dir, ang) @ sw
        ru = (self.tail[up] - self.head[up]).normalized()
        rl = (self.tail[lo] - self.head[lo]).normalized()
        tw = g.get("twist", 0.0)
        Ru = align(ru, (K - S).normalized(), p0, pd)
        Rl = align(rl, (Tn - K).normalized(), p0, pd)
        if tw:
            Rl = Quaternion((Tn - K).normalized(), math.radians(tw)) @ Rl
        M[up] = Matrix.Translation(S) @ (Ru @ self.rest_rot[up]).to_matrix().to_4x4()
        M[lo] = Matrix.Translation(K) @ (Rl @ self.rest_rot[lo]).to_matrix().to_4x4()
        return Tn

    def bases(self, pose):
        M = self.solve(pose)
        out = {}
        for n in self.order:
            b = self.bones[n]
            if b.parent is None:
                B = self.rest[n].inverted() @ M[n]
            else:
                p = b.parent.name
                B = (M[p] @ self.rest[p].inverted() @ self.rest[n]).inverted() @ M[n]
            loc, rot, _ = B.decompose()
            out[n] = (loc, rot)
        return out, M

    # ---------------------------------------------------------------- bake
    def bake(self, name, fn, frames, cyclic=False):
        import bpy
        ob = self.ob
        if ob.animation_data is None:
            ob.animation_data_create()
        act = bpy.data.actions.new(name)
        act.use_fake_user = True
        ob.animation_data.action = act
        data = {n: ([], []) for n in self.order}
        prev = {}
        for f in range(frames + 1):
            t = f / FPS
            B, _ = self.bases(fn(t))
            for n, (loc, rot) in B.items():
                # keep quaternion continuity
                if n in prev and prev[n].dot(rot) < 0:
                    rot = -rot
                prev[n] = rot
                data[n][0].append(loc)
                data[n][1].append(rot)
        for n in self.order:
            locs, rots = data[n]
            pb = f'pose.bones["{n}"]'
            moves = n in ("pelvis", "Root") or max((l.length for l in locs), default=0) > 1e-5
            chans = [("rotation_quaternion", 4, lambda i, k: rots[i][k])]
            if moves:
                chans.append(("location", 3, lambda i, k: locs[i][k]))
            for path, nc, get in chans:
                for k in range(nc):
                    fc = act.fcurve_ensure_for_datablock(ob, f"{pb}.{path}", index=k, group_name=n)
                    fc.keyframe_points.add(frames + 1)
                    co = []
                    for i in range(frames + 1):
                        co += [float(i), float(get(i, k))]
                    fc.keyframe_points.foreach_set("co", co)
                    fc.keyframe_points.foreach_set("interpolation", [1] * (frames + 1))  # LINEAR
                    fc.update()
        for pbone in ob.pose.bones:
            pbone.rotation_mode = "QUATERNION"
        tr = ob.animation_data.nla_tracks.new()
        tr.name = name
        st = tr.strips.new(name, 0, act)
        st.name = name
        ob.animation_data.action = None
        return act
