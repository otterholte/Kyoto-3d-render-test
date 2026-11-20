"""Independent audit helpers (Phase 9). Does NOT import the builder's pipeline modules.

Transforms are created here from scratch:
  OSM (WGS84, EPSG:4326)            -> EPSG:6674
  PLATEAU / GSI (JGD2011, EPSG:6668) -> EPSG:6674
Local frame = EPSG:6674 minus the box centre that we re-derive in a1_boundary.py (and compare to the builder's).
"""
import glob
import json
import math
import os

import numpy as np
from lxml import etree
from pyproj import Transformer

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
RAW = os.path.join(ROOT, "data", "raw")
OUT = os.path.join(ROOT, "pipeline", "audit", "out")
os.makedirs(OUT, exist_ok=True)
T_OSM = Transformer.from_crs(4326, 6674, always_xy=True)
T_JGD = Transformer.from_crs(6668, 6674, always_xy=True)
T_INV = Transformer.from_crs(6674, 6668, always_xy=True)
# box centre used by the scene (verified independently in a1_boundary.py)
OE, ON = -20160.0, -111160.0


def osm_raw():
    """Parse the raw OSM XML with lxml (independent of pipeline/osm_parse.py)."""
    root = etree.parse(os.path.join(RAW, "osm", "osm_wide.osm")).getroot()
    nodes, ways, rels = {}, {}, {}
    for el in root:
        if el.tag == "node":
            lon, lat = float(el.get("lon")), float(el.get("lat"))
            nodes[int(el.get("id"))] = (lon, lat, {t.get("k"): t.get("v") for t in el.findall("tag")})
        elif el.tag == "way":
            ways[int(el.get("id"))] = ([int(n.get("ref")) for n in el.findall("nd")],
                                      {t.get("k"): t.get("v") for t in el.findall("tag")})
        elif el.tag == "relation":
            rels[int(el.get("id"))] = ([(m.get("type"), int(m.get("ref")), m.get("role")) for m in el.findall("member")],
                                      {t.get("k"): t.get("v") for t in el.findall("tag")})
    return nodes, ways, rels


def osm_xy(nodes, ids):
    ll = np.array([nodes[i][:2] for i in ids if i in nodes], float)
    e, n = T_OSM.transform(ll[:, 0], ll[:, 1])
    return np.c_[np.asarray(e) - OE, np.asarray(n) - ON]


def jgd_xy(lon, lat):
    e, n = T_JGD.transform(np.asarray(lon), np.asarray(lat))
    return np.asarray(e) - OE, np.asarray(n) - ON


def gsi_fgd(cls):
    """All GSI experimental_fgd z18 features of a class, de-duplicated by fid+geometry, in local xy."""
    seen, out = set(), []
    for f in sorted(glob.glob(os.path.join(RAW, "gsi", "experimental_fgd", "18", "*", "*.geojson"))):
        for ft in json.load(open(f))["features"]:
            p = ft["properties"]
            if p.get("class") != cls:
                continue
            g = ft["geometry"]
            key = (p.get("fid"), json.dumps(g["coordinates"]))
            if key in seen:
                continue
            seen.add(key)
            c = np.array(g["coordinates"], float).reshape(-1, 2)
            x, y = jgd_xy(c[:, 0], c[:, 1])
            out.append(dict(fid=p.get("fid"), type=p.get("type"), alti=p.get("alti"), lvl=p.get("orgGILvl"),
                            xy=np.c_[x, y], gtype=g["type"]))
    return out


def dem5a_points():
    """GSI DEM5A z15 text tiles -> (x, y, z) pixel centres in local frame (independent decode)."""
    pts = []
    for f in glob.glob(os.path.join(RAW, "gsi", "dem5a", "15", "*", "*.txt")):
        tx = int(f.split(os.sep)[-2]); ty = int(os.path.basename(f).split(".")[0])
        rows = open(f).read().strip().split("\n")
        z = 15
        for py, row in enumerate(rows):
            for px, v in enumerate(row.split(",")):
                v = v.strip()
                if v in ("e", ""):
                    continue
                gx = (tx * 256 + px + 0.5) / (256 * 2 ** z)
                gy = (ty * 256 + py + 0.5) / (256 * 2 ** z)
                lon = gx * 360 - 180
                lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * gy))))
                pts.append((lon, lat, float(v)))
    a = np.array(pts)
    x, y = jgd_xy(a[:, 0], a[:, 1])
    return np.c_[x, y, a[:, 2]]


def save(name, obj):
    with open(os.path.join(OUT, name), "w") as f:
        json.dump(obj, f, indent=1, ensure_ascii=False, default=lambda o: o.tolist() if hasattr(o, "tolist") else str(o))
