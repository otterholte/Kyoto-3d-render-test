"""Build the Canby Court scene (both seasons) into blender/canby_court.blend.

  /home/user/venv/bin/python blender/build_scene.py [--lite]

Collections:
  Houses, Context, Ground (render terrain 0.5 m), Vegetation, Props  -> both seasons
  Summer_Only (grass instances), Winter_Only (snow ground, roof snow, car snow, jumps, berm, tracks)
  Web_Only (lighter terrain / snow ground for the GLB export; hidden in renders)
  Protos (vegetation prototypes, never rendered directly), Lights, Cameras
Season switch: seasons.apply(name) (also swaps deciduous/conifer prototype meshes).
"""
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import bpy  # noqa: E402

import cc_common as C  # noqa: E402


def log(*a):
    print("[build %6.1fs]" % (time.time() - T0), *a, flush=True)


T0 = time.time()


def main(lite=False):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    import houses
    import ground
    import vegetation as VEG
    import props
    import lighting
    import seasons
    import materials as MAT

    sc = bpy.context.scene
    sc.unit_settings.system = "METRIC"
    root = sc.collection
    col = {k: C.get_coll(k) for k in ("Houses", "Context", "Ground", "Vegetation", "Props", "Summer_Only",
                                      "Winter_Only", "Web_Only", "Protos", "Lights", "Cameras")}
    # ---------------------------------------------------------------- houses (plan), driveways, grading
    hbs = {h["number"]: houses.HouseBuilder(h["number"], col["Houses"]) for h in C.data("houses")["houses"]}
    drives = ground.plan_driveways(hbs)
    ground.grade(drives)
    log("driveways graded", len(drives))
    for n, hb in hbs.items():
        hb.build()
    for n, hb in hbs.items():
        if n != 3905:
            bpy.data.objects["House_%d" % n]["web_variant"] = True
            bpy.data.objects["House_%d_Roof" % n]["web_variant"] = True
            hb.build_web_simple(col["Web_Only"])
    log("houses built")
    houses.build_context(col["Context"])
    log("context built")
    walks = ground.plan_walks(hbs, drives)
    Gd = ground.Ground(hbs, drives, walks)
    gm = ground.ground_materials()
    gobjs = Gd.build(col["Ground"], 0.5, mats=gm)
    log("ground (render) built", {k: len(o.data.polygons) for k, o in gobjs.items()})
    Gw = ground.Ground(hbs, drives, walks)
    wobjs = Gw.build(col["Web_Only"], 1.0, suffix="_web", mats=gm)
    log("ground (web) built", {k: len(o.data.polygons) for k, o in wobjs.items()})
    ground.street_details(col["Ground"], hbs)
    # ---------------------------------------------------------------- vegetation
    vm = VEG.veg_materials()
    lib = VEG.Library(col["Protos"], vm, lite=lite)
    libw = VEG.Library(col["Protos"], vm, lite=True, sfx="_web")
    log("vegetation prototypes", len(lib.summer), "+ web lite")
    trees = VEG.plant_trees(lib, col["Vegetation"])
    hed = VEG.hedges(lib, col["Vegetation"], vm)
    run = ground.LineString(C.data("jumps")["run_path_local"]).buffer(3.5)
    avoid = [Gd.st.buffer(0.3), Gd.sw, Gd.dr, Gd.walk, run] + [ground.Polygon(hb.fp).buffer(0.4) for hb in hbs.values()]
    for d in getattr(hbs[3905], "deck_info", None) and [hbs[3905].deck_info] or []:
        pass
    shr = VEG.shrubs(lib, col["Vegetation"], Gd, avoid)
    log("trees", len(trees), "hedges", len(hed), "shrubs", len(shr))
    for ob in col["Vegetation"].objects:
        key = ob.get("proto")
        if key and key in libw.summer:
            ob["proto_summer_web"] = libw.summer[key].data.name
            ob["proto_winter_web"] = libw.winter[key].data.name
    # ---------------------------------------------------------------- props
    M = props._m()
    snow_mat = MAT.tex_mat("SNOW_fresh", "snow_fresh", rough_override=0.82, normal_strength=0.6)
    props.cars(col["Props"], M)
    # car snow lives in Winter_Only
    for (n, x, y, h, k, c) in props.CARS:
        pass
    props.mailboxes(col["Props"], M, drives)
    sf, street_lights = props.street_lights_hydrants(col["Props"], M)
    props.fences(col["Props"], M, hbs)
    props.yard_features(col["Props"], M)
    log("props")
    # ---------------------------------------------------------------- winter
    packed = MAT.tex_mat("SNOW_packed", "snow_packed")
    snow_ob = Gd.build_snow(col["Winter_Only"], {"fresh": snow_mat, "packed": packed}, 0.5)
    props.set_snow_surface(snow_ob)
    sw = Gw.build_snow(col["Web_Only"], {"fresh": snow_mat, "packed": packed}, 1.0, suffix="_web")
    for n, hb in hbs.items():
        hb.snow_cover(col["Winter_Only"], snow_mat)
    for ob in list(col["Props"].objects):
        if ob.get("kind") == "car":
            pass
    # snow on cars: rebuild only the snow pillows
    for (n, x, y, h, k, c) in props.CARS:
        objs = props.car(n + "_tmp", x, y, h, k, c, col["Winter_Only"], M, snow=snow_mat)
        bpy.data.objects.remove(objs[0])
        objs[1].name = n + "_Snow"
    J = C.data("jumps")
    for j in J["jumps"]:
        props.kicker(j, col["Winter_Only"], M)
    props.berm(J["runout_berm"], col["Winter_Only"], M)
    props.sled_tracks(col["Winter_Only"], M)
    log("winter overlays")
    # ---------------------------------------------------------------- distant backdrop (render only)
    import numpy as _np
    bx = [(-3000, -3000), (3000, -3000), (3000, 3000), (-3000, 3000)]
    hole = [(-209, -159), (109, -159), (109, 109), (-209, 109)]
    dz = C.dtm()
    zc = lambda x, y: float(dz.sample(x, y)) - 0.6
    V = [(x, y, 105.0) for x, y in bx] + [(x, y, zc(x, y)) for x, y in hole]
    Fc = [[0, 1, 5, 4], [1, 2, 6, 5], [2, 3, 7, 6], [3, 0, 4, 7]]
    bd = C.mesh_from_data("Backdrop_Ground", V, Fc, coll=col["Ground"],
                          uvs=_np.array([V[i][:2] for f in Fc for i in f]) / 20.0)
    bd.data.materials.append(MAT.tex_mat("BACKDROP_forest", "forest_floor", tint="#5d6b4a"))
    bd["render_only"] = True
    # ---------------------------------------------------------------- lights, cameras, grass
    lighting.porch_lamps(hbs, col["Lights"])
    cams = lighting.cameras(col["Cameras"])
    camxy = [tuple(c.location)[:2] for k, c in cams.items() if k in ("a", "c")]
    VEG.grass_zone(gobjs["soft"], camxy, col["Summer_Only"], col["Protos"], vm)
    log("grass")
    # ---------------------------------------------------------------- markers (exported as empty nodes)
    mk = C.get_coll("Markers")
    dz = C.dtm()
    import math as _m

    def marker(name, x, y, zz, heading=None, **ex):
        e = bpy.data.objects.new(name, None)
        e.empty_display_type = "ARROWS"
        e.location = (x, y, zz)
        if heading is not None:
            e.rotation_euler = (0, 0, heading)
        mk.objects.link(e)
        C.set_extras(e, kind="marker", collide=False, walkable=False, **ex)
        return e
    for n, hb in hbs.items():
        for kind, lst in hb.doors_info.items():
            for i, d in enumerate(lst):
                nx, ny = d["normal"]
                px, py = d["center"][0] + nx * 1.2, d["center"][1] + ny * 1.2
                nm = "Marker_%d_FrontDoor" % n if kind == "door" else "Marker_%d_GarageDoor_%d" % (n, i + 1)
                marker(nm, px, py, max(d["z"], float(dz.sample(px, py))), _m.atan2(-ny, -nx),
                       address="%d Canby Ct" % n, note="1.2 m outside the door, rotation faces the door",
                       door_center=[round(d["center"][0], 2), round(d["center"][1], 2), round(d["z"], 2)])
    h5 = hbs[3905]
    if getattr(h5, "deck_info", None):
        di = h5.deck_info
        marker("Marker_3905_Deck", di["center"][0], di["center"][1], di["z"], address="3905 Canby Ct")
        sb = di["stairs_bottom"]
        marker("Marker_3905_DeckStairs", sb[0], sb[1], float(dz.sample(*sb)), address="3905 Canby Ct")
    if getattr(h5, "patio_info", None):
        pi_ = h5.patio_info
        marker("Marker_3905_Patio", pi_["center"][0], pi_["center"][1], pi_["z"], address="3905 Canby Ct")
    marker("Marker_3905_BackYard", -3.0, 19.0, float(dz.sample(-3.0, 19.0)), address="3905 Canby Ct",
           note="middle of the north lawn (play structure W, shed NE, raised beds N)")
    marker("Marker_3905_WestLawn", -13.0, 2.0, float(dz.sample(-13.0, 2.0)), address="3905 Canby Ct")
    J = C.data("jumps")
    st = J["start"]["center_local"]
    marker("Marker_SledStart", st[0], st[1], float(dz.sample(*st)), _m.radians(J["start"]["heading_deg"]),
           artistic=True, season="winter", note="top of the measured sled run; rotation = downhill heading")
    rb = J["runout_berm"]["center_local"]
    marker("Marker_RunoutBerm", rb[0], rb[1], float(dz.sample(*rb)), artistic=True, season="winter")
    marker("Marker_Spawn_Bulb", -27.0, -27.0, float(dz.sample(-27.0, -27.0)), _m.radians(45),
           note="centre of the Canby Ct bulb, facing 3905")
    # ---------------------------------------------------------------- metadata for docs / game
    meta = {"houses": {}}
    for n, hb in hbs.items():
        meta["houses"][str(n)] = dict(floor_z=round(hb.floor, 2), doors=hb.doors_info,
                                      deck=getattr(hb, "deck_info", None), patio=getattr(hb, "patio_info", None),
                                      wings=[dict(kind=w.kind, roof=w.roof, eave_z=round(w.eave, 2),
                                                  ridge_z=round(w.ridge_z(), 2), pitch_12=round(w.p * 12, 1))
                                             for w in hb.wings])
    meta["driveways"] = {str(d["house"]): [list(map(float, c)) for c in d["line"].coords] for d in drives}
    import json
    json.dump(meta, open(os.path.join(HERE, "scene_meta.json"), "w"), indent=1)
    # ---------------------------------------------------------------- finish
    col["Protos"].hide_render = True
    col["Web_Only"].hide_render = True
    for c_ in (col["Protos"], col["Web_Only"]):
        lc = bpy.context.view_layer.layer_collection.children.get(c_.name)
        if lc:
            lc.exclude = False
            lc.hide_viewport = True
    lighting.render_settings()
    seasons.apply("summer")
    bpy.ops.wm.save_as_mainfile(filepath=C.BLEND, compress=False)
    log("saved", C.BLEND)


if __name__ == "__main__":
    main(lite="--lite" in sys.argv)
