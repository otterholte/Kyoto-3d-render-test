"""Season switch for the built scene: collection visibility, prototype mesh swaps, lights, sky."""
import bpy

import lighting


def apply(season):
    assert season in ("summer", "winter")
    S = season == "summer"
    for name, vis in (("Summer_Only", S), ("Winter_Only", not S)):
        c = bpy.data.collections.get(name)
        if c:
            c.hide_render = not vis
            lc = bpy.context.view_layer.layer_collection.children.get(name)
            if lc:
                lc.hide_viewport = not vis
    for ob in bpy.data.objects:
        key = "proto_summer" if S else "proto_winter"
        if key in ob.keys():
            me = bpy.data.meshes.get(ob[key])
            if me is not None and ob.data != me:
                ob.data = me
    # ground hidden under the snow in winter (the snow surface covers it; keeps curbs etc. for summer)
    g = bpy.data.collections.get("Ground")
    if g:
        for ob in g.objects:
            if ob.name.startswith("Ground_Soft") or ob.name.startswith("Street_Details"):
                ob.hide_render = not S
            if ob.name == "Backdrop_Ground":
                ob.data.materials[0] = bpy.data.materials["BACKDROP_forest"] if S else bpy.data.materials["SNOW_fresh"]
    lighting.world_setup(season)
    lighting.set_lights(not S)
    bpy.context.scene["season"] = season
