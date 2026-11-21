// Post-process the Blender glTF export: material flags, cleanup, meshopt + WebP.
// usage: NODE_PATH=<dir with node_modules> node optimize_glb.cjs in.glb out.glb [maxTex]
const { NodeIO } = require('@gltf-transform/core');
const { ALL_EXTENSIONS } = require('@gltf-transform/extensions');
const { dedup, prune, resample, meshopt, textureCompress, weld } = require('@gltf-transform/functions');
const { MeshoptEncoder, MeshoptDecoder } = require('meshoptimizer');
const sharp = require('sharp');

(async () => {
  const [inp, out, maxTex = '1024'] = process.argv.slice(2);
  await MeshoptEncoder.ready; await MeshoptDecoder.ready;
  const io = new NodeIO().registerExtensions(ALL_EXTENSIONS).registerDependencies({
    'meshopt.encoder': MeshoptEncoder, 'meshopt.decoder': MeshoptDecoder });
  const doc = await io.read(inp);
  const root = doc.getRoot();
  for (const m of root.listMaterials()) {
    const n = m.getName();
    if (n === 'Hair') { m.setAlphaMode('MASK'); m.setAlphaCutoff(0.4); m.setDoubleSided(true); }
    else if (n === 'Eyes') { m.setAlphaMode('BLEND'); }
    else { m.setAlphaMode('OPAQUE'); }
  }
  const S = Number(maxTex);
  await doc.transform(
    dedup(), prune({ keepLeaves: true, keepAttributes: false }), resample({ tolerance: 1e-4 }),
    textureCompress({ encoder: sharp, targetFormat: 'webp', resize: [S, S], quality: 88,
                      slots: /^(?!normalTexture).*$/ }),
    textureCompress({ encoder: sharp, targetFormat: 'webp', resize: [S, S], lossless: false, quality: 95,
                      slots: /^normalTexture$/ }),
    meshopt({ encoder: MeshoptEncoder, level: 'medium' }),
  );
  await io.write(out, doc);
  const anims = root.listAnimations().map(a => {
    let d = 0; for (const s of a.listSamplers()) { const t = s.getInput().getArray(); d = Math.max(d, t[t.length - 1]); }
    return `${a.getName()} ${d.toFixed(3)}s`; });
  console.log(JSON.stringify({ out, meshes: root.listMeshes().map(m => m.getName()),
    materials: root.listMaterials().map(m => m.getName()), animations: anims,
    textures: root.listTextures().map(t => `${t.getName()} ${t.getMimeType()} ${t.getImage().byteLength}`) }, null, 1));
})().catch(e => { console.error(e); process.exit(1); });
