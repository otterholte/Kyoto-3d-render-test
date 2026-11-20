"""Backdrop helper: stream PLATEAU 2025 Kyoto CityGML members straight out of the remote 2.7 GB zip
(HTTP Range, see remotezip.py) and keep only what the distant backdrop needs.

  bldg  -> per 3rd-order mesh cache  data/raw/plateau/backdrop/bldg_<mesh>.npz
           LOD1 prisms (bottom ring in local x/y, z bottom/top as surveyed), attributes,
           LOD2 Roof/Wall triangles for buildings within LOD2_RADIUS of the box centre
  luse  -> per 2nd-order mesh cache  data/raw/plateau/backdrop/luse_<mesh>.npz
           land-use polygons (exterior rings, local x/y) + uro:LandUse class code

Usage: python backdrop_plateau.py bldg 52353670 52353671 ...   |   python backdrop_plateau.py luse 523536 523546
Nothing is written outside data/raw/plateau/backdrop/ (git-ignored with the rest of data/raw/plateau/).
"""
import io
import json
import os
import sys

import mapbox_earcut as earcut
import numpy as np
from lxml import etree

from common import RAW, load_boundary, ll2en
from remotezip import open_remote_zip

URL = "https://assets.cms.plateau.reearth.io/assets/c8/4c6540-2bcf-4773-b21d-74ad2d9f1ba1/26100_kyoto-shi_city_2025_citygml_1_op.zip"
CACHE = os.path.join(RAW, "plateau", "backdrop")
LOD2_RADIUS = 1300.0      # m from the box centre; LOD2 roofs/walls kept inside, LOD1 prisms everywhere
G = "{http://www.opengis.net/gml}"
B = "{http://www.opengis.net/citygml/building/2.0}"
_bnd = load_boundary()
OE, ON = _bnd["origin_e"], _bnd["origin_n"]


def _ll(txt):
    v = np.array(txt.split(), dtype=np.float64).reshape(-1, 3)   # lat lon h
    return v


def _to_local(lat, lon):
    e, n = ll2en(lon, lat)
    return np.asarray(e) - OE, np.asarray(n) - ON


def _tri(r):
    """Triangulate a planar 3-D ring (closed or not) -> (verts, tris)."""
    if len(r) > 3 and np.allclose(r[0], r[-1]):
        r = r[:-1]
    if len(r) < 3:
        return None
    nrm = np.zeros(3)
    for i in range(len(r)):
        a, c = r[i], r[(i + 1) % len(r)]
        nrm += [(a[1] - c[1]) * (a[2] + c[2]), (a[2] - c[2]) * (a[0] + c[0]), (a[0] - c[0]) * (a[1] + c[1])]
    ax = int(np.argmax(np.abs(nrm)))
    p2 = np.delete(r, ax, axis=1).astype(np.float64)
    try:
        idx = np.asarray(earcut.triangulate_float64(p2, np.array([len(p2)], np.uint32)), int).reshape(-1, 3)
    except Exception:
        return None
    return r[idx] if len(idx) else None


def member_stream(z, name):
    return z.open(name)


def parse_bldg(z, mesh):
    name = "udx/bldg/%s_bldg_6697_op.gml" % mesh
    local_file = os.path.join(RAW, "plateau", "udx", "bldg", "%s_bldg_6697_op.gml" % mesh)
    src = open(local_file, "rb") if os.path.exists(local_file) else member_stream(z, name)
    recs, rings, lod2 = [], [], []          # rings: (bi, part, lat, lon, h) ; lod2: (bi, kind, verts lat/lon/h)
    for _, el in etree.iterparse(src, events=("end",), tag=B + "Building", huge_tree=True):
        gid = el.get(G + "id")
        rec = dict(id=gid, name=el.findtext(G + "name"), usage=el.findtext(B + "usage"),
                   cls=el.findtext(B + "class"),
                   height=float(el.findtext(B + "measuredHeight") or "nan"),
                   storeys=int(el.findtext(B + "storeysAboveGround") or 0))
        bi = len(recs)
        nparts = 0
        for solid in el.iter(B + "lod1Solid"):
            polys = [_ll(p.text) for p in solid.iter(G + "posList")]
            if not polys:
                continue
            zmin = min(p[:, 2].min() for p in polys); zmax = max(p[:, 2].max() for p in polys)
            bot = [p for p in polys if np.ptp(p[:, 2]) < 0.01 and abs(p[0, 2] - zmin) < 0.01]
            ring = max(bot, key=len) if bot else polys[0]
            rings.append((bi, nparts, ring, zmin, zmax))
            nparts += 1
        if nparts == 0:
            el.clear()
            continue
        recs.append(rec)
        # LOD2 surfaces, only near the box (cheap enough there; the far city stays LOD1)
        r0 = rings[-1][2]
        cx, cy = _to_local(r0[:, 0].mean(), r0[:, 1].mean())
        if float(np.hypot(cx, cy)) < LOD2_RADIUS:
            for kind, tag in ((0, "RoofSurface"), (1, "WallSurface")):
                for surf in el.iter(B + tag):
                    for pl in surf.iter(G + "posList"):
                        lod2.append((bi, kind, _ll(pl.text)))
        el.clear()
        while el.getprevious() is not None:
            del el.getparent()[0]
    src.close()
    # ---- vectorised transform + pack
    if not recs:
        return None
    allr = np.concatenate([r[2] for r in rings])
    x, y = _to_local(allr[:, 0], allr[:, 1])
    xy = np.c_[x, y].astype(np.float32)
    lens = np.array([len(r[2]) for r in rings])
    off = np.r_[0, np.cumsum(lens)]
    out = dict(ring_xy=xy, ring_off=off.astype(np.int64), ring_bld=np.array([r[0] for r in rings], np.int32),
               ring_zmin=np.array([r[3] for r in rings], np.float32), ring_zmax=np.array([r[4] for r in rings], np.float32))
    tv, tk, tb = [], [], []
    if lod2:
        allp = np.concatenate([p for _, _, p in lod2])
        lx, ly = _to_local(allp[:, 0], allp[:, 1])
        P = np.c_[lx, ly, allp[:, 2]]
        o = 0
        for bi, kind, p in lod2:
            t = _tri(P[o:o + len(p)])
            o += len(p)
            if t is not None:
                tv.append(t); tk += [kind] * len(t); tb += [bi] * len(t)
    out["lod2_tri"] = (np.concatenate(tv).astype(np.float32) if tv else np.zeros((0, 3, 3), np.float32))
    out["lod2_kind"] = np.array(tk, np.uint8)
    out["lod2_bld"] = np.array(tb, np.int32)
    out["meta"] = np.array(json.dumps(dict(mesh=mesh, member=name, buildings=recs), ensure_ascii=False))
    return out


def parse_luse(z, mesh2):
    name = "udx/luse/%s_luse_6697_op.gml" % mesh2
    src = member_stream(z, name)
    rings, cls = [], []
    for _, el in etree.iterparse(src, events=("end",), huge_tree=True):
        t = el.tag
        if not (isinstance(t, str) and t.endswith("}LandUse")):
            continue
        code = None
        for c in el:
            if isinstance(c.tag, str) and c.tag.endswith("}class"):
                code = (c.text or "").strip()
        for poly in el.iter(G + "Polygon"):
            ext = poly.find(".//" + G + "exterior//" + G + "posList")
            if ext is not None:
                rings.append(_ll(ext.text)); cls.append(code)
        el.clear()
        while el.getprevious() is not None:
            del el.getparent()[0]
    src.close()
    allr = np.concatenate(rings)
    x, y = _to_local(allr[:, 0], allr[:, 1])
    lens = np.array([len(r) for r in rings])
    codes = sorted(set(c or "" for c in cls))
    return dict(ring_xy=np.c_[x, y].astype(np.float32), ring_off=np.r_[0, np.cumsum(lens)].astype(np.int64),
                ring_cls=np.array([codes.index(c or "") for c in cls], np.int16),
                meta=np.array(json.dumps(dict(mesh=mesh2, member=name, codes=codes))))


def main(kind, meshes):
    os.makedirs(CACHE, exist_ok=True)
    z = None
    for m in meshes:
        dst = os.path.join(CACHE, "%s_%s.npz" % (kind, m))
        if os.path.exists(dst):
            print("cached", dst, flush=True)
            continue
        if z is None:
            z = open_remote_zip(URL)
            names = set(z.namelist())
        member = ("udx/bldg/%s_bldg_6697_op.gml" if kind == "bldg" else "udx/luse/%s_luse_6697_op.gml") % m
        if member not in names:
            print("absent in zip", member, flush=True)
            np.savez_compressed(dst, absent=np.array(True))
            continue
        out = parse_bldg(z, m) if kind == "bldg" else parse_luse(z, m)
        if out is None:
            np.savez_compressed(dst, absent=np.array(True)); continue
        np.savez_compressed(dst, **out)
        print("done", kind, m, {k: v.shape for k, v in out.items() if k != "meta"}, flush=True)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2:])
