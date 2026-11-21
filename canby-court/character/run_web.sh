#!/usr/bin/env bash
# export_web.py + glTF post-processing (meshopt, WebP) -> ../web/assets/
set -euo pipefail
cd "$(dirname "$0")"
NODE_MODULES=${NODE_MODULES:-$(pwd)/tools/node_modules}
/home/user/venv/bin/python export_web.py
NODE_PATH=$NODE_MODULES node tools/optimize_glb.cjs textures/web/character_raw.glb ../web/assets/character.glb 1024
NODE_PATH=$NODE_MODULES node tools/optimize_glb.cjs textures/web/sled_raw.glb ../web/assets/sled.glb 512
ls -la ../web/assets/
