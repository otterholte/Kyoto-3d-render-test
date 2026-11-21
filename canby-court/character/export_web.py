"""Web build: low-poly copies + baked 1024 textures + glTF export + meshopt compression.

    /home/user/venv/bin/python export_web.py
Outputs ../web/assets/character.glb and ../web/assets/sled.glb
"""
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import bpy  # noqa: E402
import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

ASSETS = os.path.abspath(os.path.join(HERE, "..", "web", "assets"))
BAKE = os.path.join(HERE, "textures", "web")
NODE_DIR = os.environ.get("CHAR_NODE_DIR", os.path.join(HERE, "tools"))
RES = 1024

# decimation targets (triangles) per web mesh
TARGETS = {
    "Body_Head": 6200, "Body_Arms": 3600,
    "Summer_Tshirt": 3000, "Summer_Jeans": 2600, "Summer_Sneaker_l": 1500, "Summer_Sneaker_r": 1500,
    "Winter_Jacket": 4600, "Winter_Pants": 2600, "Winter_Gloves": 3600, "Winter_Beanie": 1400,
    "Winter_Boot_l": 1600, "Winter_Boot_r": 1600,
    "Eyes": 2100, "Lashes": 400, "Brows": 200, "Hair_Cap_Summer": 2600,
}
SUMMER = ["Body_Head", "Body_Arms", "Eyes", "Lashes", "Brows", "Hair_Cap_Summer",
          "Summer_Tshirt", "Summer_Jeans", "Summer_Sneaker_l", "Summer_Sneaker_r"]
WINTER = ["Body_Head", "Eyes", "Lashes", "Brows", "Winter_Jacket", "Winter_Pants",
          "Winter_Gloves", "Winter_Beanie", "Winter_Boot_l", "Winter_Boot_r"]


def log(*a):
    print("[web]", *a, flush=True)


def tris(ob):
    return sum(len(p.vertices) - 2 for p in ob.data.polygons)


def apply_mod(ob, name):
    with bpy.context.temp_override(object=ob, active_object=ob, selected_objects=[ob]):
        bpy.ops.object.modifier_apply(modifier=name)


def lowpoly_copy(src, name, keep_group=None):
    ob = src.copy()
    ob.data = src.data.copy()
    ob.name = name
    ob.data.name = name
    bpy.context.scene.collection.objects.link(ob)
    for m in list(ob.modifiers):
        if m.type != "ARMATURE":
            ob.modifiers.remove(m)
    if keep_group:
        import bmesh
        gi = ob.vertex_groups[keep_group].index
        bm = bmesh.new()
        bm.from_mesh(ob.data)
        dl = bm.verts.layers.deform.active
        kill = [v for v in bm.verts if gi not in v[dl] or v[dl][gi] < 0.5]
        bmesh.ops.delete(bm, geom=kill, context="VERTS")
        bm.to_mesh(ob.data)
        bm.free()
    base = name[:-4] if name.endswith("_web") else name
    if base.startswith("Hair_Cap"):
        sd = ob.modifiers.new("sub", "SUBSURF")
        sd.levels = 1
        ob.modifiers.move(len(ob.modifiers) - 1, 0)
        apply_mod(ob, "sub")
    t = TARGETS.get(base)
    cur = tris(ob)
    if t and cur > t * 1.05:
        dm = ob.modifiers.new("dec", "DECIMATE")
        dm.decimate_type = "COLLAPSE"
        dm.ratio = t / cur
        dm.use_collapse_triangulate = True
        # decimate must run before the armature
        ob.modifiers.move(len(ob.modifiers) - 1, 0)
        apply_mod(ob, "dec")
    return ob


def new_image(name, alpha=False, color=(0.5, 0.5, 0.5, 1)):
    img = bpy.data.images.get(name)
    if img:
        bpy.data.images.remove(img)
    img = bpy.data.images.new(name, RES, RES, alpha=alpha, float_buffer=False)
    img.generated_color = color
    return img


def target_material(ob, img, noncolor=False):
    m = bpy.data.materials.new("bake_" + ob.name)
    nt = m.node_tree
    nt.nodes.clear()
    t = nt.nodes.new("ShaderNodeTexImage")
    t.image = img
    nt.nodes.active = t
    o = nt.nodes.new("ShaderNodeOutputMaterial")
    ob.data.materials.clear()
    ob.data.materials.append(m)
    return m


def rewire_emit(mats, socket_name):
    """Make each source material emit what feeds `socket_name` of its Principled BSDF."""
    saved = []
    for m in mats:
        nt = m.node_tree
        p = next((n for n in nt.nodes if n.type == "BSDF_PRINCIPLED"), None)
        out = next(n for n in nt.nodes if n.type == "OUTPUT_MATERIAL")
        prev = out.inputs["Surface"].links[0].from_socket if out.inputs["Surface"].links else None
        e = nt.nodes.new("ShaderNodeEmission")
        e.name = "__bake_emit"
        sock = p.inputs[socket_name]
        if sock.links:
            nt.links.new(sock.links[0].from_socket, e.inputs["Color"])
        else:
            v = sock.default_value
            e.inputs["Color"].default_value = (v, v, v, 1) if isinstance(v, float) else tuple(v)
        nt.links.new(e.outputs[0], out.inputs["Surface"])
        saved.append((m, prev, e))
    return saved


def restore(saved):
    for m, prev, e in saved:
        nt = m.node_tree
        out = next(n for n in nt.nodes if n.type == "OUTPUT_MATERIAL")
        if prev is not None:
            nt.links.new(prev, out.inputs["Surface"])
        nt.nodes.remove(e)


def bake_pass(pairs, kind, img_name, noncolor=False, color=(0.5, 0.5, 0.5, 1), samples=1):
    """pairs: [(hires_src, lowpoly_dst)] all baked into one shared image."""
    sc = bpy.context.scene
    img = new_image(img_name, color=color)
    if noncolor:
        img.colorspace_settings.name = "Non-Color"
    sc.cycles.samples = samples
    rb = sc.render.bake
    rb.use_selected_to_active = True
    rb.cage_extrusion = 0.012
    rb.max_ray_distance = 0.03
    rb.margin = 6
    rb.use_clear = False
    rb.target = "IMAGE_TEXTURES"
    srcmats = []
    for s, _ in pairs:
        for m in s.data.materials:
            if m and m not in srcmats:
                srcmats.append(m)
    saved = None
    btype = kind
    if kind in ("ALBEDO", "ROUGH"):
        saved = rewire_emit(srcmats, "Base Color" if kind == "ALBEDO" else "Roughness")
        btype = "EMIT"
    for s, d in pairs:
        target_material(d, img)
        for o in bpy.context.view_layer.objects:
            o.select_set(False)
        s.hide_render = False
        s.select_set(True)
        d.select_set(True)
        bpy.context.view_layer.objects.active = d
        bpy.ops.object.bake(type=btype, normal_space="TANGENT", use_selected_to_active=True,
                            cage_extrusion=0.012, max_ray_distance=0.03, margin=6, use_clear=False)
    if saved:
        restore(saved)
    path = os.path.join(BAKE, img_name + ".png")
    img.filepath_raw = path
    img.file_format = "PNG"
    img.save()
    return path


def web_material(name, albedo, normal, rough, sheen=0.0, ior=1.5, spec=0.5, alpha_from_albedo=False,
                 coat=0.0):
    m = bpy.data.materials.new(name)
    nt = m.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    p = nt.nodes.new("ShaderNodeBsdfPrincipled")
    nt.links.new(p.outputs[0], out.inputs[0])
    uv = nt.nodes.new("ShaderNodeUVMap")
    uv.uv_map = "UVMap"
    ta = nt.nodes.new("ShaderNodeTexImage")
    ta.image = bpy.data.images.load(albedo, check_existing=True)
    nt.links.new(uv.outputs[0], ta.inputs[0])
    nt.links.new(ta.outputs["Color"], p.inputs["Base Color"])
    if alpha_from_albedo:
        nt.links.new(ta.outputs["Alpha"], p.inputs["Alpha"])
    if normal:
        tn = nt.nodes.new("ShaderNodeTexImage")
        tn.image = bpy.data.images.load(normal, check_existing=True)
        tn.image.colorspace_settings.name = "Non-Color"
        nm = nt.nodes.new("ShaderNodeNormalMap")
        nm.uv_map = "UVMap"
        nt.links.new(uv.outputs[0], tn.inputs[0])
        nt.links.new(tn.outputs["Color"], nm.inputs["Color"])
        nt.links.new(nm.outputs[0], p.inputs["Normal"])
    if rough:
        tr = nt.nodes.new("ShaderNodeTexImage")
        tr.image = bpy.data.images.load(rough, check_existing=True)
        tr.image.colorspace_settings.name = "Non-Color"
        sp = nt.nodes.new("ShaderNodeSeparateColor")
        nt.links.new(uv.outputs[0], tr.inputs[0])
        nt.links.new(tr.outputs["Color"], sp.inputs[0])
        nt.links.new(sp.outputs["Green"], p.inputs["Roughness"])
        nt.links.new(sp.outputs["Blue"], p.inputs["Metallic"])
    p.inputs["Sheen Weight"].default_value = sheen
    p.inputs["Sheen Roughness"].default_value = 0.5
    p.inputs["IOR"].default_value = ior
    p.inputs["Specular IOR Level"].default_value = spec
    p.inputs["Coat Weight"].default_value = coat
    p.inputs["Coat Roughness"].default_value = 0.05
    return m


def orm_from_rough(rough_png, out_png, metal=0.0):
    r = np.asarray(Image.open(rough_png).convert("L"))
    o = np.stack([np.full_like(r, 255), r, np.full_like(r, int(metal * 255))], -1)
    Image.fromarray(o).save(out_png)
    return out_png


def main():
    os.makedirs(BAKE, exist_ok=True)
    os.makedirs(ASSETS, exist_ok=True)
    bpy.ops.wm.open_mainfile(filepath=os.path.join(HERE, "character_hires.blend"))
    sc = bpy.context.scene
    sc.render.engine = "CYCLES"
    sc.cycles.device = "CPU"
    arm = bpy.data.objects["Armature"]
    arm.data.pose_position = "REST"
    for c in bpy.data.collections:
        c.hide_render = False
        c.hide_viewport = False
    body = bpy.data.objects["Body"]
    body.modifiers["OutfitMask"].show_render = False
    body.modifiers["OutfitMask"].show_viewport = False

    low = {}
    low["Body_Head"] = lowpoly_copy(body, "Body_Head", keep_group="vis_head")
    low["Body_Arms"] = lowpoly_copy(body, "Body_Arms", keep_group="vis_arms")
    for n in ["Summer_Tshirt", "Summer_Jeans", "Summer_Sneaker_l", "Summer_Sneaker_r", "Winter_Jacket",
              "Winter_Pants", "Winter_Gloves", "Winter_Beanie", "Winter_Boot_l", "Winter_Boot_r"]:
        low[n] = lowpoly_copy(bpy.data.objects[n], n + "_web")
    for n in ["Eyes", "Lashes", "Brows", "Hair_Cap_Summer"]:
        low[n] = lowpoly_copy(bpy.data.objects[n], n + "_web")
    for k, v in low.items():
        log(k, tris(v), "tris")

    # hires sources: subdivision 1 for baking
    for n in ["Body", "Summer_Tshirt", "Summer_Jeans", "Summer_Sneaker_l", "Summer_Sneaker_r", "Winter_Jacket",
              "Winter_Pants", "Winter_Gloves", "Winter_Beanie", "Winter_Boot_l", "Winter_Boot_r"]:
        o = bpy.data.objects[n]
        for m in o.modifiers:
            if m.type == "SUBSURF":
                m.levels = 1
    # hide hair curves etc. from bake rays
    for n in ("Hair_Strands", "Brow_Strands"):
        bpy.data.objects[n].hide_render = True

    def B(o):
        return bpy.data.objects[o]
    groups = {
        "skin": [(B("Body"), low["Body_Head"]), (B("Body"), low["Body_Arms"])],
        "summer": [(B(n), low[n]) for n in ["Summer_Tshirt", "Summer_Jeans", "Summer_Sneaker_l", "Summer_Sneaker_r"]],
        "winter": [(B(n), low[n]) for n in ["Winter_Jacket", "Winter_Pants", "Winter_Gloves", "Winter_Beanie",
                                           "Winter_Boot_l", "Winter_Boot_r"]],
    }
    tex = {}
    for g, pairs in groups.items():
        a = bake_pass(pairs, "ALBEDO", f"{g}_albedo", color=(0.3, 0.3, 0.3, 1))
        r = bake_pass(pairs, "ROUGH", f"{g}_rough", noncolor=True, color=(0.7, 0.7, 0.7, 1))
        n = bake_pass(pairs, "NORMAL", f"{g}_normal", noncolor=True, color=(0.5, 0.5, 1.0, 1), samples=4)
        tex[g] = (a, n, orm_from_rough(r, os.path.join(BAKE, f"{g}_orm.png")))
        log("baked", g)

    for mn in ("Skin", "Hair", "Eyes"):
        if mn in bpy.data.materials:
            bpy.data.materials[mn].name = mn + "_hires"
    mats = {
        "skin": web_material("Skin", *tex["skin"], sheen=0.12, ior=1.4, spec=0.45),
        "summer": web_material("Outfit_Summer", *tex["summer"], sheen=0.35),
        "winter": web_material("Outfit_Winter", *tex["winter"], sheen=0.25),
    }
    hair_rgba = os.path.join(HERE, "textures", "hair_atlas.png")
    hair_n = os.path.join(HERE, "textures", "hair_atlas_normal.png")
    mats["hair"] = web_material("Hair", hair_rgba, hair_n, None, sheen=0.3, alpha_from_albedo=True, spec=0.3)
    mats["hair"].node_tree.nodes["Principled BSDF"].inputs["Roughness"].default_value = 0.5
    eye_png = os.path.join(BAKE, "eyes.png")
    Image.open(os.path.join(HERE, "_mh_cache", "eyes", "brown_eye.png")).resize((512, 512), Image.LANCZOS).save(eye_png)
    mats["eyes"] = web_material("Eyes", eye_png, None, None, alpha_from_albedo=True, coat=1.0, ior=1.376)
    mats["eyes"].node_tree.nodes["Principled BSDF"].inputs["Roughness"].default_value = 0.3
    assign = {"Body_Head": "skin", "Body_Arms": "skin", "Eyes": "eyes", "Lashes": "hair", "Brows": "hair",
              "Hair_Cap_Summer": "hair"}
    for k, ob in low.items():
        hi = bpy.data.objects.get(k)
        if hi is not None and hi is not ob:
            hi.name = k + "_hires"
            if hi.data is not None:
                hi.data.name = k + "_hires"
    for k, ob in low.items():
        key = assign.get(k) or ("summer" if k.startswith("Summer") else "winter")
        ob.data.materials.clear()
        ob.data.materials.append(mats[key])
        # remove extra UV layers / colour attributes not needed on the web
        for l in list(ob.data.uv_layers):
            if l.name != "UVMap":
                ob.data.uv_layers.remove(l)
        for ca in list(ob.data.color_attributes):
            ob.data.color_attributes.remove(ca)
        # drop vertex groups that are not bones
        bones = set(b.name for b in arm.data.bones)
        for vg in list(ob.vertex_groups):
            if vg.name not in bones:
                ob.vertex_groups.remove(vg)
        ob.name = k
        ob.data.name = k
    # names: web objects drop the _web suffix (original hi-res objects get renamed first)
    arm.data.pose_position = "POSE"

    # ---- character export: Armature + low meshes only
    for o in bpy.context.view_layer.objects:
        o.select_set(False)
    keep = set(low.values()) | {arm}
    for o in keep:
        o.hide_set(False)
        o.select_set(True)
    out_raw = os.path.join(BAKE, "character_raw.glb")
    bpy.ops.export_scene.gltf(filepath=out_raw, use_selection=True, export_format="GLB",
                              export_animation_mode="NLA_TRACKS", export_skins=True, export_morph=False,
                              export_yup=True, export_apply=False, export_texcoords=True, export_normals=True,
                              export_tangents=False, export_materials="EXPORT", export_image_format="AUTO",
                              export_force_sampling=True, export_frame_step=1, export_def_bones=False,
                              export_leaf_bone=False, export_optimize_animation_size=True,
                              export_extras=False, export_cameras=False, export_lights=False)
    stats = {"summer_tris": sum(tris(low[k]) for k in SUMMER), "winter_tris": sum(tris(low[k]) for k in WINTER),
             "per_mesh": {k: tris(v) for k, v in low.items()}}
    log("tris", stats)
    with open(os.path.join(BAKE, "stats.json"), "w") as f:
        json.dump(stats, f, indent=1)

    # ---- sled export
    export_sled()


def export_sled():
    bpy.ops.wm.open_mainfile(filepath=os.path.join(HERE, "character_hires.blend"))
    sc = bpy.context.scene
    sc.render.engine = "CYCLES"
    sled = bpy.data.objects["Sled"]
    sled.location = (0, 0, 0)
    for m in sled.modifiers:
        if m.type == "SUBSURF":
            m.levels = 0
    # apply solidify / bevel on a copy
    low = sled.copy()
    low.data = sled.data.copy()
    low.name = "Sled_web"
    sc.collection.objects.link(low)
    for m in list(low.modifiers):
        if m.type in ("SUBSURF", "BEVEL"):
            low.modifiers.remove(m)
    for m in list(low.modifiers):
        apply_mod(low, m.name)
    # bake the procedural plastic onto its own UVs (512)
    global RES
    RES = 512
    src = sled
    a = bake_pass([(src, low)], "ALBEDO", "sled_albedo", color=(0.02, 0.1, 0.3, 1))
    r = bake_pass([(src, low)], "ROUGH", "sled_rough", noncolor=True)
    n = bake_pass([(src, low)], "NORMAL", "sled_normal", noncolor=True, color=(0.5, 0.5, 1, 1), samples=4)
    o = orm_from_rough(r, os.path.join(BAKE, "sled_orm.png"))
    low.data.materials.clear()
    bpy.data.materials["SledPlastic"].name = "SledPlastic_hires"
    sled.data.name = "Sled_hires"
    low.data.name = "Sled"
    low.data.materials.append(web_material("SledPlastic", a, n, o, coat=0.3))
    bpy.data.materials["SledRope"].name = "SledRope_hires"
    rm = bpy.data.materials.new("SledRope")
    p = rm.node_tree.nodes["Principled BSDF"]
    p.inputs["Base Color"].default_value = (0.55, 0.52, 0.45, 1)
    p.inputs["Roughness"].default_value = 0.9
    ropes = []
    for r_ in [c for c in sled.children if c.name.startswith("SledRope")]:
        r_.data.bevel_resolution = 1
        r_.data.resolution_u = 3
        dg = bpy.context.evaluated_depsgraph_get()
        me = bpy.data.meshes.new_from_object(r_.evaluated_get(dg))
        nm_ = r_.name
        r_.name = nm_ + "_hires"
        ro = bpy.data.objects.new(nm_, me)
        sc.collection.objects.link(ro)
        ro.matrix_world = r_.matrix_world
        me.materials.clear()
        me.name = nm_
        me.materials.append(rm)
        ro.parent = low
        ro.matrix_parent_inverse = low.matrix_world.inverted()
        ropes.append(ro)
    seat = bpy.data.objects["SledSeat"]
    seat_web = bpy.data.objects.new("SledSeat", None)
    seat.name = "SledSeat_hires"
    seat_web.name = "SledSeat"
    sc.collection.objects.link(seat_web)
    seat_web.location = seat.matrix_world.translation
    seat_web.parent = low
    seat_web.matrix_parent_inverse = low.matrix_world.inverted()
    sled.name = "Sled_hires"
    low.name = "Sled"
    for o in bpy.context.view_layer.objects:
        o.select_set(False)
    for o in [low, seat_web] + ropes:
        o.select_set(True)
    bpy.ops.export_scene.gltf(filepath=os.path.join(BAKE, "sled_raw.glb"), use_selection=True, export_format="GLB",
                              export_animations=False, export_yup=True, export_apply=True, export_extras=False)
    log("sled tris", tris(low) + sum(tris(r) for r in ropes))


if __name__ == "__main__":
    main()
