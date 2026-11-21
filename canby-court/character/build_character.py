"""Build the Canby Court player character (hi-res .blend for Cycles).

    /home/user/venv/bin/python build_character.py            # -> character_hires.blend
    /home/user/venv/bin/python export_web.py                 # -> ../web/assets/character.glb, sled.glb
    /home/user/venv/bin/python render_checks.py              # -> ../renders/character_*.png

Base: MakeHuman hm08 base mesh, targets, game-engine skeleton + weights and
eyes (all CC0, fetched by fetch_assets.sh). Everything else (shape recipe,
garments, hair, materials, sled, animation) is generated here.
"""
import os
import sys
import time
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import bpy  # noqa: E402  (bpy before bmesh)
import bmesh  # noqa: E402,F401

import char_body  # noqa: E402
import garments as G  # noqa: E402
import materials as MAT  # noqa: E402
import hair as H  # noqa: E402
import anim  # noqa: E402
import clips  # noqa: E402
import sled as SLED  # noqa: E402
import geo  # noqa: E402

TEX = os.path.join(HERE, "textures")
GROUND = 0.026          # shoe sole thickness under the bare foot

SUMMER_ATLAS = {"Summer_Tshirt": (0.5, 0.5, 1.0, 1.0), "Summer_Jeans": (0.0, 0.0, 0.5, 1.0),
                "Summer_Sneaker_l": (0.5, 0.0, 1.0, 0.25), "Summer_Sneaker_r": (0.5, 0.25, 1.0, 0.5)}
WINTER_ATLAS = {"Winter_Jacket": (0.0, 0.0, 0.5, 1.0), "Winter_Pants": (0.5, 0.5, 1.0, 1.0),
                "Winter_Boot_l": (0.5, 0.0, 0.75, 0.25), "Winter_Boot_r": (0.5, 0.25, 0.75, 0.5),
                "Winter_Gloves": (0.75, 0.25, 1.0, 0.5),
                "Winter_Beanie": (0.75, 0.0, 1.0, 0.25)}


def log(*a):
    print("[build]", *a, flush=True)


def coll(name, parent=None):
    c = bpy.data.collections.get(name) or bpy.data.collections.new(name)
    if c.name not in (parent or bpy.context.scene.collection).children:
        (parent or bpy.context.scene.collection).children.link(c)
    return c


def landmarks(d, eyes):
    co = d["co"]
    vg = d["vg"]
    ev = np.array([v.co[:] for v in eyes.data.vertices])
    eye_l = ev[ev[:, 0] > 0].mean(0)
    eye_r = ev[ev[:, 0] < 0].mean(0)
    mouth = co[vg["joint-mouth"]].mean(0)
    bco = np.array([v.co[:] for v in d["body"].data.vertices])
    sel = (np.abs(bco[:, 0]) < 0.004) & (bco[:, 2] > eye_l[2] - 0.07) & (bco[:, 2] < eye_l[2] - 0.01)
    nose = bco[sel][np.argmin(bco[sel][:, 1])]
    arm = d["arm"].data.bones
    head = np.array(arm["head"].head_local)
    hand_pts = [np.array(arm[f"{f}_{k}{s}"].head_local) for f in ("index", "middle", "ring", "pinky")
                for k in ("01", "02") for s in ("_l", "_r")]
    return dict(eye_l=eye_l, eye_r=eye_r, mouth=mouth, nose=nose, head=head, hand_pts=hand_pts)


def rigid_to_head(ob, arm):
    g = ob.vertex_groups.new(name="head")
    g.add(list(range(len(ob.data.vertices))), 1.0, "REPLACE")
    ob.parent = arm
    m = ob.modifiers.new("Armature", "ARMATURE")
    m.object = arm


def skin_garment(ob, body, arm):
    G.transfer_weights(body, ob)
    ob.parent = arm
    m = ob.modifiers.new("Armature", "ARMATURE")
    m.object = arm


def limit_arm_weights(ob, armness):
    """Torso panels of loose tops must not follow the upper arm (stops 'wings' when the arm is raised)."""
    up = [g for g in ob.vertex_groups if g.name.startswith(("upperarm", "clavicle"))]
    ids = {g.index for g in up}
    for v in ob.data.vertices:
        a = float(armness[v.index])
        if a > 0.6:
            continue
        keep = 0.25 + 0.75 * a / 0.6
        ws = {g.group: g.weight for g in v.groups}
        tot = sum(ws.values()) or 1.0
        new = {k: (w * keep if k in ids else w) for k, w in ws.items()}
        s = sum(new.values()) or 1.0
        for k, w in new.items():
            ob.vertex_groups[k].add([v.index], w * tot / s, "REPLACE")


def body_visibility_groups(body, bd):
    """Vertex groups: vis_head (head/neck/collar band), vis_arms (forearms/hands + lower upper-arm)."""
    co = bd.co
    headw = bd.w("head", "neck")
    armw = bd.w(*G.BONES_ARM)
    handw = bd.w(*G.BONES_HAND)
    neck = bd.bones["neck_01"][0]
    rho = np.hypot(co[:, 0], co[:, 1] - neck[1])
    head_part = (headw > 0.25) | ((co[:, 2] > neck[2] - 0.11) & (rho < 0.13) & (armw + handw < 0.2))
    tparam = np.zeros(bd.nv)
    for s, sfx in ((1, "_l"), (-1, "_r")):
        h, t = bd.bones["upperarm" + sfx]
        tt, _, _ = G.seg_param(co, h, t)
        m = np.sign(co[:, 0]) == s
        tparam[m] = tt[m]
    arm_part = ((armw + handw) > 0.45) & (tparam > 0.22)
    for name, mask in (("vis_head", head_part), ("vis_arms", arm_part)):
        g = body.vertex_groups.new(name=name)
        g.add([int(i) for i in np.where(mask)[0]], 1.0, "REPLACE")
    vs = body.vertex_groups.new(name="vis_summer")
    vs.add([int(i) for i in np.where(head_part | arm_part)[0]], 1.0, "REPLACE")
    vw = body.vertex_groups.new(name="vis_winter")
    vw.add([int(i) for i in np.where(head_part)[0]], 1.0, "REPLACE")


def main():
    t0 = time.time()
    os.makedirs(TEX, exist_ok=True)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc = bpy.context.scene
    sc.render.fps = anim.FPS
    C_char = coll("Character")
    C_sum = coll("Outfit_Summer")
    C_win = coll("Outfit_Winter")
    C_hair = coll("Hair_Hires")
    C_sled = coll("Sled")

    # ---------------- body, eyes, rig
    d = char_body.build(C_char, ground_offset=GROUND)
    body, arm = d["body"], d["arm"]
    bpy.data.objects.remove(d["eyes"]["low-poly"])
    eyes = d["eyes"]["high-poly"]
    eyes.name = "Eyes"
    lm = landmarks(d, eyes)
    bd = G.BodyData(body, arm)
    log("body", len(body.data.vertices), "verts; height", bd.co[:, 2].max().round(3))

    MAT.skin_masks(body, lm)
    body.data.materials.append(MAT.skin_material())
    eyes.data.materials.append(MAT.eye_material(os.path.join(char_body.mh.CACHE, "eyes", "brown_eye.png")))
    body_visibility_groups(body, bd)

    # ---------------- garments
    sm = {}
    sm["Summer_Tshirt"] = G.tshirt(bd, C_sum, SUMMER_ATLAS["Summer_Tshirt"])
    sm["Summer_Jeans"] = G.jeans(bd, C_sum, SUMMER_ATLAS["Summer_Jeans"])
    for s in ("_l", "_r"):
        sm["Summer_Sneaker" + s] = G.shoe(bd, C_sum, s, SUMMER_ATLAS["Summer_Sneaker" + s], "sneaker")
    wm = {}
    wm["Winter_Jacket"] = G.puffer(bd, C_win, WINTER_ATLAS["Winter_Jacket"])
    wm["Winter_Pants"] = G.jeans(bd, C_win, WINTER_ATLAS["Winter_Pants"], baggy=True, name="Winter_Pants")
    wm["Winter_Gloves"] = G.gloves(bd, C_win, WINTER_ATLAS["Winter_Gloves"])
    wm["Winter_Beanie"] = G.beanie(bd, C_win, WINTER_ATLAS["Winter_Beanie"])
    for s in ("_l", "_r"):
        wm["Winter_Boot" + s] = G.shoe(bd, C_win, s, WINTER_ATLAS["Winter_Boot" + s], "boot")
    hc = H.HeadFrame(bd, eyes, lm)
    MAT.garment_fields(sm["Summer_Tshirt"], "tshirt")
    MAT.garment_fields(sm["Summer_Jeans"], "jeans")
    MAT.garment_fields(wm["Winter_Pants"], "pants")
    MAT.garment_fields(wm["Winter_Gloves"], "gloves")
    MAT.garment_fields(wm["Winter_Beanie"], "beanie", extra={"head": hc.C})
    MAT.garment_fields(wm["Winter_Jacket"], "puffer", extra={"quilt": G.EXTRA["Winter_Jacket"]["quilt"]})
    mats = {"Summer_Tshirt": MAT.tshirt_material(), "Summer_Jeans": MAT.denim_material(),
            "Summer_Sneaker": MAT.shoe_material("sneaker"), "Winter_Jacket": MAT.puffer_material(),
            "Winter_Pants": MAT.snowpants_material(), "Winter_Gloves": MAT.glove_material(),
            "Winter_Beanie": MAT.beanie_material(), "Winter_Boot": MAT.shoe_material("boot")}
    for name, ob in list(sm.items()) + list(wm.items()):
        key = name.rstrip("_lr") if name.endswith(("_l", "_r")) else name
        key = name[:-2] if name.endswith(("_l", "_r")) else name
        ob.data.materials.append(mats[key])
        if "Sneaker" in name or "Boot" in name:
            # shoes are rigid on the foot
            sfx = name[-2:]
            g = ob.vertex_groups.new(name="foot" + sfx)
            co = np.array([v.co[:] for v in ob.data.vertices])
            ball_y = np.array(arm.data.bones["ball" + sfx].head_local)[1]
            wb = np.clip((ball_y + 0.01 - co[:, 1]) / 0.04, 0, 1)   # toe box bends with the ball joint
            gb = ob.vertex_groups.new(name="ball" + sfx)
            for i, w in enumerate(wb):
                g.add([i], 1 - w, "REPLACE")
                gb.add([i], w, "REPLACE")
            if "Boot" in name:
                gc = ob.vertex_groups.new(name="calf" + sfx)
                wc = np.clip((co[:, 2] - 0.10) / 0.10, 0, 1) * (1 - wb)
                for i, w in enumerate(wc):
                    gc.add([i], w, "REPLACE")
                    g.add([i], (1 - w) * (1 - wb[i]), "REPLACE")
            ob.parent = arm
            m = ob.modifiers.new("Armature", "ARMATURE")
            m.object = arm
        else:
            skin_garment(ob, body, arm)
            if name in ("Summer_Tshirt", "Winter_Jacket"):
                limit_arm_weights(ob, G.EXTRA[name]["arm"])
    log("garments", {k: len(v.data.polygons) for k, v in list(sm.items()) + list(wm.items())})

    # ---------------- hair, brows, lashes
    strands = H.gen_strands(bd, hc, n=70000)
    cap = H.cap_mesh(bd, hc, C_char, strands)
    scalp = H.cap_mesh(bd, hc, C_hair, strands, scale=0.12, name="Hair_Scalp_Hires")
    hs = H.curves_object("Hair_Strands", strands, C_hair)
    bs = H.brow_strands(bd, hc)
    bso = H.curves_object("Brow_Strands", bs, C_hair, r_root=0.00004, r_tip=0.00002)
    brows = H.brow_cards(bd, hc, C_char)
    lashes = H.lash_mesh(d, C_char)
    capt = H.rasterize_cap(strands, hc)
    browt = H.rasterize_brows(bs, hc)
    lu = H.rasterize_lashes(upper=True)
    ll = H.rasterize_lashes(upper=False)
    rgba, nimg = H.build_atlas(capt, browt, lu, ll)
    rgba.save(os.path.join(TEX, "hair_atlas.png"))
    nimg.save(os.path.join(TEX, "hair_atlas_normal.png"))
    hair_mat = H.card_material("Hair", os.path.join(TEX, "hair_atlas.png"), os.path.join(TEX, "hair_atlas_normal.png"))
    for ob in (cap, brows, lashes, scalp):
        ob.data.materials.append(hair_mat)
        rigid_to_head(ob, arm)
    hmat = H.hair_bsdf_material("HairStrands")
    bmat = H.hair_bsdf_material("BrowStrands", melanin=0.8, redness=0.3)
    hs.data.materials.append(hmat)
    bso.data.materials.append(bmat)
    for ob in (hs, bso):
        ob.parent = arm
        ob.parent_type = "BONE"
        ob.parent_bone = "head"
        # keep world placement: bone parenting is relative to the bone tail
        hb = arm.data.bones["head"]
        ob.matrix_parent_inverse = (arm.matrix_world @ hb.matrix_local @
                                    __import__("mathutils").Matrix.Translation((0, hb.length, 0))).inverted()
    rigid_to_head(eyes, arm)
    # winter: cap hair hidden under the beanie except the back/sides fringe -> separate mesh
    capw = cap.copy()
    capw.data = cap.data.copy()
    capw.name = "Hair_Cap_Winter"
    C_win.objects.link(capw)
    bm = bmesh.new()
    bm.from_mesh(capw.data)
    hd = lm["head"]
    kill = []
    for v in bm.verts:
        rel = np.array(v.co) - hd
        zc = 0.080 + (rel[1] - -0.10) * (0.020 - 0.080) / (0.08 - -0.10)
        if rel[2] > zc - 0.012:
            kill.append(v)
    bmesh.ops.delete(bm, geom=kill, context="VERTS")
    bm.to_mesh(capw.data)
    bm.free()
    for c in list(cap.users_collection):
        c.objects.unlink(cap)
    C_sum.objects.link(cap)
    cap.name = "Hair_Cap_Summer"
    skin_body = body.modifiers.new("Armature", "ARMATURE")
    skin_body.object = arm
    body.parent = arm

    # ---------------- animation
    rig = anim.Rig(arm)
    ctx = clips.Ctx(rig)
    info = {}
    for name, f in clips.CLIPS.items():
        fn, frames, meta = f(ctx)
        rig.bake(name, fn, frames)
        info[name] = dict(frames=frames, seconds=round(frames / anim.FPS, 3), **meta)
    arm["clip_info"] = str(info)
    log("clips", info)

    # ---------------- sled
    sled_ob, seat, ropes = SLED.build(C_sled)
    sled_ob.location = (2.0, 0, 0)

    # outfits: summer visible by default in the .blend
    C_win.hide_render = True
    C_win.hide_viewport = True
    mk = body.modifiers.new("OutfitMask", "MASK")
    mk.vertex_group = "vis_summer"
    mk.show_viewport = mk.show_render = True
    body.modifiers.move(len(body.modifiers) - 1, 0)
    sub = body.modifiers.new("Subdivision", "SUBSURF")
    sub.levels = 1
    sub.render_levels = 2
    for ob in list(sm.values()) + list(wm.values()) + [eyes]:
        s = ob.modifiers.new("Subdivision", "SUBSURF")
        s.levels = 0 if ob is not eyes else 0
        s.render_levels = 1
    arm.show_in_front = True
    arm.data.pose_position = "POSE"
    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(HERE, "character_hires.blend"), compress=True)
    log("saved character_hires.blend in %.1fs" % (time.time() - t0))


if __name__ == "__main__":
    main()
