"""A4 prep: PLATEAU DEM TIN (mesh 52353692 only) and DEM5A pixels in the box -> out/dem_ref.npz
Also builds the sample point list (random DEM5A pixels, random TIN points, GSI ElevPt, contour points)."""
import os
import numpy as np
from lxml import etree
from acommon import RAW, OUT, jgd_xy, dem5a_points, gsi_fgd

path = os.path.join(RAW, "plateau", "udx", "dem", "523536_dem_6697_50_op.gml")
G = "{http://www.opengis.net/gml}"
tris = []
for ev, el in etree.iterparse(path, events=("end",), tag="{*}ReliefFeature", huge_tree=True):
    name = el.findtext(G + "name")
    if name in ("52353692", "52354602", "52353682", "52353691", "52353693"):
        for pl in el.iter(G + "posList"):
            v = np.array(pl.text.split(), float).reshape(-1, 3)[:3]
            tris.append(v)
    el.clear()
    while el.getprevious() is not None:
        del el.getparent()[0]
T = np.array(tris)  # (n, 3, 3) lat lon h
x, y = jgd_xy(T[:, :, 1].ravel(), T[:, :, 0].ravel())
T = np.stack([x.reshape(-1, 3), y.reshape(-1, 3), T[:, :, 2]], axis=-1)
keep = (np.abs(T[:, :, 0]).max(1) < 230) & (np.abs(T[:, :, 1]).max(1) < 230)
T = T[keep]
D = dem5a_points()
D = D[(np.abs(D[:, 0]) < 230) & (np.abs(D[:, 1]) < 230)]
np.savez_compressed(os.path.join(OUT, "dem_ref.npz"), tin=T, dem5a=D)
print("tin triangles", len(T), "dem5a pts", len(D))
