// ARTISTIC: drifting late-autumn leaves (momiji / ginkgo) and a few petals around the camera.
// One Points draw call; positions wrap inside a box that follows the camera.
import * as THREE from 'three';

export function buildLeaves(scene, count) {
  const B = new THREE.Vector3(36, 14, 36);
  const pos = new Float32Array(count * 3), seed = new Float32Array(count * 4), col = new Float32Array(count * 3);
  const palette = [[0.75, 0.13, 0.06], [0.85, 0.32, 0.07], [0.9, 0.62, 0.12], [0.62, 0.1, 0.08], [0.95, 0.78, 0.8]];
  for (let i = 0; i < count; i++) {
    pos.set([Math.random() * B.x, Math.random() * B.y, Math.random() * B.z], i * 3);
    seed.set([Math.random(), Math.random(), 0.4 + Math.random() * 0.8, Math.random() * 6.28], i * 4);
    col.set(palette[Math.floor(Math.random() * palette.length)], i * 3);
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.BufferAttribute(pos, 3));
  g.setAttribute('seed', new THREE.BufferAttribute(seed, 4));
  g.setAttribute('pcol', new THREE.BufferAttribute(col, 3));
  const m = new THREE.ShaderMaterial({
    uniforms: { uTime: { value: 0 }, uCam: { value: new THREE.Vector3() }, uBox: { value: B }, uScale: { value: 300 }, uLight: { value: new THREE.Color(1, 1, 1) } },
    vertexShader: /* glsl */`
      attribute vec4 seed; attribute vec3 pcol;
      uniform float uTime, uScale; uniform vec3 uCam, uBox;
      varying vec3 vCol; varying float vRot; varying float vA;
      void main() {
        float t = uTime * seed.z;
        vec3 p = position;
        p.y -= uTime * ( 0.35 + 0.35 * seed.x );
        p.x += uTime * 0.45 + sin( t * 1.3 + seed.w ) * 0.8;
        p.z += sin( t * 0.9 + seed.w * 2.0 ) * 0.7 + uTime * 0.12;
        vec3 o = uCam - uBox * vec3( 0.5, 0.35, 0.5 );
        p = o + mod( p - o, uBox );
        vec4 mv = viewMatrix * vec4( p, 1.0 );
        float d = -mv.z;
        gl_PointSize = uScale * ( 0.07 + 0.05 * seed.y ) / max( d, 0.5 );
        gl_Position = projectionMatrix * mv;
        vCol = pcol;
        vRot = t * 2.0 + seed.w;
        vec3 rel = ( p - o ) / uBox;
        float edge = min( min( rel.x, 1.0 - rel.x ), min( rel.z, 1.0 - rel.z ) );
        vA = smoothstep( 0.0, 0.12, edge ) * smoothstep( 0.0, 0.1, min( rel.y, 1.0 - rel.y ) ) * smoothstep( 0.8, 2.5, d );
      }`,
    fragmentShader: /* glsl */`
      uniform vec3 uLight;
      varying vec3 vCol; varying float vRot; varying float vA;
      void main() {
        vec2 q = gl_PointCoord - 0.5;
        float c = cos( vRot ), s = sin( vRot );
        q = mat2( c, -s, s, c ) * q;
        q.x *= 1.0 + 0.8 * abs( sin( vRot * 0.7 ) );     // tumbling
        float r = length( q * vec2( 1.0, 1.7 ) );
        float a = smoothstep( 0.5, 0.42, r ) * vA;
        if ( a < 0.02 ) discard;
        gl_FragColor = vec4( vCol * uLight * ( 0.8 + 0.4 * q.y ), a );
        #include <tonemapping_fragment>
        #include <colorspace_fragment>
      }`,
    transparent: true, depthWrite: false, fog: false,
  });
  const pts = new THREE.Points(g, m);
  pts.frustumCulled = false;
  pts.name = 'Leaves_artistic';
  scene.add(pts);
  return {
    points: pts,
    update(dt, camera, light, viewportH) {
      m.uniforms.uTime.value += dt;
      m.uniforms.uCam.value.copy(camera.position);
      m.uniforms.uScale.value = viewportH * 0.9;
      m.uniforms.uLight.value.copy(light);
    },
  };
}
