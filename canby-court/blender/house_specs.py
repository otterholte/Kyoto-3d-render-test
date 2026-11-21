"""Per-house massing specs: roof 'wings' (overlapping rectangles) authored in each house's frame.

Authored by hand from the measured footprints (houses.json) and the observed roof forms on the 2022/2024
orthophotos (ridge directions, wings, garage positions). Everything vertical is INFERRED (no lidar):
  eave above floor = 2.85 m (1 storey), 3.3 m (1.5 storey knee wall), 5.6 m (2 storeys); pitch 6:12 default,
  5:12 low wings, 8:12 for the 2015 Craftsman, 9:12 for the 1.5-storey 3900.
Frame: origin = footprint centroid (houses.json), u axis at `frame` degrees (math, CCW from east), v = u + 90.
Wing: u0,u1,v0,v1 (m, frame coords) | roof: hip / gable (ridge along `ridge`: 'u' or 'v') / shed (high side
`high`: 'u0','u1','v0','v1') | st = storeys (1, 1.5, 2) | pitch = rise per 12 | dz = floor offset (split levels)
| world=(cx, cy, angle, L, W) to give a rectangle in world coords instead (wing in another orientation).
kind: 'main' (default), 'porch' (posts, no walls), 'dormer' (front wall + window, on a roof plane).
"""

EAVE = {1: 2.85, 1.5: 3.3, 2: 5.6}

SPECS = {
    3802: dict(frame=-29.25, pitch=6, wings=[
        dict(u=(-10.7, 12.9), v=(-7.7, 1.0), roof="hip", st=1),
        dict(u=(-10.7, -0.9), v=(-7.7, 10.8), roof="hip", st=1),
        dict(u=(2.4, 10.7), v=(-1.3, 6.0), roof="hip", st=1),
    ]),
    3803: dict(frame=1.7, pitch=6, wings=[
        dict(u=(-9.3, 7.0), v=(-6.0, 5.6), roof="gable", ridge="u", st=2),
        dict(u=(-2.4, 2.6), v=(3.0, 10.0), roof="gable", ridge="v", st=2),
        dict(u=(0.9, 8.9), v=(-8.4, -0.5), roof="gable", ridge="v", st=1, dz=-0.2),
        dict(u=(-7.2, -5.6), v=(-5.6, -3.4), roof="gable", ridge="v", st=2, kind="dormer", pitch=8),
        dict(u=(-3.6, -2.0), v=(-5.6, -3.4), roof="gable", ridge="v", st=2, kind="dormer", pitch=8),
        dict(u=(0.0, 1.6), v=(-5.6, -3.4), roof="gable", ridge="v", st=2, kind="dormer", pitch=8),
    ]),
    3806: dict(frame=-3.5, pitch=6, wings=[
        dict(u=(-8.9, 10.6), v=(-7.2, 4.8), roof="hip", st=2),
        dict(u=(-9.6, 0.1), v=(-1.3, 8.4), roof="hip", st=1.5, dz=-0.6),
        dict(u=(0.1, 3.3), v=(4.6, 6.7), roof="hip", st=1, pitch=5),
    ]),
    3807: dict(frame=-3.7, pitch=6, wings=[
        dict(u=(-11.4, 11.2), v=(-5.7, 5.7), roof="hip", st=2),
        dict(u=(-11.3, -2.5), v=(-5.7, 7.9), roof="hip", st=2),
        dict(u=(2.3, 11.2), v=(-8.2, 5.7), roof="hip", st=1.5, dz=-0.7),
    ]),
    3811: dict(frame=-4.0, pitch=6, wings=[
        dict(u=(-9.5, 6.3), v=(-4.7, 7.3), roof="gable", ridge="u", st=2),
        dict(u=(-4.4, 1.0), v=(-6.1, 7.3), roof="gable", ridge="v", st=2),
        dict(u=(1.0, 9.4), v=(-7.3, 1.7), roof="hip", st=1, dz=-0.2),
    ]),
    3813: dict(frame=0.0, pitch=8, wings=[
        dict(u=(-6.9, 6.6), v=(-7.0, 7.6), roof="hip", st=2),
        dict(u=(-6.9, -0.6), v=(-7.0, 2.0), roof="gable", ridge="v", st=2),
        dict(u=(0.0, 6.2), v=(-9.9, -8.0), roof="shed", high="v1", st=1, pitch=4, kind="porch"),
    ]),
    3900: dict(frame=17.5, pitch=9, wings=[
        dict(u=(-10.3, 9.4), v=(-4.7, 8.9), roof="gable", ridge="u", st=1.5),
        dict(u=(-6.6, 6.6), v=(-9.7, 2.0), roof="gable", ridge="v", st=1.5),
        dict(u=(6.6, 10.6), v=(-5.8, 1.4), roof="hip", st=1, pitch=6),
        dict(u=(-7.5, -5.5), v=(5.6, 8.4), roof="gable", ridge="v", st=1.5, kind="dormer", pitch=10),
        dict(u=(-3.5, -1.5), v=(5.6, 8.4), roof="gable", ridge="v", st=1.5, kind="dormer", pitch=10),
        dict(u=(0.5, 2.5), v=(5.6, 8.4), roof="gable", ridge="v", st=1.5, kind="dormer", pitch=10),
    ]),
    3904: dict(frame=-48.5, pitch=6, wings=[
        dict(u=(-7.8, 9.3), v=(-8.3, 9.3), roof="hip", st=1),
        dict(u=(-11.1, 10.2), v=(-8.3, -0.6), roof="hip", st=1),
    ]),
    3905: dict(frame=26.5, pitch=6, wings=[
        dict(u=(-6.6, 4.0), v=(-6.9, 7.6), roof="hip", st=2),                       # main 2-storey block
        dict(u=(-10.0, -6.3), v=(-6.9, 7.5), roof="shed", high="u1", st=1, pitch=3, eave=2.55),  # lower strip on the WSW face
        dict(u=(3.2, 7.8), v=(-5.1, 6.4), roof="hip", st=1, pitch=4, eave=2.6),     # low-slope NE section
        dict(u=(-1.0, 2.6), v=(6.0, 8.0), roof="hip", st=1, eave=2.6),              # hipped bay, north
        dict(world=(10.6, 1.6, -4.6, 8.6, 7.4), roof="gable", ridge="u", st=1, dz=-0.15),   # east garage wing
        dict(u=(-11.9, -10.0), v=(-1.4, 2.2), roof="gable", ridge="u", st=1, pitch=8, kind="porch"),  # entry porch
    ]),
    3909: dict(frame=3.0, pitch=6, wings=[
        dict(u=(-5.4, 7.1), v=(-5.5, 11.5), roof="gable", ridge="v", st=2),
        dict(world=(7.8, -32.1, 64.0, 9.7, 9.1), roof="gable", ridge="u", st=1, dz=-0.2),
    ]),
}
