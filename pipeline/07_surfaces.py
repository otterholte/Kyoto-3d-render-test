"""Ground-surface classification raster (shared by Blender + web).

data/processed/surface_mask.png  RGBA, 0.5 m/px, covering the terrain grid extent (local -300..+300 m)
  R = asphalt / vehicle road        (PLATEAU road area, OSM surface=asphalt/concrete)
  G = stone paving (ishidatami)     (OSM surface=paving_stones/stone/sett/cobblestone, pedestrian streets)
  B = gravel / packed earth paths   (OSM surface=gravel/fine_gravel/dirt/ground/unpaved/compacted)
  A = 255 everywhere (unclassified ground = soil / moss / garden)
data/processed/steps.json   stair geometry spec per OSM steps way (centreline, width, n, riser, tread, z0/z1)
"""
import json
import os
import numpy as np
from PIL import Image, ImageDraw
from shapely.geometry import LineString, Polygon
from common import PROC
from terrain_sample import ground, X0, Y0, STEP, NX, NY

S = json.load(open(os.path.join(PROC, "streets.json")))
RES = 0.5
ext_x0, ext_y1 = X0, Y0 + (NY - 1) * STEP
W = int(round((NX - 1) * STEP / RES)); Hh = int(round((NY - 1) * STEP / RES))


def px(pts):
    return [((x - ext_x0) / RES, (ext_y1 - y) / RES) for x, y in pts]


R = Image.new("L", (W, Hh), 0); G = Image.new("L", (W, Hh), 0); B = Image.new("L", (W, Hh), 0)
dR, dG, dB = ImageDraw.Draw(R), ImageDraw.Draw(G), ImageDraw.Draw(B)


def fill(poly, layer):
    polys = getattr(poly, "geoms", [poly])
    for p in polys:
        if p.is_empty or p.geom_type != "Polygon":
            continue
        tgt = {"R": dR, "G": dG, "B": dB}[layer]
        for other in {"R": (dG, dB), "G": (dR, dB), "B": (dR, dG)}[layer]:
            other.polygon(px(p.exterior.coords), fill=0)
        tgt.polygon(px(p.exterior.coords), fill=255)
        for h in p.interiors:
            tgt.polygon(px(h.coords), fill=0)


for r in S["plateau_roads"]:
    rings = r["exterior"] if r["multi"] else [r["exterior"]]
    for ring in rings:
        if len(ring) >= 3:
            fill(Polygon(ring), "R")

STONE = {"paving_stones", "stone", "sett", "cobblestone", "unhewn_cobblestone", "granite"}
GRAVEL = {"gravel", "fine_gravel", "dirt", "ground", "unpaved", "compacted", "earth", "pebblestone", "sand"}
order = sorted(S["streets"], key=lambda s: 0 if s["highway"] in ("secondary", "tertiary", "unclassified", "residential", "service") else 1)
steps = []
for s in order:
    if s["highway"] in ("steps",):
        continue
    sf = s["surface"]
    if sf in STONE or (sf is None and s["highway"] == "pedestrian"):
        layer = "G"
    elif sf in GRAVEL or (sf is None and s["highway"] in ("path", "track")):
        layer = "B"
    elif s["highway"] in ("footway", "path") and sf is None:
        layer = "G" if s["in_box"] else "R"
    else:
        layer = "R"
    fill(LineString(s["coords"]).buffer(s["width_m"] / 2, cap_style="flat" if layer == "R" else "round", join_style="round"), layer)

for s in S["streets"]:
    if s["highway"] != "steps":
        continue
    ln = LineString(s["coords"])
    z = s["z"]
    z0, z1 = z[0], z[-1]
    up_forward = z1 >= z0
    rise = abs(z1 - z0)
    n = None
    if s["step_count"]:
        try:
            n = int(s["step_count"])
        except ValueError:
            n = None
    src = "osm:step_count"
    if not n:
        n = max(1, int(round(rise / 0.16))); src = "terrain rise / 0.16 m riser (inferred)"
    if rise < 0.05:
        rise = 0.16 * n
        src += "; terrain shows no rise -> nominal 0.16 m risers (inferred)"
    fill(ln.buffer(s["width_m"] / 2, cap_style="flat"), "G" if (s["surface"] in STONE or s["surface"] is None) else "R")
    steps.append(dict(osm_id=s["osm_id"], name=s["name"], coords=s["coords"], width_m=s["width_m"],
                      width_src=s["width_src"], n=n, n_src=src, z_bottom=round(min(z0, z1), 3),
                      z_top=round(min(z0, z1) + rise, 3), ascending_along_way=up_forward,
                      riser_m=round(rise / n, 3), tread_m=round(ln.length / n, 3), length_m=round(ln.length, 2),
                      surface=s["surface"], in_box=s["in_box"], handrail=s["handrail"]))

img = Image.merge("RGBA", (R, G, B, Image.new("L", (W, Hh), 255)))
img.save(os.path.join(PROC, "surface_mask.png"))
json.dump(dict(res_m=RES, extent=[ext_x0, ext_x0 + W * RES, ext_y1 - Hh * RES, ext_y1], steps=steps),
          open(os.path.join(PROC, "steps.json"), "w"), ensure_ascii=False, indent=1)
a = np.asarray(img)
print("mask", img.size, "coverage % R/G/B", [round(100 * (a[..., i] > 0).mean(), 1) for i in range(3)], "steps", len(steps))
