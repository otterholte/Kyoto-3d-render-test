"""Shared geodesy + project constants.

CRS decisions (see docs/boundary.md):
  * Source geographic CRS: WGS84 (EPSG:4326, OSM) / JGD2011 geographic (EPSG:6668 / 6697 PLATEAU, GSI).
    WGS84 and JGD2011 differ by < 1 m in Japan; treated as identical (documented).
  * Projected working CRS: JGD2011 / Japan Plane Rectangular CS VI  (EPSG:6674)
    -- the official zone for Kyoto Prefecture. Units: metres. X(northing) / Y(easting)
       in Japanese survey convention; pyproj with always_xy returns (easting, northing).
  * Local scene frame: origin = BOX_ORIGIN_E/N (centre of the 400 m box, in EPSG:6674),
    x = east, y = north, z = orthometric height (JGD2011 vertical, T.P. metres).
    Blender: 1 unit = 1 m, +X east, +Y north, +Z up.
    Three.js : x = east, y = up, z = -north.
"""
import json
import os
from pyproj import Transformer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, "data", "raw")
PROC = os.path.join(ROOT, "data", "processed")

EPSG_PROJ = 6674
_to_proj = Transformer.from_crs(4326, EPSG_PROJ, always_xy=True)
_to_geo = Transformer.from_crs(EPSG_PROJ, 4326, always_xy=True)


def ll2en(lon, lat):
    """lon/lat (deg) -> easting/northing in EPSG:6674 (m)."""
    return _to_proj.transform(lon, lat)


def en2ll(e, n):
    return _to_geo.transform(e, n)


def load_boundary():
    with open(os.path.join(PROC, "boundary.json")) as f:
        return json.load(f)


def local(e, n, b=None):
    b = b or load_boundary()
    return e - b["origin_e"], n - b["origin_n"]
