// Distant backdrop (backdrop agent): real Kyoto city massing + Higashiyama hills beyond the 400 m box.
// Loaded after the walk has started (never blocks it); render only: no collision, no shadow casting,
// fog / aerial perspective applied through the shared height-fog + atmosphere patch.
import * as THREE from 'three';
import { loadGLB } from './world.js';
import { patchAtmosTree } from './pbr.js';

export async function loadBackdrop(scene, manifest) {
  if (!manifest || !manifest.backdrop) return null;
  const ver = manifest.generated ? '?v=' + encodeURIComponent(manifest.generated) : '';
  const gltf = await loadGLB('dist/' + manifest.backdrop.file + ver);
  const root = gltf.scene;
  root.name = 'Backdrop';
  let tris = 0;
  root.traverse((o) => {
    if (!o.isMesh) return;
    o.castShadow = false;
    o.receiveShadow = false;
    o.userData.noAO = true;                 // far geometry: AO pre-pass would only cost time
    const mats = Array.isArray(o.material) ? o.material : [o.material];
    for (const m of mats) {
      if (!o.geometry.attributes.normal && !m.flatShading) { m.flatShading = true; m.needsUpdate = true; }
      if ('envMapIntensity' in m) m.envMapIntensity = 0.6;
    }
    tris += (o.geometry.index ? o.geometry.index.count : o.geometry.attributes.position.count) / 3;
  });
  root.updateMatrixWorld(true);
  root.traverse((o) => { if (o.isMesh) { o.matrixAutoUpdate = false; } });
  patchAtmosTree(root);
  scene.add(root);
  return { root, tris: Math.round(tris), box: new THREE.Box3().setFromObject(root) };
}
