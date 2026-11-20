"""Bilinear sampling of the processed terrain grid (local frame)."""
import os
import numpy as np
from common import PROC

_t = np.load(os.path.join(PROC, "terrain.npz"))
H = _t["heights"].astype(np.float64)
X0, Y0, STEP = float(_t["x0"]), float(_t["y0"]), float(_t["step"])
NY, NX = H.shape


def ground(x, y):
    x = np.asarray(x, float); y = np.asarray(y, float)
    fx = np.clip((x - X0) / STEP, 0, NX - 1.000001); fy = np.clip((y - Y0) / STEP, 0, NY - 1.000001)
    i = fx.astype(int); j = fy.astype(int); u = fx - i; v = fy - j
    return (H[j, i] * (1 - u) * (1 - v) + H[j, i + 1] * u * (1 - v) + H[j + 1, i] * (1 - u) * v + H[j + 1, i + 1] * u * v)
