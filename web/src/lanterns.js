// ARTISTIC: instanced paper lanterns (chōchin) hung from facades along Ninenzaka and Sannenzaka.
// Positions follow the OSM street centrelines; each lantern is only placed where a horizontal ray from the
// street finds a real facade (PLATEAU wall) within reach, so none float in the air.
import * as THREE from 'three';

const NAMES = new Set(['二寧坂', '産寧坂']);
const _ray = new THREE.Ray();

export function buildLanterns(scene, minimap, controller, { spacing = 7 } = {}) {
  const spots = [];
  const bvh = controller.bvh;
  for (const s of minimap.streets) {
    if (!s.name || !NAMES.has(s.name) || s.hw === 'steps') continue;
    const P = [];
    for (let i = 0; i < s.pts.length; i += 2) P.push([s.pts[i], -s.pts[i + 1]]); // three x, z
    let carry = spacing * 0.5, side = 1;
    for (let i = 0; i < P.length - 1; i++) {
      const [ax, az] = P[i], [bx, bz] = P[i + 1];
      const L = Math.hypot(bx - ax, bz - az);
      if (L < 1e-3) continue;
      const dx = (bx - ax) / L, dz = (bz - az) / L;
      for (let d = carry; d < L; d += spacing) {
        const cx = ax + dx * d, cz = az + dz * d;
        if (Math.abs(cx) > 198 || Math.abs(cz) > 198) continue;
        side = -side;
        const nx = -dz * side, nz = dx * side;
        const g = controller.dropTo(cx, cz);
        if (!g || !g.info.walkable) continue;
        const y = g.y + 2.35;
        _ray.origin.set(cx, y, cz);
        _ray.direction.set(nx, 0, nz);
        const reach = s.w / 2 + 3.5;
        const hit = bvh.raycastFirst(_ray, THREE.DoubleSide, 0, reach);
        if (!hit || Math.abs(hit.face.normal.y) > 0.4 || hit.distance < 0.7) continue;
        spots.push({ x: hit.point.x - nx * 0.34, y, z: hit.point.z - nz * 0.34, nx, nz, wall: hit.point.clone() });
      }
      carry = (carry - L) % spacing;
      if (carry < 0) carry += spacing;
    }
  }

  const n = spots.length;
  const group = new THREE.Group();
  group.name = 'Lanterns_artistic';
  if (!n) return { group, update() {}, count: 0 };

  // paper body: lathe profile
  const prof = [];
  for (let i = 0; i <= 10; i++) {
    const t = i / 10;
    prof.push(new THREE.Vector2(0.06 + 0.11 * Math.sin(Math.PI * t), -0.21 + 0.42 * t));
  }
  const bodyG = new THREE.LatheGeometry(prof, 14);
  const bodyM = new THREE.MeshStandardMaterial({ color: 0xf3e3c3, roughness: 0.8, emissive: new THREE.Color(1.0, 0.52, 0.2), emissiveIntensity: 1 });
  const capG = new THREE.CylinderGeometry(0.075, 0.075, 0.05, 10);
  const capM = new THREE.MeshStandardMaterial({ color: 0x1f1714, roughness: 0.6 });
  const armG = new THREE.BoxGeometry(0.03, 0.03, 1);
  const body = new THREE.InstancedMesh(bodyG, bodyM, n);
  const caps = new THREE.InstancedMesh(capG, capM, n * 2);
  const arms = new THREE.InstancedMesh(armG, capM, n);
  const o = new THREE.Object3D();
  spots.forEach((s, i) => {
    o.position.set(s.x, s.y, s.z); o.rotation.set(0, 0, 0); o.scale.set(1, 1, 1); o.updateMatrix();
    body.setMatrixAt(i, o.matrix);
    o.position.y = s.y + 0.22; o.updateMatrix(); caps.setMatrixAt(i * 2, o.matrix);
    o.position.y = s.y - 0.22; o.updateMatrix(); caps.setMatrixAt(i * 2 + 1, o.matrix);
    // bracket from the wall to above the lantern
    const len = Math.hypot(s.wall.x - s.x, s.wall.z - s.z) + 0.05;
    o.position.set((s.x + s.wall.x) / 2, s.y + 0.3, (s.z + s.wall.z) / 2);
    o.rotation.set(0, Math.atan2(s.nx, s.nz), 0); o.scale.set(1, 1, len); o.updateMatrix();
    arms.setMatrixAt(i, o.matrix);
  });
  for (const m of [body, caps, arms]) { m.castShadow = false; m.receiveShadow = false; m.computeBoundingSphere(); group.add(m); }

  // glow halos (camera-facing, additive) so lanterns read as lit even without bloom
  const haloM = new THREE.ShaderMaterial({
    uniforms: { uI: { value: 1 }, uSize: { value: 1.3 } },
    vertexShader: /* glsl */`
      uniform float uSize; varying vec2 vUv; varying float vFade;
      void main() {
        vUv = position.xy;
        vec3 c = ( modelMatrix * instanceMatrix * vec4( 0.0, 0.0, 0.0, 1.0 ) ).xyz;
        vec4 mv = viewMatrix * vec4( c, 1.0 );
        float dist = -mv.z;
        vFade = smoothstep( 160.0, 40.0, dist ) * smoothstep( 0.6, 2.0, dist );
        mv.xy += position.xy * uSize;
        mv.z += 0.25;
        gl_Position = projectionMatrix * mv;
      }`,
    fragmentShader: /* glsl */`
      uniform float uI; varying vec2 vUv; varying float vFade;
      void main() {
        float r = length( vUv ) * 2.0;
        float a = exp( -r * r * 5.0 ) * 0.9 + exp( -r * 9.0 ) * 0.5;
        gl_FragColor = vec4( vec3( 1.0, 0.58, 0.26 ) * a * uI * vFade, 1.0 );
      }`,
    transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, fog: false,
  });
  const halo = new THREE.InstancedMesh(new THREE.PlaneGeometry(1, 1), haloM, n);
  spots.forEach((s, i) => { o.position.set(s.x, s.y, s.z); o.rotation.set(0, 0, 0); o.scale.set(1, 1, 1); o.updateMatrix(); halo.setMatrixAt(i, o.matrix); });
  halo.frustumCulled = false;
  halo.renderOrder = 5;
  group.add(halo);
  scene.add(group);

  return {
    group, count: n, spots,
    update(intensity) {
      bodyM.emissiveIntensity = 0.35 + intensity * 0.9;
      haloM.uniforms.uI.value = 0.12 + intensity * 0.32;
    },
  };
}
