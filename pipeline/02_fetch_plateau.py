"""Phase 2C: extract only mesh-52353692 members from the 2.7 GB Kyoto City PLATEAU 2025 CityGML zip."""
import os, sys
from remotezip import open_remote_zip
from common import RAW
URL = "https://assets.cms.plateau.reearth.io/assets/c8/4c6540-2bcf-4773-b21d-74ad2d9f1ba1/26100_kyoto-shi_city_2025_citygml_1_op.zip"
out = os.path.join(RAW, "plateau")
z = open_remote_zip(URL)
want = [i for i in z.infolist() if (
    i.filename in ("udx/bldg/52353692_bldg_6697_op.gml", "udx/tran/52353692_tran_6697_op.gml")
    or i.filename.startswith("udx/dem/523536_dem_6697_50")
    or (i.filename.startswith("udx/bldg/52353692_bldg_6697_appearance/") and not i.is_dir())
    or i.filename.startswith("codelists/Building_") or i.filename.startswith("codelists/BuildingDetail"))]
want.sort(key=lambda i: i.header_offset)  # sequential reads hit the range cache
for k, i in enumerate(want):
    dst = os.path.join(out, i.filename)
    if os.path.exists(dst) and os.path.getsize(dst) == i.file_size:
        continue
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    with z.open(i) as s, open(dst, "wb") as d:
        d.write(s.read())
    if k % 200 == 0 or i.file_size > 1e6:
        print(k, len(want), i.filename, i.file_size, flush=True)
print("done")
