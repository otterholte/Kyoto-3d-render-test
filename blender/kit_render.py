"""Render the art-directed shots from blender/higashiyama_art.blend.

  /home/user/venv/bin/python blender/kit_render.py --shots a,b --res 960 --samples 32 [--out renders/test_]
  final:  --res 3840 --samples 160 --out renders/final_
Writes renders/<prefix><shot>.png and appends timings to renders/render_log.json.
"""
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import bpy  # noqa: E402

A = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]


def arg(k, d=None):
    return A[A.index(k) + 1] if k in A else d


ROOT = os.path.dirname(HERE)
blend = arg("--blend", os.path.join(HERE, "higashiyama_art.blend"))
bpy.ops.wm.open_mainfile(filepath=blend)
import kit_light  # noqa: E402

scene = bpy.context.scene
kit_light.render_settings(scene)
res = int(arg("--res", 960))
scene.render.resolution_x = res
scene.render.resolution_y = res * 9 // 16
scene.render.resolution_percentage = 100
scene.cycles.samples = int(arg("--samples", 32))
if arg("--threshold"):
    scene.cycles.adaptive_threshold = float(arg("--threshold"))
if arg("--time-limit"):
    # one tile for the whole frame: with auto-tiling the time limit is spent per tile
    scene.cycles.time_limit = float(arg("--time-limit"))
    scene.cycles.use_auto_tile = False
    scene.cycles.tile_size = 4096
threads = arg("--threads")
if threads:
    scene.render.threads_mode = "FIXED"; scene.render.threads = int(threads)
# vignette blur scales with resolution
cn = scene.compositing_node_group
if cn and "VignetteBlur" in cn.nodes:
    s = int(300 * res / 3840) + 8
    cn.nodes["VignetteBlur"].inputs["Size"].default_value = (s, s)
if cn and "Kuwahara" in cn.nodes:
    cn.nodes["Kuwahara"].inputs["Size"].default_value = max(2, int(round(5 * res / 3840 * 1.6)))
if "--no-fog" in A and bpy.data.objects.get("FX_Fog_Volume"):
    bpy.data.objects["FX_Fog_Volume"].hide_render = True
_last = [0.0]


def _stats(st):
    if time.time() - _last[0] > 120:
        _last[0] = time.time()
        print("STATS", time.strftime("%H:%M:%S"), st, flush=True)


bpy.app.handlers.render_stats.append(_stats)
prefix = arg("--out", os.path.join("renders", "test_"))
shots = arg("--shots", "a,b,c,d,e").split(",")
cams = {o.name[4:]: o for o in bpy.data.objects if o.type == "CAMERA" and o.name.startswith("Cam_") and o.get("preset")}
log_p = os.path.join(ROOT, "renders", "render_log.json")
try:
    LOG = json.load(open(log_p))
except Exception:
    LOG = []
for sh in shots:
    name = next((k for k in cams if k.startswith(sh + "_") or k == sh), None)
    if name is None:
        print("no camera for", sh); continue
    cam = cams[name]
    scene.camera = cam
    kit_light.apply_preset(arg("--preset", cam["preset"]), scene)
    fog = bpy.data.materials.get("ART_Fog")
    if fog and cam.get("fog_scale", 1.0) != 1.0:
        fog.node_tree.nodes["FogVol"].inputs["Density"].default_value *= cam["fog_scale"]
    out = os.path.join(ROOT, prefix + name + ".png")
    scene.render.filepath = out
    t = time.time()
    bpy.ops.render.render(write_still=True)
    dt = time.time() - t
    print("RENDERED %s %.1fs" % (out, dt), flush=True)
    LOG.append(dict(shot=name, file=os.path.relpath(out, ROOT), res=[scene.render.resolution_x, scene.render.resolution_y],
                    samples=scene.cycles.samples, seconds=round(dt, 1), preset=scene.get("preset"),
                    when=time.strftime("%Y-%m-%d %H:%M:%S")))
    with open(log_p, "w") as f:
        json.dump(LOG, f, indent=1)
