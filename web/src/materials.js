// Materials: exponential height fog (global shader-chunk patch), painterly surface mottling,
// and the ground shader driven by the measured surface mask (R asphalt, G granite paving, B gravel).
import * as THREE from 'three';

// ---------------------------------------------------------------- height fog
// scene.fog is a THREE.Fog whose `near` = density (1/m) and `far` = height falloff (1/m);
// fog thins exponentially above FOG_BASE (T.P. metres, the lowest ground in the box).
const FOG_BASE = '48.0';
export function installHeightFog() {
  const C = THREE.ShaderChunk;
  C.fog_pars_vertex = /* glsl */`
#ifdef USE_FOG
  varying float vFogDepth;
  varying vec3 vFogWorldPos;
#endif`;
  C.fog_vertex = /* glsl */`
#ifdef USE_FOG
  vFogDepth = - mvPosition.z;
  vec4 fogWp = vec4( transformed, 1.0 );
  #ifdef USE_BATCHING
    fogWp = batchingMatrix * fogWp;
  #endif
  #ifdef USE_INSTANCING
    fogWp = instanceMatrix * fogWp;
  #endif
  vFogWorldPos = ( modelMatrix * fogWp ).xyz;
#endif`;
  C.fog_pars_fragment = /* glsl */`
#ifdef USE_FOG
  uniform vec3 fogColor;
  varying float vFogDepth;
  varying vec3 vFogWorldPos;
  uniform float fogNear;
  uniform float fogFar;
  #ifdef HW_ATMOS
    uniform vec3 hwSunDir;
    uniform vec3 hwSunCol;
  #endif
#endif`;
  C.fog_fragment = /* glsl */`
#ifdef USE_FOG
  {
    float fd = fogNear;           // density
    float fk = max( fogFar, 1e-4 ); // height falloff
    vec3 rv = vFogWorldPos - cameraPosition;
    float dist = length( rv );
    float h0 = max( cameraPosition.y - ${FOG_BASE}, 0.0 );
    float h1 = max( vFogWorldPos.y - ${FOG_BASE}, 0.0 );
    float dh = h1 - h0;
    float integ = abs( dh ) > 0.05 ? ( exp( -fk * h0 ) - exp( -fk * h1 ) ) / ( fk * dh ) : exp( -fk * h0 );
    float fogFactor = clamp( 1.0 - exp( -fd * dist * integ ), 0.0, 1.0 );
    vec3 fogC = fogColor;
    #ifdef HW_ATMOS
      // aerial perspective: haze toward the sun is lit warm (forward scattering)
      float sdot = max( dot( rv / max( dist, 1e-3 ), normalize( hwSunDir ) ), 0.0 );
      fogC += hwSunCol * ( pow( sdot, 8.0 ) * 0.7 + pow( sdot, 2.0 ) * 0.12 );
    #endif
    gl_FragColor.rgb = mix( gl_FragColor.rgb, fogC, fogFactor );
  }
#endif`;
}

// ---------------------------------------------------------------- GLSL noise
export const NOISE_GLSL = /* glsl */`
float hw_hash( vec2 p ) { p = fract( p * vec2( 123.34, 456.21 ) ); p += dot( p, p + 45.32 ); return fract( p.x * p.y ); }
float hw_noise( vec2 p ) {
  vec2 i = floor( p ), f = fract( p );
  vec2 u = f * f * ( 3.0 - 2.0 * f );
  return mix( mix( hw_hash( i ), hw_hash( i + vec2( 1.0, 0.0 ) ), u.x ), mix( hw_hash( i + vec2( 0.0, 1.0 ) ), hw_hash( i + vec2( 1.0, 1.0 ) ), u.x ), u.y );
}
float hw_fbm( vec2 p ) {
  float s = 0.0, a = 0.5;
  for ( int i = 0; i < 4; i ++ ) { s += a * hw_noise( p ); p = p * 2.03 + 17.1; a *= 0.5; }
  return s;
}
`;

// shared uniforms updated by the time-of-day system
export const shared = {
  uWet: { value: 0.2 },
  uTime: { value: 0 },
  uWarm: { value: 1 },   // 1 = golden hour, 0 = blue hour
  uNight: { value: 0 },  // 0 = daylight ... 1 = blue hour (lit interiors)
};

// ---------------------------------------------------------------- painterly surface
// Adds world-space brush mottling and slight hue drift to a MeshStandardMaterial.
// lift = [a, b, sat]: perceptual remap of (dark) sampled vertex colours, p' = a + b * p (p ~ sqrt(linear))
export function painterly(mat, { scale = 0.6, amount = 0.22, hue = 0.05, streak = 0, lift = null } = {}) {
  const liftGLSL = lift ? `
        #ifdef USE_COLOR
        {
          vec3 pc = sqrt( max( vColor.rgb, vec3( 1e-5 ) ) );
          float l = dot( pc, vec3( 0.3333 ) );
          float l2 = ${lift[0].toFixed(3)} + ${lift[1].toFixed(3)} * l;
          vec3 pc2 = mix( vec3( l2 ), pc * ( l2 / max( l, 1e-3 ) ), ${lift[2].toFixed(3)} );
          diffuseColor.rgb = diffuse * pc2 * pc2;
        }
        #endif` : '';
  mat.onBeforeCompile = (sh) => {
    sh.uniforms.uWarm = shared.uWarm;
    sh.vertexShader = sh.vertexShader
      .replace('#include <common>', '#include <common>\nvarying vec3 vPWorld;\nvarying vec3 vPNormal;')
      .replace('#include <begin_vertex>', `#include <begin_vertex>
        { vec4 pw = vec4( transformed, 1.0 );
          #ifdef USE_INSTANCING
            pw = instanceMatrix * pw;
          #endif
          vPWorld = ( modelMatrix * pw ).xyz;
          vPNormal = normalize( mat3( modelMatrix ) * objectNormal ); }`);
    sh.fragmentShader = sh.fragmentShader
      .replace('#include <common>', `#include <common>\nvarying vec3 vPWorld;\nvarying vec3 vPNormal;\nuniform float uWarm;\n${NOISE_GLSL}`)
      .replace('#include <color_fragment>', `#include <color_fragment>
        ${liftGLSL}
        {
          vec3 n = abs( vPNormal );
          vec2 q = n.y > 0.7 ? vPWorld.xz : ( n.x > n.z ? vPWorld.zy : vPWorld.xy );
          float b = hw_fbm( q * ${scale.toFixed(3)} + vec2( 0.0, ${streak.toFixed(3)} * q.x ) );
          float b2 = hw_noise( q * ${(scale * 6.0).toFixed(3)} );
          float m = mix( 1.0 - ${amount.toFixed(3)}, 1.0 + ${amount.toFixed(3)}, b * 0.8 + b2 * 0.2 );
          diffuseColor.rgb *= m;
          // hue drift: warm in the lit golden hour, cooler in the blue hour
          diffuseColor.rgb *= mix( vec3( 1.0 - ${hue.toFixed(3)}, 1.0, 1.0 + ${hue.toFixed(3)} ), vec3( 1.0 + ${hue.toFixed(3)}, 1.0, 1.0 - ${hue.toFixed(3)} ), b * uWarm );
        }`);
  };
  mat.customProgramCacheKey = () => `painterly-${scale}-${amount}-${hue}-${streak}-${lift}`;
  return mat;
}

export function makeRoleMaterials() {
  const std = (o) => new THREE.MeshStandardMaterial({ roughness: 0.88, metalness: 0, ...o });
  const M = {
    roof: painterly(std({ vertexColors: true, roughness: 0.62, color: 0xdfe2ea }), { scale: 1.3, amount: 0.18, hue: 0.03, lift: [0.2, 0.74, 1.1] }),
    wall: painterly(std({ vertexColors: true, roughness: 0.9, color: 0xfff1e0 }), { scale: 0.9, amount: 0.2, hue: 0.05, lift: [0.27, 0.74, 1.2] }),
    plinth: painterly(std({ vertexColors: false, roughness: 0.95, color: 0x8a7f72 }), { scale: 1.6, amount: 0.25 }),
    steps: painterly(std({ color: 0x8d8780, roughness: 0.7 }), { scale: 2.2, amount: 0.22 }),
    barrier: painterly(std({ color: 0xa69a88, roughness: 0.92 }), { scale: 1.2, amount: 0.25 }),
    trunk: painterly(std({ color: 0x4a3626, roughness: 0.95 }), { scale: 3.0, amount: 0.25 }),
    crown: painterly(std({ vertexColors: true, roughness: 0.95, color: 0xffffff }), { scale: 0.9, amount: 0.3, hue: 0.08 }),
    other: painterly(std({ vertexColors: false, color: 0xbbb3a6 }), {}),
  };
  return M;
}

// ---------------------------------------------------------------- ground
export function makeGroundMaterial(maskTex) {
  maskTex.flipY = false;               // row 0 = north edge (local y = +300) -> three z = -300
  maskTex.colorSpace = THREE.NoColorSpace;
  maskTex.minFilter = THREE.LinearMipmapLinearFilter;
  maskTex.magFilter = THREE.LinearFilter;
  maskTex.anisotropy = 4;
  const mat = new THREE.MeshStandardMaterial({ color: 0xffffff, roughness: 0.9, metalness: 0, envMapIntensity: 0.0 });
  mat.onBeforeCompile = (sh) => {
    sh.uniforms.uMask = { value: maskTex };
    sh.uniforms.uWet = shared.uWet;
    sh.vertexShader = sh.vertexShader
      .replace('#include <common>', '#include <common>\nvarying vec3 vGWorld;')
      .replace('#include <begin_vertex>', '#include <begin_vertex>\nvGWorld = ( modelMatrix * vec4( transformed, 1.0 ) ).xyz;');
    sh.fragmentShader = sh.fragmentShader
      .replace('#include <common>', `#include <common>
        varying vec3 vGWorld;
        uniform sampler2D uMask;
        uniform float uWet;
        float gPave; float gWetMask;
        ${NOISE_GLSL}`)
      .replace('#include <color_fragment>', `#include <color_fragment>
        {
          vec2 p = vGWorld.xz;
          // warp the 0.5 m mask edges a little so they read as hand-laid, not pixelated
          vec2 warp = vec2( hw_noise( p * 0.9 ), hw_noise( p * 0.9 + 31.7 ) ) - 0.5;
          vec2 muv = ( p + warp * 0.55 + 300.0 ) / 600.0;
          vec3 m = texture2D( uMask, muv ).rgb;
          float big = hw_fbm( p * 0.08 );
          float mid = hw_fbm( p * 0.6 );
          float fine = hw_noise( p * 7.0 );
          // soil / moss / garden ground
          vec3 soil = mix( vec3( 0.20, 0.16, 0.10 ), vec3( 0.16, 0.20, 0.09 ), smoothstep( 0.45, 0.7, big ) );
          soil *= 0.8 + 0.4 * mid;
          // gravel (masa-tsuchi)
          vec3 gravel = vec3( 0.47, 0.41, 0.32 ) * ( 0.82 + 0.3 * fine + 0.15 * mid );
          // asphalt with patching
          vec3 asph = vec3( 0.105, 0.105, 0.115 ) * ( 0.85 + 0.25 * mid ) + 0.02 * step( 0.72, hw_noise( p * 0.35 ) );
          // granite ishidatami: running-bond slabs (~0.62 x 0.31 m), random row offsets and slab lengths,
          // darker joints and per-slab tint (artistic texture over the measured surface class)
          vec2 sp = p / vec2( 0.62, 0.31 );
          float row = floor( sp.y );
          sp.x += hw_hash( vec2( row, 7.0 ) ) * 3.0;
          sp.x *= mix( 0.7, 1.3, hw_hash( vec2( row, 3.0 ) ) );
          vec2 cell = floor( sp ), f = fract( sp );
          float joint = smoothstep( 0.0, 0.05, min( min( f.x, 1.0 - f.x ) * 0.6, min( f.y, 1.0 - f.y ) ) );
          float slab = hw_hash( cell + row * 0.37 );
          vec3 pave = mix( vec3( 0.40, 0.37, 0.33 ), vec3( 0.56, 0.51, 0.44 ), slab ) * ( 0.86 + 0.22 * fine ) * ( 0.92 + 0.16 * mid );
          pave *= mix( 0.6, 1.0, joint );
          vec3 c = soil;
          c = mix( c, gravel, m.b );
          c = mix( c, asph, m.r );
          c = mix( c, pave, m.g );
          gPave = m.g * joint;
          gWetMask = clamp( m.g + m.r * 0.6, 0.0, 1.0 ) * smoothstep( 0.35, 0.65, hw_fbm( p * 0.25 + 3.0 ) + 0.25 );
          diffuseColor.rgb = c * ( 1.0 - 0.25 * uWet * gWetMask );
        }`)
      .replace('#include <roughnessmap_fragment>', `float roughnessFactor = mix( 0.94, mix( 0.9, 0.22, uWet ), gWetMask );`);
  };
  mat.customProgramCacheKey = () => 'hw-ground';
  return mat;
}
