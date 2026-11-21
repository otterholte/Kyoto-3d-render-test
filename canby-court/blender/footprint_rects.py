"""Footprint -> overlapping maximal rectangles (roof 'wings'), no bpy.

The union of hip/gable roof solids over OVERLAPPING maximal rectangles reproduces the valleys of an L/T/U-plan
roof (the visible roof is the upper envelope of the wing roofs). Rectangles are searched in one or more house
frames (angles) on the snapped vertex coordinates of the footprint, keeping those >= `min_inside` inside the
footprint, then chosen greedily by newly covered area.
"""
import math

import numpy as np
import shapely
from shapely.geometry import Polygon, box
from shapely import affinity


def _cluster(vals, tol):
    vals = np.sort(np.asarray(vals))
    out = [[vals[0]]]
    for v in vals[1:]:
        if v - out[-1][-1] <= tol:
            out[-1].append(v)
        else:
            out.append([v])
    return [float(np.mean(g)) for g in out]


def dominant_angles(pts, n=2, tol_deg=8):
    p = np.asarray(pts)
    d = np.diff(np.vstack([p, p[:1]]), axis=0)
    L = np.hypot(d[:, 0], d[:, 1])
    a = np.degrees(np.arctan2(d[:, 1], d[:, 0])) % 90
    hist = np.zeros(90)
    for ai, li in zip(a, L):
        for k in range(-3, 4):
            hist[int(round(ai + k)) % 90] += li * math.exp(-k * k / 4)
    out = []
    for _ in range(n):
        i = int(np.argmax(hist))
        if hist[i] < 0.2 * hist.max() if out else False:
            break
        out.append(float(i))
        for k in range(-int(tol_deg) * 2, int(tol_deg) * 2 + 1):
            hist[(i + k) % 90] = 0
    return out


def decompose(pts, angles, min_side=2.2, min_inside=0.94, snap=0.35, min_gain=3.0, max_rects=8):
    P = Polygon(pts).buffer(0)
    cx, cy = P.centroid.x, P.centroid.y
    cands = []
    for ang in angles:
        Q = affinity.rotate(P, -ang, origin=(cx, cy))
        xs = _cluster([c[0] for c in Q.exterior.coords], snap)
        ys = _cluster([c[1] for c in Q.exterior.coords], snap)
        boxes = []
        for i in range(len(xs)):
            for j in range(i + 1, len(xs)):
                if xs[j] - xs[i] < min_side:
                    continue
                for k in range(len(ys)):
                    for l in range(k + 1, len(ys)):
                        if ys[l] - ys[k] < min_side:
                            continue
                        boxes.append((xs[i], ys[k], xs[j], ys[l]))
        if not boxes:
            continue
        B = shapely.box(*np.array(boxes).T)
        inside = shapely.area(shapely.intersection(B, Q)) / shapely.area(B)
        for b, f in zip(boxes, inside):
            if f >= min_inside:
                world = affinity.rotate(box(*b), ang, origin=(cx, cy))
                cands.append((ang, b, world))
    chosen = []
    covered = Polygon()
    total = P.area
    for _ in range(max_rects):
        best, bg = None, 0
        for c in cands:
            g = c[2].intersection(P).difference(covered).area
            if g > bg:
                best, bg = c, g
        if best is None or bg < max(min_gain, 0.03 * total):
            break
        chosen.append(best)
        covered = covered.union(best[2].intersection(P))
    rects = []
    for ang, b, world in chosen:
        x0, y0, x1, y1 = b
        c_local = ((x0 + x1) / 2, (y0 + y1) / 2)
        # back to world centre
        a = math.radians(ang)
        dx, dy = c_local[0] - cx, c_local[1] - cy
        wx = cx + dx * math.cos(a) - dy * math.sin(a)
        wy = cy + dx * math.sin(a) + dy * math.cos(a)
        rects.append({"c": [round(wx, 3), round(wy, 3)], "a": ang, "L": round(x1 - x0, 3), "W": round(y1 - y0, 3)})
    return rects, 1 - P.difference(covered).area / total


def rect_poly(r, grow=0.0):
    a = math.radians(r["a"])
    u = np.array([math.cos(a), math.sin(a)])
    v = np.array([-math.sin(a), math.cos(a)])
    c = np.array(r["c"])
    hl, hw = r["L"] / 2 + grow, r["W"] / 2 + grow
    return [tuple(c - u * hl - v * hw), tuple(c + u * hl - v * hw), tuple(c + u * hl + v * hw),
            tuple(c - u * hl + v * hw)]
