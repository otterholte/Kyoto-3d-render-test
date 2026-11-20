"""Phase 2B/4: terrain heightfield from GSI DEM5A (5 m laser-survey grid, z15 text tiles).

Output data/processed/terrain.npz:
  heights[j, i] (m, T.P.) on a regular grid in the LOCAL frame (x east, y north, origin = box centre)
  x0, y0, step, nx, ny, plus a 'source' mask (1 = DEM5A, 2 = interpolated over no-data).
Bare-earth DEM: DEM5A is the ground surface with buildings/trees removed by GSI.
"""
import glob
import math
import os
import numpy as np
from scipy.interpolate import griddata
from common import RAW, PROC, load_boundary, ll2en

b = load_boundary()
OE, ON = b["origin_e"], b["origin_n"]
MARGIN = 100.0
STEP = 2.0
pts, vals = [], []
for f in glob.glob(os.path.join(RAW, "gsi", "dem5a", "15", "*", "*.txt")):
    z = 15
    tx = int(f.split(os.sep)[-2]); ty = int(os.path.basename(f).split(".")[0])
    rows = [r.split(",") for r in open(f).read().strip().split("\n")]
    for py, row in enumerate(rows):
        for px, v in enumerate(row):
            if v.strip() == "e":
                continue
            # pixel centre -> lon/lat (Web Mercator tile scheme)
            gx = (tx * 256 + px + 0.5) / (256 * 2 ** z)
            gy = (ty * 256 + py + 0.5) / (256 * 2 ** z)
            lon = gx * 360 - 180
            lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * gy))))
            e, n = ll2en(lon, lat)
            x, y = e - OE, n - ON
            if abs(x) < 200 + MARGIN + 20 and abs(y) < 200 + MARGIN + 20:
                pts.append((x, y)); vals.append(float(v))
pts = np.array(pts); vals = np.array(vals)
xs = np.arange(-200 - MARGIN, 200 + MARGIN + 1e-6, STEP)
ys = np.arange(-200 - MARGIN, 200 + MARGIN + 1e-6, STEP)
GX, GY = np.meshgrid(xs, ys)
H = griddata(pts, vals, (GX, GY), method="linear")
src = np.where(np.isnan(H), 2, 1).astype(np.uint8)
# fill holes (no-data under some structures) with nearest -> then smooth those cells only
Hn = griddata(pts, vals, (GX, GY), method="nearest")
H = np.where(np.isnan(H), Hn, H)
# mark cells far from any DEM sample as interpolated
from scipy.spatial import cKDTree
d, _ = cKDTree(pts).query(np.c_[GX.ravel(), GY.ravel()])
src[(d.reshape(GX.shape) > 6.0)] = 2
os.makedirs(PROC, exist_ok=True)
np.savez_compressed(os.path.join(PROC, "terrain.npz"), heights=H.astype(np.float32), source=src,
                    x0=xs[0], y0=ys[0], step=STEP, nx=len(xs), ny=len(ys))
inb = (np.abs(GX) <= 200) & (np.abs(GY) <= 200)
print("samples", len(vals), "grid", H.shape, "in-box min/max", H[inb].min(), H[inb].max(),
      "interp cells in box %", round(100 * (src[inb] == 2).mean(), 2))
px, py = b["pagoda"]["local_x"], b["pagoda"]["local_y"]
i = int(round((px - xs[0]) / STEP)); j = int(round((py - ys[0]) / STEP))
print("ground at pagoda", H[j, i])
