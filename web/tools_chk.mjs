import { NodeIO } from '@gltf-transform/core';
import { ALL_EXTENSIONS } from '@gltf-transform/extensions';
import { MeshoptDecoder } from 'meshoptimizer';
await MeshoptDecoder.ready;
const io = new NodeIO().registerExtensions(ALL_EXTENSIONS).registerDependencies({ 'meshopt.decoder': MeshoptDecoder });
const doc = await io.read('dist/world_art.glb');
for (const n of doc.getRoot().listNodes()) {
  const ex = n.getExtras();
  if (!ex.members) continue;
  const k = ex.members.findIndex((m) => m.name === 'B_2c931dc7');
  if (k < 0) continue;
  const M = n.getWorldMatrix();
  console.log(n.getName(), 'member', k, 'of', ex.members.length, 'T', n.getTranslation(), 'S', n.getScale());
  for (const p of n.getMesh().listPrimitives()) {
    const a = p.getAttribute('POSITION'), m = p.getAttribute('_MEMBER');
    const el = [], me = [];
    let mn = [1e9, 1e9, 1e9], mx = [-1e9, -1e9, -1e9], c = 0;
    for (let i = 0; i < a.getCount(); i++) {
      m.getElement(i, me); if (me[0] !== k) continue;
      a.getElement(i, el);
      const w = [0, 1, 2].map((r) => M[r] * el[0] + M[4 + r] * el[1] + M[8 + r] * el[2] + M[12 + r]);
      for (let j = 0; j < 3; j++) { mn[j] = Math.min(mn[j], w[j]); mx[j] = Math.max(mx[j], w[j]); } c++;
    }
    console.log('  ', p.getMaterial().getName(), c, mn.map((v) => +v.toFixed(1)), mx.map((v) => +v.toFixed(1)), 'm-count', m.getCount(), 'p-count', a.getCount(), a.getComponentType(), a.getNormalized());
  }
}
