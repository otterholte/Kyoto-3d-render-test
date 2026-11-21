"""Shared constants / helpers for the Canby Court pipeline.

CRS: NAD83(2011) / UTM zone 10N (EPSG:6339), metres.
Local origin: the 3905 Canby Ct address point projected to EPSG:6339, rounded
to the metre (see ORIGIN_E / ORIGIN_N).  Local x = E - ORIGIN_E (east),
local y = N - ORIGIN_N (north), z = NAVD88 metres (absolute; terrain.json
gives the z offset used by the scene).
"""
from pathlib import Path
import json
import time

import requests
from pyproj import Transformer

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
PROC = ROOT / "data" / "processed"
DOCS = ROOT / "docs"

CRS = "EPSG:6339"
# Fetch / context bbox (lon/lat WGS84) — generous so neighbours + street entrance are covered
FETCH_BBOX = (-122.4700, 48.7210, -122.4630, 48.7255)

# Origin = 3905 Canby Ct address point (city layer DD_LAT/DD_Long) in EPSG:6339, rounded.
ADDR_3905 = (-122.4653697, 48.72334394)

TO_UTM = Transformer.from_crs("EPSG:4326", CRS, always_xy=True)
TO_LL = Transformer.from_crs(CRS, "EPSG:4326", always_xy=True)
_e, _n = TO_UTM.transform(*ADDR_3905)
ORIGIN_E = round(_e)
ORIGIN_N = round(_n)

# Never persist any of these (privacy rule: no owner / taxpayer / person names)
BANNED_FIELD_SUBSTR = ("OWNER", "TAXPAYER", "TITLE_OWNER", "OWNERCS", "FULLTAXADDR",
                       "FULLOWNERADDR", "NAME_", "CREATED_US", "LAST_EDITE", "CREATED_USER",
                       "LAST_EDITED_USER", "SUBDIVISION", "LEGAL_DESC", )

CANBY_ADDRS = [3802, 3803, 3806, 3807, 3811, 3813, 3900, 3904, 3905, 3909]

UA = {"User-Agent": "canby-court-3d-research/0.1 (non-commercial)"}


def to_local(lon, lat):
    e, n = TO_UTM.transform(lon, lat)
    return e - ORIGIN_E, n - ORIGIN_N


def local_to_ll(x, y):
    return TO_LL.transform(x + ORIGIN_E, y + ORIGIN_N)


def get(url, params=None, tries=4, timeout=90, stream=False):
    for i in range(tries):
        try:
            r = requests.get(url, params=params, headers=UA, timeout=timeout, stream=stream)
            if r.status_code == 200:
                return r
            print("HTTP", r.status_code, url)
        except requests.RequestException as ex:
            print("retry", i, ex)
        time.sleep(2 * (i + 1))
    raise RuntimeError(f"failed: {url}")


def scrub(props):
    """Drop any field that could carry a person's name."""
    out = {}
    for k, v in props.items():
        ku = k.upper()
        if any(b in ku for b in BANNED_FIELD_SUBSTR):
            continue
        out[k] = v
    return out


def dump(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=1))
    return path
