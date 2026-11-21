"""Distant backdrop (real surroundings) for the Higashiyama scene: collection "95_Distant_Backdrop".

Library use (from any build script, after the scene exists):
    sys.path.insert(0, "<repo>/blender"); from build_backdrop import add_backdrop
    add_backdrop(bpy.context.scene, detail="render")      # or detail="web"

Script use (checks + web asset):
    /home/user/venv/bin/python blender/build_backdrop.py [--no-render] [--no-glb] [--samples 16]
      opens blender/higashiyama_blockout.blend (never saved), adds the render backdrop,
      renders renders/backdrop_check_aerial_sw.png + renders/backdrop_check_yasaka_east.png (960x540),
      then rebuilds the backdrop at web detail and writes web/assets/backdrop.glb.

Data: data/processed/backdrop_{render,web}.npz + backdrop_meta.json from pipeline/10_backdrop.py.
Frame: 1 unit = 1 m, +X east, +Y north, +Z absolute T.P. height (as build_world.py). The inner +-300 m is a hole:
ring A zips exactly onto the boundary vertices of Terrain_GSI_DEM5A (2 m), with a 3 m skirt under the seam.
"""
import json
import os
import struct
import sys

import bpy  # noqa: I001  (bpy before anything that may import bmesh)
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PROC = os.path.join(ROOT, "data", "processed")
COLL_NAME = "95_Distant_Backdrop"
HAZE_RGB = (0.62, 0.68, 0.78)       # linear; a pale sky-blue haze, tuned per lighting preset via the node


# ------------------------------------------------------------------ helpers
def _srgb_to_linear(c):
    c = np.asarray(c, np.float32) / 255.0
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4).astype(np.float32)


def _linear_to_u8(c):
    return np.clip(np.round(np.asarray(c) * 255.0), 0, 255).astype(np.uint8)


def _mesh(name, V, F, C, smooth):
    me = bpy.data.meshes.new(name)
    n, m = len(V), len(F)
    me.vertices.add(n)
    me.vertices.foreach_set("co", np.asarray(V, np.float32).ravel())
    me.loops.add(3 * m)
    me.loops.foreach_set("vertex_index", np.asarray(F, np.int32).ravel())
    me.polygons.add(m)
    me.polygons.foreach_set("loop_start", np.arange(0, 3 * m, 3, dtype=np.int32))
    me.update(calc_edges=True)
    lin = _srgb_to_linear(C)
    col = me.color_attributes.new("Col", "FLOAT_COLOR", "POINT")
    col.data.foreach_set("color", np.c_[lin, np.ones(n, np.float32)].ravel())
    me.color_attributes.active_color = col
    if smooth:
        me.polygons.foreach_set("use_smooth", np.ones(m, bool))
    me.validate(clean_customdata=False)
    return me


def _material(name, rough, haze, bump=0.0):
    """Vertex colour (measured ortho / PLATEAU-derived) -> Principled, mixed toward a haze emission with
    camera distance (aerial perspective). Nodes 'BackdropHaze' (RGB) and 'BackdropHazeAmount' (Value) are
    the knobs a lighting preset can retune; 'BackdropHazeDistance' (Value, m) sets the e-folding distance."""
    m = bpy.data.materials.get(name)
    if m:
        return m
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    nt.nodes.clear()
    N, L = nt.nodes.new, nt.links.new
    out = N("ShaderNodeOutputMaterial")
    attr = N("ShaderNodeAttribute"); attr.attribute_type = "GEOMETRY"; attr.attribute_name = "Col"
    bsdf = N("ShaderNodeBsdfPrincipled")
    bsdf.inputs["Roughness"].default_value = rough
    bsdf.inputs["Specular IOR Level"].default_value = 0.3
    L(attr.outputs["Color"], bsdf.inputs["Base Color"])
    if bump > 0:          # canopy: crown-scale bump (artistic shading only, no geometry)
        tc = N("ShaderNodeTexCoord")
        nz = N("ShaderNodeTexNoise"); nz.inputs["Scale"].default_value = 0.12; nz.inputs["Detail"].default_value = 3.0
        L(tc.outputs["Object"], nz.inputs["Vector"])
        bp = N("ShaderNodeBump"); bp.inputs["Strength"].default_value = bump; bp.inputs["Distance"].default_value = 4.0
        L(nz.outputs["Fac"], bp.inputs["Height"])
        L(bp.outputs["Normal"], bsdf.inputs["Normal"])
    cam = N("ShaderNodeCameraData")
    hd = N("ShaderNodeValue"); hd.name = hd.label = "BackdropHazeDistance"; hd.outputs[0].default_value = 9000.0
    ha = N("ShaderNodeValue"); ha.name = ha.label = "BackdropHazeAmount"; ha.outputs[0].default_value = haze
    hc = N("ShaderNodeRGB"); hc.name = hc.label = "BackdropHaze"; hc.outputs[0].default_value = (*HAZE_RGB, 1)
    div = N("ShaderNodeMath"); div.operation = "DIVIDE"
    L(cam.outputs["View Distance"], div.inputs[0]); L(hd.outputs[0], div.inputs[1])
    ex = N("ShaderNodeMath"); ex.operation = "EXPONENT"
    neg = N("ShaderNodeMath"); neg.operation = "MULTIPLY"; neg.inputs[1].default_value = -1.0
    L(div.outputs[0], neg.inputs[0]); L(neg.outputs[0], ex.inputs[0])
    one = N("ShaderNodeMath"); one.operation = "SUBTRACT"; one.inputs[0].default_value = 1.0
    L(ex.outputs[0], one.inputs[1])
    fac = N("ShaderNodeMath"); fac.operation = "MULTIPLY"; fac.use_clamp = True
    L(one.outputs[0], fac.inputs[0]); L(ha.outputs[0], fac.inputs[1])
    em = N("ShaderNodeEmission"); L(hc.outputs[0], em.inputs["Color"])
    mix = N("ShaderNodeMixShader")
    L(fac.outputs[0], mix.inputs[0]); L(bsdf.outputs[0], mix.inputs[1]); L(em.outputs[0], mix.inputs[2])
    L(mix.outputs[0], out.inputs["Surface"])
    m["backdrop_material"] = True
    return m


def _add_bump(m, scale, strength, dist):
    nt = m.node_tree
    if nt.nodes.get("BackdropBump"):
        return
    bsdf = next(n for n in nt.nodes if n.type == "BSDF_PRINCIPLED")
    tc = nt.nodes.new("ShaderNodeTexCoord")
    nz = nt.nodes.new("ShaderNodeTexNoise"); nz.inputs["Scale"].default_value = scale; nz.inputs["Detail"].default_value = 4.0
    nt.links.new(tc.outputs["Object"], nz.inputs["Vector"])
    bp = nt.nodes.new("ShaderNodeBump"); bp.name = "BackdropBump"
    bp.inputs["Strength"].default_value = strength; bp.inputs["Distance"].default_value = dist
    nt.links.new(nz.outputs["Fac"], bp.inputs["Height"]); nt.links.new(bp.outputs["Normal"], bsdf.inputs["Normal"])


def _collection(scene):
    old = bpy.data.collections.get(COLL_NAME)
    if old:
        for ob in list(old.objects):
            me = ob.data
            bpy.data.objects.remove(ob, do_unlink=True)
            if me and me.users == 0:
                bpy.data.meshes.remove(me)
        bpy.data.collections.remove(old)
    c = bpy.data.collections.new(COLL_NAME)
    scene.collection.children.link(c)
    return c


# ------------------------------------------------------------------ public
def add_backdrop(scene=None, detail="render", haze=0.35, extend_clip=True, hide_conflicting=True):
    """Build collection 95_Distant_Backdrop from data/processed/backdrop_<detail>.npz.

    detail          "render" (4/12/72 m terrain rings, separate canopy, full PLATEAU LOD1 + LOD2 near the box)
                    or "web" (12/48/252 m rings, canopy merged into the terrain, filtered/simplified LOD1).
    haze            default aerial-perspective amount baked into the backdrop materials (0 disables).
    extend_clip     raise every scene camera's clip_end to >= 40 km so the 15 km horizon ring is visible.
    hide_conflicting  hide (render + viewport) older placeholder far-terrain objects named Backdrop_DEM10B_*
                    (blender/kit_backdrop.py, artistic land cover) that would overlap this measured backdrop.
    Returns the collection.
    """
    scene = scene or bpy.context.scene
    z = np.load(os.path.join(PROC, "backdrop_%s.npz" % detail))
    info = json.loads(str(z["objects"]))
    meta = json.load(open(os.path.join(PROC, "backdrop_meta.json")))
    coll = _collection(scene)
    mats = {"terrain": _material("BD_Terrain", 0.95, haze),
            "canopy": _material("BD_Canopy", 0.9, haze, bump=0.25),
            "city": _material("BD_City", 0.8, haze)}
    # terrain: faint 25 m-scale shading bump so flat far ground reads as textured land, never as a water sheet
    _add_bump(mats["terrain"], 0.04, 0.12, 3.0)
    for k, o in enumerate(info):
        V, F, C = z["V%d" % k], z["F%d" % k].astype(np.int64), z["C%d" % k]
        me = _mesh(o["name"], V, F, C, smooth=o["kind"] != "city")
        me.materials.append(mats[o["kind"]])
        ob = bpy.data.objects.new(o["name"], me)
        coll.objects.link(ob)
        ob["source"] = o["source"]
        ob["artistic"] = bool(o["artistic"])
        ob["kind"] = o["kind"]
        ob["detail"] = detail
        if "step_m" in o:
            ob["grid_step_m"] = float(o["step_m"]); ob["ring_extent_m"] = [float(v) for v in o["extent_m"]]
        ob["exclude_web"] = detail != "web"
        ob.visible_shadow = o["kind"] != "terrain" or o["name"].startswith("Backdrop_Terrain_A")
    coll["detail"] = detail
    coll["sources"] = json.dumps(meta["sources"], ensure_ascii=False)
    coll["forest_rule"] = meta["forest"]["rule"]
    coll["frame"] = meta["frame"]
    coll["earth_curvature"] = meta["earth_curvature"]
    coll["artistic_parts"] = ("canopy height (12-20 m value noise), canopy late-autumn palette, haze; "
                              "wall colours statistically assigned from measured inner PLATEAU textures")
    if extend_clip:
        for ob in scene.objects:
            if ob.type == "CAMERA" and ob.data.clip_end < 40000:
                ob.data.clip_end = 40000.0
    if hide_conflicting:
        for ob in scene.objects:
            if ob.name.startswith("Backdrop_DEM10B"):
                ob.hide_render = True; ob.hide_viewport = True
    return coll


# ------------------------------------------------------------------ glTF (GLB) writer
def export_glb(path, coll=None):
    """Write the collection as a compact GLB: Y-up (x, z, -y), POSITION float32, COLOR_0 RGBA8 (linear,
    normalised), uint16 indices (objects split into <=65535-vertex primitives), no normals (three.js
    GLTFLoader then flat-shades, as world_art.glb does), node extras = source/artistic flags."""
    coll = coll or bpy.data.collections[COLL_NAME]
    meta = json.load(open(os.path.join(PROC, "backdrop_meta.json")))
    bin_parts, views, accs, meshes, nodes = [], [], [], [], []
    off = 0

    def add_view(data, target):
        nonlocal off
        b = data.tobytes()
        pad = (-len(b)) % 4
        bin_parts.append(b + b"\0" * pad)
        views.append(dict(buffer=0, byteOffset=off, byteLength=len(b), target=target))
        off += len(b) + pad
        return len(views) - 1

    for ob in sorted(coll.objects, key=lambda o: o.name):
        me = ob.data
        n = len(me.vertices)
        co = np.empty(n * 3, np.float32); me.vertices.foreach_get("co", co); co = co.reshape(-1, 3)
        me.calc_loop_triangles()
        tri = np.empty(len(me.loop_triangles) * 3, np.int32); me.loop_triangles.foreach_get("vertices", tri)
        tri = tri.reshape(-1, 3)
        col = np.empty(n * 4, np.float32); me.color_attributes["Col"].data.foreach_get("color", col)
        col = _linear_to_u8(col.reshape(-1, 4)); col[:, 3] = 255
        P = np.c_[co[:, 0], co[:, 2], -co[:, 1]].astype(np.float32)        # Z-up -> Y-up
        prims = []
        s, step = 0, 40000
        while s < len(tri):
            e = min(len(tri), s + step)
            used, inv = np.unique(tri[s:e].ravel(), return_inverse=True)
            if len(used) > 65535:
                step //= 2
                continue
            pv = P[used]
            ia = add_view(inv.astype(np.uint16), 34963)
            pa = add_view(pv, 34962)
            ca = add_view(col[used], 34962)
            accs.append(dict(bufferView=pa, componentType=5126, count=len(used), type="VEC3",
                             min=pv.min(0).tolist(), max=pv.max(0).tolist()))
            accs.append(dict(bufferView=ca, componentType=5121, normalized=True, count=len(used), type="VEC4"))
            accs.append(dict(bufferView=ia, componentType=5123, count=int(inv.size), type="SCALAR"))
            prims.append(dict(attributes=dict(POSITION=len(accs) - 3, COLOR_0=len(accs) - 2), indices=len(accs) - 1,
                              material=0, mode=4))
            s = e
            step = 40000
        meshes.append(dict(name=ob.name, primitives=prims))
        ex = {k: ob[k] for k in ("source", "artistic", "kind", "detail", "grid_step_m") if k in ob}
        ex["artistic"] = bool(ex.get("artistic", False))
        nodes.append(dict(name=ob.name, mesh=len(meshes) - 1, extras=ex))
    gl = dict(
        asset=dict(version="2.0", generator="kyoto-3d-render-test blender/build_backdrop.py"),
        scene=0, scenes=[dict(name=COLL_NAME, nodes=list(range(len(nodes))), extras=dict(
            frame="glTF Y-up: x = east, y = T.P. height (absolute), z = -north; metres; origin EPSG:6674 E -20160 N -111160",
            inner_hole="|x|,|z| <= 300 m is a hole: world_art.glb / world.glb terrain fills it",
            sources=meta["sources"], forest_rule=meta["forest"]["rule"], earth_curvature=meta["earth_curvature"],
            artistic="canopy height/colour (forest extent is measured luse), wall colours statistically assigned",
            detail=coll.get("detail", "web")))],
        nodes=nodes, meshes=meshes,
        materials=[dict(name="Backdrop_VertexColour", pbrMetallicRoughness=dict(
            baseColorFactor=[1, 1, 1, 1], metallicFactor=0.0, roughnessFactor=0.95))],
        accessors=accs, bufferViews=views, buffers=[dict(byteLength=off)])
    js = json.dumps(gl, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    js += b" " * ((-len(js)) % 4)
    binb = b"".join(bin_parts)
    with open(path, "wb") as f:
        f.write(struct.pack("<III", 0x46546C67, 2, 12 + 8 + len(js) + 8 + len(binb)))
        f.write(struct.pack("<II", len(js), 0x4E4F534A)); f.write(js)
        f.write(struct.pack("<II", len(binb), 0x004E4942)); f.write(binb)
    return os.path.getsize(path), len(meshes), sum(len(m["primitives"]) for m in meshes)


# ------------------------------------------------------------------ script entry
def _look_at(cam, target):
    from mathutils import Vector
    d = Vector(target) - cam.location
    cam.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()


def main(argv):
    sys.path.insert(0, os.path.join(ROOT, "pipeline"))
    from terrain_sample import ground
    bpy.ops.wm.open_mainfile(filepath=os.path.join(HERE, "higashiyama_blockout.blend"))
    scene = bpy.context.scene
    samples = int(argv[argv.index("--samples") + 1]) if "--samples" in argv else 16
    coll = add_backdrop(scene, "render")
    tris = sum(len(o.data.polygons) for o in coll.objects)
    print("render backdrop:", len(coll.objects), "objects", tris, "tris", flush=True)
    if "--no-render" not in argv:
        scene.render.engine = "CYCLES"
        scene.cycles.device = "CPU"
        scene.cycles.samples = samples
        scene.cycles.use_denoising = True
        scene.render.threads_mode = "FIXED"; scene.render.threads = 3
        scene.render.resolution_x, scene.render.resolution_y = 960, 540
        scene.render.resolution_percentage = 100
        scene.render.image_settings.file_format = "PNG"
        gz = lambda x, y: float(ground(x, y))  # noqa: E731
        cd = bpy.data.cameras.new("Cam_Backdrop_YasakaEast"); cd.lens = 30; cd.clip_end = 40000
        cam = bpy.data.objects.new("Cam_Backdrop_YasakaEast", cd); scene.collection.objects.link(cam)
        cam.location = (-79.0, 88.2, gz(-79.0, 88.2) + 1.6)
        _look_at(cam, (300.0, 95.0, gz(-79.0, 88.2) + 1.6 + 380 * 0.16))
        cw = bpy.data.cameras.new("Cam_Backdrop_Wide"); cw.lens = 32; cw.clip_end = 40000
        camw = bpy.data.objects.new("Cam_Backdrop_Wide", cw); scene.collection.objects.link(camw)
        camw.location = (-2600.0, -1900.0, 650.0)      # over Shimogyo, looking ENE at Higashiyama
        _look_at(camw, (900.0, 400.0, 120.0))
        shots = [("aerial_sw", scene.objects["Cam_Aerial_SW"]), ("yasaka_east", cam), ("wide_ene", camw),
                 ("yasaka_east_nostreet", cam)]
        only = argv[argv.index("--shots") + 1].split(",") if "--shots" in argv else None
        for nm, c in shots:
            if only and nm not in only:
                continue
            scene.camera = c
            # *_nostreet: same view with the inner street buildings/walls hidden (pagoda kept) to show the
            # hills that the blockout's box massing occludes from street level
            for cl in scene.collection.children:
                if cl.name.startswith(("30_", "40_")):
                    cl.hide_render = nm.endswith("_nostreet")
            scene.render.filepath = os.path.join(ROOT, "renders", "backdrop_check_%s.png" % nm)
            bpy.ops.render.render(write_still=True)
            print("wrote", scene.render.filepath, flush=True)
    if "--no-glb" not in argv:
        coll = add_backdrop(scene, "web")
        size, nm, npr = export_glb(os.path.join(ROOT, "web", "assets", "backdrop.glb"), coll)
        print("backdrop.glb %.2f MB, %d meshes, %d primitives, %d tris" % (
            size / 1e6, nm, npr, sum(len(o.data.polygons) for o in coll.objects)), flush=True)


if __name__ == "__main__":
    main(sys.argv[1:])
