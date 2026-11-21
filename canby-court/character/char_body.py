"""Body, eyes and game-engine armature from MakeHuman hm08 (CC0)."""
import bpy
import bmesh
import numpy as np
from mathutils import Vector, Matrix

import mh_base as mh

# ------------------------------------------------------------------ character recipe
# An original, average adult: mid-30s male, average build, mixed ancestry,
# light-medium complexion. Small, deliberately asymmetric-free detail tweaks so
# the face is not the stock MakeHuman default.
RECIPE = dict(gender=1.0, age_years=34, muscle=0.56, weight=0.54, height=0.52,
              proportions=0.72,
              race={"caucasian": 0.62, "asian": 0.18, "african": 0.20})
DETAILS = {
    "head/head-oval": 0.25,
    "head/head-square": 0.15,
    "nose/nose-scale-depth-decr|incr": 0.10,
    "nose/nose-point-width-decr|incr": 0.15,
    "nose/nose-hump-decr|incr": -0.15,
    "nose/nose-width2-decr|incr": 0.10,
    "chin/chin-width-decr|incr": 0.20,
    "chin/chin-prominent-decr|incr": 0.15,
    "chin/chin-jaw-drop-decr|incr": 0.10,
    "mouth/mouth-upperlip-volume-decr|incr": -0.10,
    "mouth/mouth-scale-horiz-decr|incr": 0.08,
    "eyebrows/eyebrows-trans-down|up": -0.15,
    "eyes/l-eye-scale-decr|incr": -0.08,
    "eyes/r-eye-scale-decr|incr": -0.08,
    "eyes/l-eye-bag-decr|incr": 0.15,
    "eyes/r-eye-bag-decr|incr": 0.15,
    "forehead/forehead-trans-backward|forward": 0.12,
    "l-cheek-bones-decr|incr": 0.0,
    "neck/neck-scale-horiz-decr|incr": 0.15,
    "torso/torso-vshape-decr|incr": 0.10,
    "stomach/stomach-pregnant-decr|incr": 0.12,
    "measure/measure-shoulder-dist-decr|incr": 0.10,
}


def _detail_weights():
    out = {}
    for k, v in DETAILS.items():
        if v == 0 or "/" not in k:
            continue
        out.update(mh.detail_modifier(k, v))
    return out


def shaped_coords():
    obj = mh.load_obj(f"{mh.CACHE}/base.obj")
    tg = mh.Targets()
    w = mh.macro_weights(**RECIPE)
    w.update(_detail_weights())
    co_mh, missing = mh.apply_targets(obj["verts"], tg, w)
    if missing:
        print("missing targets:", missing)
    return obj, co_mh


def _make_mesh(name, co, faces, uv_loops=None):
    me = bpy.data.meshes.new(name)
    me.from_pydata([tuple(c) for c in co], [], faces)
    if uv_loops is not None:
        uvl = me.uv_layers.new(name="UVMap")
        uvl.data.foreach_set("uv", np.asarray(uv_loops, dtype=np.float32).ravel())
    me.update()
    return me


def build(collection, ground_offset=0.0):
    """Create Body, Eyes, Armature. Returns dict of objects and helper data."""
    obj, co_mh = shaped_coords()
    co = mh.mh_to_blender(co_mh)
    vg = mh.load_vgroups()
    body_idx = vg["body"]
    # ground: lowest body vertex on z=0 (+ shoe sole offset)
    zmin = co[body_idx, 2].min()
    co[:, 2] += -zmin + ground_offset
    # centre x/y on the pelvis column
    pel = co[vg["joint-pelvis"]].mean(axis=0)
    co[:, 0] -= pel[0]
    co[:, 1] -= pel[1]

    # ---- body mesh: keep only 'body' faces (+ eyelash helper strips separately)
    body_set = set(body_idx.tolist())
    faces, uvs = [], []
    lash_faces, lash_uvs = [], []
    for f, t, g in zip(obj["faces"], obj["fuv"], obj["fgroup"]):
        if g == "body":
            faces.append(f)
            uvs.extend(obj["uvs"][i] for i in t)
    me = _make_mesh("Body", co, faces, uvs)
    body = bpy.data.objects.new("Body", me)
    collection.objects.link(body)

    # ---- armature
    rig = mh.load_rig()
    joints = mh.joint_positions(rig, vg, co)
    arm_data = bpy.data.armatures.new("Armature")
    arm = bpy.data.objects.new("Armature", arm_data)
    collection.objects.link(arm)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode="EDIT")
    ebs = {}
    for n, (h, t, roll, parent) in joints.items():
        eb = arm_data.edit_bones.new(n)
        eb.head = Vector(h)
        eb.tail = Vector(t)
        eb.roll = roll
        ebs[n] = eb
    for n, (h, t, roll, parent) in joints.items():
        if parent:
            ebs[n].parent = ebs[parent]
            ebs[n].use_connect = rig[n].get("use_connect", False)
    # Root: flat on the ground pointing up, at origin
    r = ebs["Root"]
    r.head = Vector((0, 0, 0))
    r.tail = Vector((0, 0, 0.25))
    r.roll = 0
    bpy.ops.object.mode_set(mode="OBJECT")

    # ---- weights (indices into the full base mesh)
    weights = mh.load_weights()
    old2new = -np.ones(len(co), dtype=np.int64)
    used = sorted(set(i for f in faces for i in f))
    # from_pydata kept all verts; remove loose ones later -> weights by original index now
    for bone, lst in weights.items():
        if not lst:
            continue
        g = body.vertex_groups.new(name=bone)
        by_w = {}
        for vi, wv in lst:
            if vi in body_set:
                by_w.setdefault(round(wv, 4), []).append(vi)
        for wv, vis in by_w.items():
            g.add(vis, wv, "REPLACE")
    # drop loose (non-body) verts
    bm = bmesh.new()
    bm.from_mesh(me)
    loose = [v for v in bm.verts if not v.link_faces]
    bmesh.ops.delete(bm, geom=loose, context="VERTS")
    bm.to_mesh(me)
    bm.free()
    for p in me.polygons:
        p.use_smooth = True

    # ---- eyes (high-poly MakeHuman eyes fitted with mhclo)
    eyes = {}
    for lod in ("high-poly", "low-poly"):
        clo = mh.load_mhclo(f"{mh.CACHE}/eyes/{lod}.mhclo")
        eo = mh.load_obj(f"{mh.CACHE}/eyes/{lod}.obj")
        # shaping offsets: apply same ground/centre shift
        pos = mh.mh_to_blender(mh.fit_mhclo(clo, co_mh))
        pos[:, 2] += -zmin + ground_offset
        pos[:, 0] -= pel[0]
        pos[:, 1] -= pel[1]
        euv = [eo["uvs"][i] for t in eo["fuv"] for i in t]
        eme = _make_mesh(f"Eyes_{lod}", pos, eo["faces"], euv)
        for p in eme.polygons:
            p.use_smooth = True
        e = bpy.data.objects.new(f"Eyes_{lod}", eme)
        collection.objects.link(e)
        eyes[lod] = e

    # lash helper strips (geometry along the lid margins) for the eyelash cards
    lash_groups = [g for g in obj["groups"] if "eyelashes" in g]
    lf, lu = [], []
    for f, t, g in zip(obj["faces"], obj["fuv"], obj["fgroup"]):
        if g in lash_groups:
            lf.append((f, g))
    return dict(body=body, arm=arm, eyes=eyes, co=co, co_mh=co_mh, vg=vg, obj=obj,
                joints=joints, lash_faces=lf, zmin=zmin, pel=pel)


def skin_to_armature(obj, arm):
    obj.parent = arm
    m = obj.modifiers.new("Armature", "ARMATURE")
    m.object = arm
    return m
