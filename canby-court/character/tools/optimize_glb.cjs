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
  // Blender writes Sheen Tint as sheenColor (ignoring Sheen Weight): set physically sensible values.
  const SHEEN = { Skin: [0.07, 0.055, 0.05], Outfit_Summer: [0.16, 0.17, 0.19], Outfit_Winter: [0.10, 0.10, 0.11] };
  for (const m of root.listMaterials()) {
    const n = m.getName().replace(/\.\d+$/, '');
    m.setName(n);
    const sh = m.getExtension('KHR_materials_sheen');
    if (sh) { if (SHEEN[n]) sh.setSheenColorFactor(SHEEN[n]); else m.setExtension('KHR_materials_sheen', null); }
    const cc = m.getExtension('KHR_materials_clearcoat');
    if (cc && cc.getClearcoatFactor() === 0) m.setExtension('KHR_materials_clearcoat', null);
    m.setDoubleSided(/^(Hair|Outfit)/.test(n));
    if (/^Hair/.test(n)) { m.setAlphaMode('MASK'); m.setAlphaCutoff(0.4); }
    else if (/^Eyes/.test(n)) { m.setAlphaMode('BLEND'); }
    else { m.setAlphaMode('OPAQUE'); }
  }
  for (const nd of root.listNodes()) nd.setName(nd.getName().replace(/_web$/, ''));
  for (const me of root.listMeshes()) me.setName(me.getName().replace(/\.\d+$/, ''));
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
