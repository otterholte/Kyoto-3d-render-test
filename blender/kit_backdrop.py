"""Distant landscape backdrop from GSI DEM10B (outside the 600 m terrain grid).

Near ring  : DEM10B z13 tiles, 25 m mesh, |x|,|y| <= 2.5 km (hole over the detailed terrain)
Far ring   : DEM10B z11 tiles, 120 m mesh, |x|,|y| <= 15 km (hole over the near ring)
Elevations are real (GSI DEM10B, 出典: 国土地理院); land cover is painted (forest on slopes/hills, an
impressionistic city texture in the basin) -> collection 90_Backdrop_Outside_Boundary, artistic land cover.
Earth curvature drop d^2/2R is applied.
"""
import math
import os

import bpy
import numpy as np
import requests

from kit_common import ROOT, mesh_obj, get_coll
from kit_materials import new_mat, node, link, sep, comb, math as mth, mrange, mix, principled, brush, paint, vmath

RAW = os.path.join(ROOT, "data", "raw", "gsi", "dem10b")
LAT0, LON0 = 34.9978039, 135.7791449
UA = {"User-Agent": "higashiyama-reconstruction/1.0 (open data)"}


def _tile(lon, lat, z):
    n = 2 ** z
    lat = np.radians(lat)
    x = (np.asarray(lon) + 180) / 360 * n
    y = (1 - np.log(np.tan(lat) + 1 / np.cos(lat)) / math.pi) / 2 * n
    return x, y


def _fetch(z, x, y):
    p = os.path.join(RAW, str(z), str(x), "%d.txt" % y)
    if not os.path.exists(p):
        os.makedirs(os.path.dirname(p), exist_ok=True)
        r = requests.get("https://cyberjapandata.gsi.go.jp/xyz/dem/%d/%d/%d.txt" % (z, x, y), headers=UA, timeout=60)
        if r.status_code != 200:
            return None
        open(p, "w").write(r.text)
    rows = [[float(v) if v not in ("e", "") else np.nan for v in ln.split(",")] for ln in open(p).read().strip().splitlines()]
    return np.array(rows)


def sampler(z, half_km):
    """Return f(lon, lat) -> elevation using bilinear sampling of z-level DEM10B tiles."""
    from pyproj import Transformer
    tr = Transformer.from_crs(6674, 4326, always_xy=True)
    lonA, latA = tr.transform(-20160.0 - half_km * 1000, -111160.0 - half_km * 1000)
    lonB, latB = tr.transform(-20160.0 + half_km * 1000, -111160.0 + half_km * 1000)
    x0, y1 = _tile(lonA, latA, z); x1, y0 = _tile(lonB, latB, z)
    tx0, tx1, ty0, ty1 = int(x0), int(x1), int(y0), int(y1)
    W = (tx1 - tx0 + 1) * 256; H = (ty1 - ty0 + 1) * 256
    big = np.full((H, W), np.nan)
    for tx in range(tx0, tx1 + 1):
        for ty in range(ty0, ty1 + 1):
            a = _fetch(z, tx, ty)
            if a is not None and a.shape == (256, 256):
                big[(ty - ty0) * 256:(ty - ty0 + 1) * 256, (tx - tx0) * 256:(tx - tx0 + 1) * 256] = a
    big = np.where(np.isnan(big), 0.0, big)   # sea/no-data -> 0 (none expected inland)

    def f(lon, lat):
        px, py = _tile(lon, lat, z)
        fx = (px - tx0) * 256 - 0.5; fy = (py - ty0) * 256 - 0.5
        fx = np.clip(fx, 0, W - 1.001); fy = np.clip(fy, 0, H - 1.001)
        i = fx.astype(int); j = fy.astype(int); u = fx - i; v = fy - j
        return big[j, i] * (1 - u) * (1 - v) + big[j, i + 1] * u * (1 - v) + big[j + 1, i] * (1 - u) * v + big[j + 1, i + 1] * u * v
    return f


def grid(name, f, half, step, hole, coll, mat):
    from pyproj import Transformer
    tr = Transformer.from_crs(6674, 4326, always_xy=True)
    xs = np.arange(-half, half + step / 2, step)
    GX, GY = np.meshgrid(xs, xs)
    lon, lat = tr.transform(GX + -20160.0, GY + -111160.0)
    Z = f(np.asarray(lon), np.asarray(lat))
    Z = Z - (GX ** 2 + GY ** 2) / (2 * 6371000.0) - 0.6
    n = len(xs)
    idx = np.arange(n * n).reshape(n, n)
    F = []
    for j in range(n - 1):
        for i in range(n - 1):
            cx = (xs[i] + xs[i + 1]) / 2; cy = (xs[j] + xs[j + 1]) / 2
            if abs(cx) < hole and abs(cy) < hole:
                continue
            F.append((idx[j, i], idx[j, i + 1], idx[j + 1, i + 1], idx[j + 1, i]))
    V = np.c_[GX.ravel(), GY.ravel(), Z.ravel()]
    ob = mesh_obj(name, V, F, coll, [mat], smooth=True)
    ob["source"] = "GSI DEM10B (出典: 国土地理院) z-level tiles; land cover painted (artistic)"
    ob["artistic"] = True
    ob["exclude_web"] = True
    return ob


def m_farland():
    m, nt, out = new_mat("ART_Far_Land")
    geo = node(nt, "ShaderNodeNewGeometry")
    P, N = geo.outputs["Position"], geo.outputs["Normal"]
    x, y, z = sep(nt, P)
    nz = sep(nt, N)[2]
    dist = vmath(nt, "LENGTH", comb(nt, x, y, 0.0))
    hill = mth(nt, "MAXIMUM", mrange(nt, z, 70.0, 110.0), mrange(nt, nz, 0.985, 0.94))
    # forest: dark evergreen mottled with autumn maples
    fz = node(nt, "ShaderNodeTexNoise", {"Vector": P, "Scale": 0.03, "Detail": 4.0}).outputs["Factor"]
    forest = mix(nt, mrange(nt, fz, 0.45, 0.75), (0.035, 0.055, 0.025), (0.09, 0.08, 0.03))
    az = node(nt, "ShaderNodeTexNoise", {"Vector": P, "Scale": 0.09, "Detail": 2.0}).outputs["Factor"]
    forest = mix(nt, mrange(nt, az, 0.6, 0.72, 0.0, 0.7), forest, (0.32, 0.08, 0.02))
    # city: small blocks of roofs, grey-brown
    cv = node(nt, "ShaderNodeTexVoronoi", {"Vector": P, "Scale": 0.07}, feature="F1", distance="CHEBYCHEV").outputs["Color"]
    city = mix(nt, sep(nt, cv)[0], (0.10, 0.10, 0.11), (0.30, 0.28, 0.26))
    c = mix(nt, hill, city, forest)
    f1, f2 = brush(nt, P, 0.012, (1, 1, 1))
    c = paint(nt, c, f1, f2, 0.18, 0.02)
    # atmospheric perspective baked into the albedo + emission so far hills read as soft silhouettes
    haze = mrange(nt, dist, 300.0, 12000.0, 0.15, 0.9)
    b = principled(nt, None, c, 0.95, 0.2)
    # blue-hour city lights in the basin (artistic): sparse warm specks
    cl = nt.nodes.new("ShaderNodeValue"); cl.name = "CityLights"; cl.outputs[0].default_value = 0.0
    sp = node(nt, "ShaderNodeTexVoronoi", {"Vector": P, "Scale": 0.045, "Randomness": 1.0}, feature="F1")
    spec = mth(nt, "MULTIPLY", mrange(nt, sp.outputs["Distance"], 0.12, 0.04), mrange(nt, sep(nt, sp.outputs["Color"])[0], 0.45, 0.5))
    spec = mth(nt, "MULTIPLY", spec, mth(nt, "SUBTRACT", 1.0, hill))
    em2 = node(nt, "ShaderNodeEmission", {"Color": (1.0, 0.62, 0.32, 1)})
    link(nt, mth(nt, "MULTIPLY", spec, mth(nt, "MULTIPLY", cl.outputs[0], 8.0)), em2.inputs["Strength"])
    add = node(nt, "ShaderNodeAddShader", {0: b.outputs[0], 1: em2.outputs[0]})
    # aerial perspective: blend toward a per-preset haze colour (node "FarHaze") with distance
    hz = nt.nodes.new("ShaderNodeRGB"); hz.name = "FarHaze"; hz.outputs[0].default_value = (0.6, 0.52, 0.52, 1)
    em = node(nt, "ShaderNodeEmission", {"Strength": 1.0})
    link(nt, hz.outputs[0], em.inputs["Color"])
    add2 = node(nt, "ShaderNodeMixShader", {0: mth(nt, "MULTIPLY", haze, 0.8), 1: add.outputs[0], 2: em.outputs[0]})
    link(nt, add2.outputs[0], out.inputs["Surface"])
    return m


def build(log=print):
    coll = get_coll("90_Backdrop_Outside_Boundary")
    mat = m_farland()
    try:
        fn = sampler(13, 2.6)
        ff = sampler(11, 15.5)
    except Exception as ex:
        log("backdrop DEM fetch failed:", ex)
        return None
    a = grid("Backdrop_DEM10B_near", fn, 2500.0, 25.0, 290.0, coll, mat)
    b = grid("Backdrop_DEM10B_far", ff, 15000.0, 120.0, 2440.0, coll, mat)
    b.location.z = -1.5
    log("backdrop", len(a.data.vertices), len(b.data.vertices))
    return a, b
