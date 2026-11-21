"""Backdrop helper: GSI (国土地理院) XYZ tiles -> mosaics + local-frame samplers.

Layers used (all 出典: 国土地理院, GSI terms of use):
  dem5a_png / dem5b_png  z15   5 m DEM (laser / photogrammetry), PNG elevation encoding (0.01 m)
  dem_png                z14   DEM10B 10 m (fallback where DEM5 has no data), z12 for the far horizon ring
  seamlessphoto          z16   orthophoto (roof colours, ground colour in the 6 km area), z12 for the far ring
Tiles are cached under data/raw/gsi/backdrop/<layer>/<z>/<x>/<y>.<ext>.
"""
import io
import math
import os
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import requests
from PIL import Image

from common import RAW, load_boundary, en2ll

UA = {"User-Agent": "kyoto-reconstruction/1.0 (open data research)"}
BASE = "https://cyberjapandata.gsi.go.jp/xyz"
CACHE = os.path.join(RAW, "gsi", "backdrop")
_b = load_boundary()
OE, ON = _b["origin_e"], _b["origin_n"]


def lonlat_to_px(lon, lat, z):
    """lon/lat (deg) -> global Web-Mercator pixel coords at zoom z (pixel corners at integers)."""
    n = 256.0 * 2 ** z
    lat = np.radians(np.asarray(lat, float))
    x = (np.asarray(lon, float) + 180.0) / 360.0 * n
    y = (1 - np.log(np.tan(lat) + 1 / np.cos(lat)) / math.pi) / 2 * n
    return x, y


def local_to_px(x, y, z):
    lon, lat = en2ll(np.asarray(x, float) + OE, np.asarray(y, float) + ON)
    return lonlat_to_px(lon, lat, z)


def _get(layer, z, x, y, ext):
    p = os.path.join(CACHE, layer, str(z), str(x), "%d.%s" % (y, ext))
    if os.path.exists(p):
        return p if os.path.getsize(p) > 0 else None
    url = "%s/%s/%d/%d/%d.%s" % (BASE, layer, z, x, y, ext)
    for a in range(4):
        try:
            r = requests.get(url, headers=UA, timeout=60)
            if r.status_code == 404:
                os.makedirs(os.path.dirname(p), exist_ok=True)
                open(p, "wb").close()          # remember "no tile"
                return None
            r.raise_for_status()
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "wb") as f:
                f.write(r.content)
            return p
        except Exception:
            time.sleep(2 * (a + 1))
    print("FAIL", url, flush=True)
    return None


def tile_range(half, z, cx=0.0, cy=0.0):
    xs = np.array([cx - half, cx + half, cx - half, cx + half]); ys = np.array([cy - half, cy - half, cy + half, cy + half])
    px, py = local_to_px(xs, ys, z)
    return int(px.min() // 256), int(px.max() // 256), int(py.min() // 256), int(py.max() // 256)


def _decode_dem_png(path):
    a = np.asarray(Image.open(path).convert("RGB"), np.int64)
    v = (a[..., 0] << 16) + (a[..., 1] << 8) + a[..., 2]
    h = np.where(v < 2 ** 23, v, v - 2 ** 24).astype(np.float64) * 0.01
    h[v == 2 ** 23] = np.nan
    return h


class Mosaic:
    """Raster mosaic in global pixel space at zoom z; .sample(x_local, y_local) bilinear."""

    def __init__(self, arr, z, px0, py0):
        self.a, self.z, self.px0, self.py0 = arr, z, px0, py0

    def sample(self, x, y, arr=None):
        a = self.a if arr is None else arr
        px, py = local_to_px(x, y, self.z)
        fx = np.clip(px - self.px0 - 0.5, 0, a.shape[1] - 1.0001)
        fy = np.clip(py - self.py0 - 0.5, 0, a.shape[0] - 1.0001)
        i = fx.astype(int); j = fy.astype(int); u = fx - i; v = fy - j
        if a.ndim == 3:
            u = u[..., None]; v = v[..., None]
        return (a[j, i] * (1 - u) * (1 - v) + a[j, i + 1] * u * (1 - v) + a[j + 1, i] * (1 - u) * v
                + a[j + 1, i + 1] * u * v)


def mosaic(layer, z, half, ext="png", kind="dem", threads=6):
    tx0, tx1, ty0, ty1 = tile_range(half, z)
    jobs = [(tx, ty) for tx in range(tx0, tx1 + 1) for ty in range(ty0, ty1 + 1)]
    with ThreadPoolExecutor(threads) as ex:
        paths = list(ex.map(lambda t: _get(layer, z, t[0], t[1], ext), jobs))
    W, H = (tx1 - tx0 + 1) * 256, (ty1 - ty0 + 1) * 256
    big = np.full((H, W), np.nan) if kind == "dem" else np.zeros((H, W, 3), np.float32)
    n_ok = 0
    for (tx, ty), p in zip(jobs, paths):
        if p is None:
            continue
        sl = (slice((ty - ty0) * 256, (ty - ty0 + 1) * 256), slice((tx - tx0) * 256, (tx - tx0 + 1) * 256))
        if kind == "dem":
            big[sl] = _decode_dem_png(p)
        else:
            big[sl] = np.asarray(Image.open(p).convert("RGB"), np.float32)
        n_ok += 1
    print("mosaic %s z%d: %d/%d tiles" % (layer, z, n_ok, len(jobs)), flush=True)
    return Mosaic(big, z, tx0 * 256, ty0 * 256), dict(layer=layer, z=z, tiles=len(jobs), tiles_ok=n_ok,
                                                      tile_x=[tx0, tx1], tile_y=[ty0, ty1])


def fused_dem15(half):
    """DEM5A -> DEM5B -> DEM10B(z14, upsampled) per pixel at z15. Returns mosaic + per-pixel source code."""
    a, ia = mosaic("dem5a_png", 15, half)
    b, ib = mosaic("dem5b_png", 15, half)
    c, ic = mosaic("dem_png", 14, half)
    H = a.a.copy()
    src = np.where(np.isnan(H), 0, 1).astype(np.uint8)
    m = np.isnan(H) & ~np.isnan(b.a)
    H[m] = b.a[m]; src[m] = 2
    if np.isnan(H).any():
        jj, ii = np.nonzero(np.isnan(H))
        # z15 pixel centre -> z14 pixel coords
        gx = (ii + a.px0 + 0.5) / 2.0 - c.px0 - 0.5
        gy = (jj + a.py0 + 0.5) / 2.0 - c.py0 - 0.5
        ci = np.clip(np.round(gx).astype(int), 0, c.a.shape[1] - 1); cj = np.clip(np.round(gy).astype(int), 0, c.a.shape[0] - 1)
        H[jj, ii] = c.a[cj, ci]; src[jj, ii] = 3
    if np.isnan(H).any():
        from scipy.ndimage import distance_transform_edt
        nanm = np.isnan(H)
        idx = distance_transform_edt(nanm, return_distances=False, return_indices=True)
        H = H[tuple(idx)]; src[nanm] = 4
    return Mosaic(H, 15, a.px0, a.py0), src, [ia, ib, ic]
