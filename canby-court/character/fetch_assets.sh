#!/usr/bin/env bash
# Fetch the CC0 MakeHuman source assets used by build_character.py into ./_mh_cache
# (not committed: ~35 MB). Pinned to exact upstream revisions.
set -euo pipefail
cd "$(dirname "$0")"
C=_mh_cache; mkdir -p $C
MH=a8bc2d54ff0ac92e78ff71431b1023eda42bf482      # makehumancommunity/makehuman master
MPFB=9de0707fdc88438d7c53a1a2ac7937d9221e2431    # makehumancommunity/mpfb2 master
R=https://raw.githubusercontent.com/makehumancommunity
get() { [ -s "$C/$2" ] || { mkdir -p "$(dirname "$C/$2")"; curl -sSfL "$1" -o "$C/$2"; }; }
get $R/mpfb2/$MPFB/src/mpfb/data/3dobjs/base.obj base.obj
get $R/mpfb2/$MPFB/src/mpfb/data/rigs/standard/rig.game_engine.json rig.game_engine.json
get $R/mpfb2/$MPFB/src/mpfb/data/rigs/standard/weights.game_engine.json weights.game_engine.json
get $R/mpfb2/$MPFB/src/mpfb/data/mesh_metadata/basemesh_vertex_groups.json basemesh_vertex_groups.json
get $R/mpfb2/$MPFB/LICENSE.ASSETS.md LICENSE.ASSETS.md
get $R/makehuman/$MH/makehuman/data/eyes/high-poly/high-poly.obj eyes/high-poly.obj
get $R/makehuman/$MH/makehuman/data/eyes/high-poly/high-poly.mhclo eyes/high-poly.mhclo
get $R/makehuman/$MH/makehuman/data/eyes/low-poly/low-poly.obj eyes/low-poly.obj
get $R/makehuman/$MH/makehuman/data/eyes/low-poly/low-poly.mhclo eyes/low-poly.mhclo
get $R/makehuman/$MH/makehuman/data/eyes/materials/brown_eye.png eyes/brown_eye.png
# compiled morph targets (targets.npz) ship inside the makehuman 1.3.2 wheel on PyPI
if [ ! -s $C/targets.npz ]; then
  W=https://files.pythonhosted.org/packages/52/7b/d3d997e4b8ee3b16af4d5e9ff5994af82c6467db18fa50e535bb057ff077/makehuman-1.3.2-py3-none-any.whl
  curl -sSfL $W -o $C/mh.whl
  unzip -p $C/mh.whl makehuman/data/targets.npz > $C/targets.npz
  rm $C/mh.whl
fi
ls -la $C
