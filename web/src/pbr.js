// Physically based role materials driven by the texture library (src/textures.js):
//   facade  - walls: modules picked per storey / bay from the facade atlas; UVs computed in the shader from
//             world position and the flat face normal (u = metres along the wall / bay width,
//             v = metres above the building's wall base / storey height); per-building style from extras
//   roof    - kawara tiles: u along the eave, v down the slope; flat roofs get a gravel/membrane finish
//   stone   - box-mapped world-space stone (plinths, steps, stone walls)
//   ground  - terrain: ishidatami / asphalt / gravel / soil textures by world UV, blended by the measured
//             surface mask, wet sheen at dusk
//   paving  - art-pass street ribbons (ishidatami or sett)
//   leaves  - alpha-tested leaf cards for tree canopies
// All take the art/PLATEAU vertex colour as a gentle tint. If the GLB carries a 'uv' attribute on walls/roofs
// (art pass), facades use it instead of the computed mapping (define HW_GLB_UV).
import * as THREE from 'three';
import { shared, NOISE_GLSL } from './materials.js';
import { M as MOD, MODULES } from './textures.js';

// ---------------------------------------------------------------- atmosphere (aerial perspective) patch
export const atmos = { hwSunDir: { value: new THREE.Vector3(0, 1, 0) }, hwSunCol: { value: new THREE.Color(1, 0.7, 0.5) } };
export function patchAtmos(mat) {
  if (!mat || mat.userData.hwAtmos || mat.isShaderMaterial || mat.fog === false) return mat;
  mat.userData.hwAtmos = true;
  const prev = mat.onBeforeCompile;
  const prevKey = mat.customProgramCacheKey();
  mat.defines = { ...(mat.defines || {}), HW_ATMOS: '' };
  mat.onBeforeCompile = (sh, r) => {
    if (prev) prev.call(mat, sh, r);
    sh.uniforms.hwSunDir = atmos.hwSunDir;
    sh.uniforms.hwSunCol = atmos.hwSunCol;
  };
  mat.customProgramCacheKey = () => prevKey + '|atmos';
  mat.needsUpdate = true;
  return mat;
}
export function patchAtmosTree(root) {
  root.traverse((o) => {
    if (!o.material) return;
    (Array.isArray(o.material) ? o.material : [o.material]).forEach(patchAtmos);
  });
}

// ---------------------------------------------------------------- shared GLSL
const WORLD_VARS = /* glsl */`
varying vec3 vHWPos;
varying vec3 vHWNrm;
`;
function addWorldPos(sh) {
  sh.vertexShader = sh.vertexShader
    .replace('#include <common>', '#include <common>\n' + WORLD_VARS)
    .replace('#include <begin_vertex>', `#include <begin_vertex>
      { vec4 hwp = vec4( transformed, 1.0 );
        #ifdef USE_INSTANCING
          hwp = instanceMatrix * hwp;
        #endif
        vHWPos = ( modelMatrix * hwp ).xyz;
        vHWNrm = mat3( modelMatrix ) * objectNormal; }`);
  sh.fragmentShader = sh.fragmentShader.replace('#include <common>', '#include <common>\n' + WORLD_VARS + NOISE_GLSL);
}

// exact face normal (role geometry is non-indexed with per-face normals, see world.js addRole), facing the
// camera. NOT derived from dFdx/dFdy of world positions: at ~150 m from the origin float32 derivatives give
// ~1e-3 rad of noise, which the UV frame (u = dot(xz, tangent)) amplifies into visible speckle.
const FLAT_N = /* glsl */`
  vec3 hwN = normalize( vHWNrm );
  if ( dot( hwN, cameraPosition - vHWPos ) < 0.0 ) hwN = -hwN;
`;
// tint: art / PLATEAU vertex colour normalised to luminance (hue + mild value), mixed in gently
const TINT = /* glsl */`
  vec3 hwTint = vec3( 1.0 );
  #ifdef USE_COLOR
    { float l = max( dot( vColor.rgb, vec3( 0.2126, 0.7152, 0.0722 ) ), 0.02 );
      vec3 hue = clamp( vColor.rgb / l, 0.6, 1.6 );
      hwTint = mix( vec3( 1.0 ), hue * mix( 0.85, 1.15, clamp( l * 4.0, 0.0, 1.0 ) ), HW_TINT ); }
  #endif
`;
// tangent-space normal -> view-space `normal` (three's lighting input)
const APPLY_NORMAL = /* glsl */`
  normal = normalize( ( viewMatrix * vec4( normalize( hwT * hwNt.x + hwB * hwNt.y + hwN * hwNt.z ), 0.0 ) ).xyz );
`;

function baseMaterial(opts) {
  const m = new THREE.MeshStandardMaterial({ roughness: 1, metalness: 0, flatShading: true, ...opts });
  return m;
}

// ---------------------------------------------------------------- facade
export function facadeMaterial(lib, { tint = 0.18, glbUv = false } = {}) {
  const F = lib.facade;
  // pushed back in depth so the art kit's facade cards (coplanar with the walls) always win: no z-fighting
  const m = baseMaterial({ vertexColors: true, color: 0xffffff, polygonOffset: true, polygonOffsetFactor: 1, polygonOffsetUnits: 4 });
  if (glbUv) m.defines = { HW_GLB_UV: '' };
  const slots = F.slots.map((s, i) => s || [i % F.grid[0], F.grid[1] - 1 - Math.floor(i / F.grid[0])]);
  m.onBeforeCompile = (sh) => {
    sh.uniforms.uAlb = { value: F.map }; sh.uniforms.uNrm = { value: F.normalMap }; sh.uniforms.uOrm = { value: F.ormMap };
    sh.uniforms.uGrid = { value: new THREE.Vector2(F.grid[0], F.grid[1]) };
    sh.uniforms.uSlots = { value: slots.map(([c, r]) => new THREE.Vector2(c, r)) };
    sh.uniforms.uBay = { value: F.bay_m };
    sh.uniforms.uWet = shared.uWet;
    addWorldPos(sh);
    sh.vertexShader = sh.vertexShader
      .replace('#include <common>', '#include <common>\nattribute vec4 aFac;\nflat varying vec4 vFac;\n#ifdef HW_GLB_UV\nvarying vec2 vHWUv;\n#endif')
      .replace('#include <begin_vertex>', '#include <begin_vertex>\nvFac = aFac;\n#ifdef HW_GLB_UV\nvHWUv = uv;\n#endif');
    sh.fragmentShader = sh.fragmentShader
      .replace('#include <packing>', `#include <packing>
        #define HW_TINT ${tint.toFixed(2)}
        flat varying vec4 vFac;   // per-building constants: flat, so floor()/hash() never see interpolation ulps
        #ifdef HW_GLB_UV
          varying vec2 vHWUv;
        #endif
        uniform sampler2D uAlb, uNrm, uOrm; uniform vec2 uGrid; uniform vec2 uSlots[${MODULES.length}]; uniform float uBay, uWet;
        vec3 hwT, hwB, hwN; vec3 hwNt; vec4 hwOrm; float hwAO;
        int hwModule( float storey, float nStorey, float style, float bay, float seed ) {
          float h = hw_hash( vec2( bay, seed * 31.7 ) ), hb = fract( seed * 7.31 );
          if ( storey >= nStorey ) return ${MOD.plain};
          if ( style > 4.5 ) return ${MOD.plain};
          if ( style > 3.5 ) return ${MOD.temple};
          if ( style > 1.5 ) {                                   // modern / modern-shop
            if ( storey < 0.5 && style > 2.5 ) return h < 0.85 ? ${MOD.shopfront} : ${MOD.modern_upper};
            return ${MOD.modern_upper};
          }
          if ( storey < 0.5 ) {                                  // machiya ground floor
            if ( style > 0.5 ) return h < 0.45 ? ${MOD.noren} : ( h < 0.9 ? ${MOD.koshi} : ${MOD.shopfront} );
            return h < 0.18 ? ${MOD.noren} : ${MOD.koshi};
          }
          return hb < 0.55 ? ${MOD.mushiko} : ${MOD.lattice};
        }`)
      .replace('#include <map_fragment>', `
        ${FLAT_N}
        hwB = vec3( 0.0, 1.0, 0.0 );
        hwT = normalize( vec3( -hwN.z, 0.0, hwN.x ) );
        float baseY = vFac.x, storeyH = max( vFac.y, 2.2 );
        float code = floor( vFac.z + 0.5 );
        float nStorey = floor( code / 16.0 + 0.001 ), style = code - nStorey * 16.0, seed = floor( vFac.w * 997.0 + 0.5 ) / 997.0;
        #ifdef HW_GLB_UV
          vec2 uvc = vHWUv;   // GLB facade UVs in facade units: u = bays, v = storeys (extras.facade_uv)
        #else
          vec2 uvc = vec2( dot( vHWPos.xz, hwT.xz ) / uBay + seed * 5.0, ( vHWPos.y - baseY ) / storeyH );
        #endif
        if ( abs( hwN.y ) > 0.6 ) uvc = vHWPos.xz / uBay;       // stray horizontal faces in the wall slot
        float storey = floor( uvc.y ), bay = floor( uvc.x );
        int mi = hwModule( max( storey, 0.0 ), max( nStorey, 1.0 ), style, bay, seed );
        vec2 cell = uSlots[ mi ];
        vec2 f = fract( uvc );
        if ( storey < 0.0 ) f.y = 0.02;                          // below the measured base: plinth-ish
        f = clamp( f, vec2( 0.004 ), vec2( 0.996 ) );
        vec2 auv = ( cell + f ) / uGrid;
        vec2 gx = dFdx( uvc ) / uGrid, gy = dFdy( uvc ) / uGrid;
        vec4 alb = textureGrad( uAlb, auv, gx, gy );
        hwOrm = textureGrad( uOrm, auv, gx, gy );
        hwNt = textureGrad( uNrm, auv, gx, gy ).xyz * 2.0 - 1.0;
        ${TINT}
        diffuseColor.rgb = alb.rgb * hwTint * ( 0.55 + 0.45 * hwOrm.r );
        // rain-darkened base at dusk
        diffuseColor.rgb *= 1.0 - 0.25 * uWet * smoothstep( 0.6, 0.0, vHWPos.y - baseY );
      `)
      .replace('#include <color_fragment>', '')
      .replace('#include <roughnessmap_fragment>', 'float roughnessFactor = clamp( hwOrm.g, 0.04, 1.0 );')
      .replace('#include <normal_fragment_maps>', APPLY_NORMAL);
  };
  m.customProgramCacheKey = () => 'hw-facade-' + tint + (glbUv ? '-uv' : '');
  m.userData.hwRole = 'facade';
  return m;
}

// ---------------------------------------------------------------- roof
export function roofMaterial(lib, { tint = 0.25 } = {}) {
  const K = lib.kawara, G = lib.gravel;
  const m = baseMaterial({ vertexColors: true, color: 0xffffff });
  m.onBeforeCompile = (sh) => {
    sh.uniforms.uAlb = { value: K.map }; sh.uniforms.uNrm = { value: K.normalMap }; sh.uniforms.uOrm = { value: K.ormMap };
    sh.uniforms.uSize = { value: new THREE.Vector2(...K.size_m) };
    sh.uniforms.uFlat = { value: G.map }; sh.uniforms.uFlatSize = { value: G.size_m[0] };
    sh.uniforms.uWet = shared.uWet;
    addWorldPos(sh);
    sh.fragmentShader = sh.fragmentShader
      .replace('#include <packing>', `#include <packing>
        #define HW_TINT ${tint.toFixed(2)}
        uniform sampler2D uAlb, uNrm, uOrm, uFlat; uniform vec2 uSize; uniform float uFlatSize, uWet;
        vec3 hwT, hwB, hwN; vec3 hwNt; vec4 hwOrm;`)
      .replace('#include <map_fragment>', `
        ${FLAT_N}
        ${TINT}
        if ( hwN.y > 0.97 || hwN.y < 0.25 ) {
          // flat roof (membrane / gravel) or a steep wall-like roof face
          vec2 uv = ( abs( hwN.y ) > 0.5 ? vHWPos.xz : vec2( dot( vHWPos.xz, normalize( vec2( -hwN.z, hwN.x ) + 1e-4 ) ), vHWPos.y ) ) / uFlatSize;
          diffuseColor.rgb = texture2D( uFlat, uv ).rgb * vec3( 0.55, 0.56, 0.6 ) * hwTint;
          hwOrm = vec4( 1.0, 0.85, 0.0, 1.0 );
          hwT = vec3( 1.0, 0.0, 0.0 ); hwB = vec3( 0.0, 0.0, 1.0 ); hwNt = vec3( 0.0, 0.0, 1.0 );
        } else {
          vec2 d = normalize( hwN.xz );                         // horizontal down-slope direction
          vec2 e = vec2( -d.y, d.x );                           // along the eave
          vec2 uv = vec2( dot( vHWPos.xz, e ) / uSize.x, -dot( vHWPos.xz, d ) / max( hwN.y, 0.25 ) / uSize.y );
          vec4 alb = texture2D( uAlb, uv );
          hwOrm = texture2D( uOrm, uv );
          hwNt = texture2D( uNrm, uv ).xyz * 2.0 - 1.0;
          hwT = normalize( vec3( e.x, 0.0, e.y ) );
          hwB = normalize( cross( hwN, hwT ) );
          if ( hwB.y < 0.0 ) hwB = -hwB;
          diffuseColor.rgb = alb.rgb * hwTint * ( 0.6 + 0.4 * hwOrm.r );
        }
      `)
      .replace('#include <color_fragment>', '')
      .replace('#include <roughnessmap_fragment>', 'float roughnessFactor = clamp( mix( hwOrm.g, hwOrm.g * 0.45, uWet ), 0.05, 1.0 );')
      .replace('#include <normal_fragment_maps>', APPLY_NORMAL);
  };
  m.customProgramCacheKey = () => 'hw-roof-' + tint;
  m.userData.hwRole = 'roof';
  return m;
}

// ---------------------------------------------------------------- box-mapped stone (plinth, steps, walls)
export function stoneMaterial(set, { tint = 0.0, color = 0xffffff, scale = 1, topSet = null } = {}) {
  const m = baseMaterial({ vertexColors: tint > 0, color });
  const top = topSet || set;
  m.onBeforeCompile = (sh) => {
    sh.uniforms.uAlb = { value: set.map }; sh.uniforms.uNrm = { value: set.normalMap }; sh.uniforms.uOrm = { value: set.ormMap };
    sh.uniforms.uAlbT = { value: top.map }; sh.uniforms.uNrmT = { value: top.normalMap }; sh.uniforms.uOrmT = { value: top.ormMap };
    sh.uniforms.uSize = { value: set.size_m[0] * scale }; sh.uniforms.uSizeT = { value: top.size_m[0] * scale };
    sh.uniforms.uWet = shared.uWet;
    addWorldPos(sh);
    sh.fragmentShader = sh.fragmentShader
      .replace('#include <packing>', `#include <packing>
        #define HW_TINT ${tint.toFixed(2)}
        uniform sampler2D uAlb, uNrm, uOrm, uAlbT, uNrmT, uOrmT; uniform float uSize, uSizeT, uWet;
        vec3 hwT, hwB, hwN; vec3 hwNt; vec4 hwOrm;`)
      .replace('#include <map_fragment>', `
        ${FLAT_N}
        ${TINT}
        vec4 alb;
        if ( abs( hwN.y ) > 0.7 ) {
          vec2 uv = vHWPos.xz / uSizeT;
          alb = texture2D( uAlbT, uv ); hwOrm = texture2D( uOrmT, uv ); hwNt = texture2D( uNrmT, uv ).xyz * 2.0 - 1.0;
          hwT = vec3( 1.0, 0.0, 0.0 ); hwB = vec3( 0.0, 0.0, -1.0 );
        } else {
          hwT = normalize( vec3( -hwN.z, 0.0, hwN.x ) ); hwB = vec3( 0.0, 1.0, 0.0 );
          vec2 uv = vec2( dot( vHWPos.xz, hwT.xz ), vHWPos.y ) / uSize;
          alb = texture2D( uAlb, uv ); hwOrm = texture2D( uOrm, uv ); hwNt = texture2D( uNrm, uv ).xyz * 2.0 - 1.0;
        }
        diffuseColor.rgb *= alb.rgb * hwTint * ( 0.6 + 0.4 * hwOrm.r );
      `)
      .replace('#include <color_fragment>', '')
      .replace('#include <roughnessmap_fragment>', 'float roughnessFactor = clamp( mix( hwOrm.g, hwOrm.g * 0.5, uWet * step( 0.7, hwN.y ) ), 0.05, 1.0 );')
      .replace('#include <normal_fragment_maps>', APPLY_NORMAL);
  };
  const key = 'hw-stone-' + tint + '-' + (set.map && set.map.uuid) + (top.map && top.map.uuid) + scale;
  m.customProgramCacheKey = () => key;
  return m;
}

// ---------------------------------------------------------------- ground (terrain) and street ribbons
// lite (mobile): normal maps only for the paving layer, cheaper noise
export function groundMaterial(lib, maskTex, { lite = false } = {}) {
  maskTex.flipY = false;               // row 0 = north edge (local y = +300) -> three z = -300
  maskTex.colorSpace = THREE.NoColorSpace;
  maskTex.minFilter = THREE.LinearMipmapLinearFilter;
  maskTex.needsUpdate = true;
  const S = [lib.ishidatami, lib.asphalt, lib.gravel, lib.soil];
  const m = new THREE.MeshStandardMaterial({ color: 0xffffff, roughness: 0.9, metalness: 0, envMapIntensity: 0.0 });
  m.onBeforeCompile = (sh) => {
    sh.uniforms.uMask = { value: maskTex };
    sh.uniforms.uWet = shared.uWet;
    ['P', 'A', 'G', 'S'].forEach((k, i) => {
      sh.uniforms['uAlb' + k] = { value: S[i].map }; sh.uniforms['uNrm' + k] = { value: S[i].normalMap };
      sh.uniforms['uOrm' + k] = { value: S[i].ormMap }; sh.uniforms['uSz' + k] = { value: S[i].size_m[0] };
    });
    addWorldPos(sh);
    sh.fragmentShader = sh.fragmentShader
      .replace('#include <packing>', `#include <packing>
        uniform sampler2D uMask, uAlbP, uNrmP, uOrmP, uAlbA, uNrmA, uOrmA, uAlbG, uNrmG, uOrmG, uAlbS, uNrmS, uOrmS;
        uniform float uSzP, uSzA, uSzG, uSzS, uWet;
        vec3 hwNt; float hwRough; float hwWetMask;
        void hwLayer( sampler2D A, sampler2D N, sampler2D O, float sz, float w, vec2 p, inout vec3 c, inout vec3 n, inout float r ) {
          vec2 uv = p / sz;
          c += w * texture2D( A, uv ).rgb; n += w * ( texture2D( N, uv ).xyz * 2.0 - 1.0 ); r += w * texture2D( O, uv ).g;
        }
        void hwLayerLite( sampler2D A, sampler2D O, float sz, float w, vec2 p, inout vec3 c, inout vec3 n, inout float r ) {
          vec2 uv = p / sz;
          c += w * texture2D( A, uv ).rgb; n += w * vec3( 0.0, 0.0, 1.0 ); r += w * texture2D( O, uv ).g;
        }`)
      .replace('#include <map_fragment>', `
        vec2 p = vHWPos.xz;
        vec2 warp = vec2( hw_noise( p * 0.9 ), hw_noise( p * 0.9 + 31.7 ) ) - 0.5;
        vec3 msk = texture2D( uMask, ( p + warp * 0.55 + 300.0 ) / 600.0 ).rgb;
        float wP = msk.g, wA = msk.r * ( 1.0 - wP ), wG = msk.b * ( 1.0 - wP ) * ( 1.0 - msk.r );
        float wS = max( 0.0, 1.0 - wP - wA - wG );
        vec3 c = vec3( 0.0 ), n = vec3( 0.0 ); float r = 0.0;
        // sampled unconditionally: branching on the mask weights would break mip derivatives at the borders
        hwLayer( uAlbP, uNrmP, uOrmP, uSzP, wP, p, c, n, r );
        #ifdef HW_LITE
          hwLayerLite( uAlbA, uOrmA, uSzA, wA, p, c, n, r );
          hwLayerLite( uAlbG, uOrmG, uSzG, wG, p, c, n, r );
          hwLayerLite( uAlbS, uOrmS, uSzS, wS, p, c, n, r );
          float big = hw_noise( p * 0.1 );
        #else
          hwLayer( uAlbA, uNrmA, uOrmA, uSzA, wA, p, c, n, r );
          hwLayer( uAlbG, uNrmG, uOrmG, uSzG, wG, p, c, n, r );
          hwLayer( uAlbS, uNrmS, uOrmS, uSzS, wS, p, c, n, r );
          float big = hw_fbm( p * 0.05 );
        #endif
        c *= 0.85 + 0.3 * big;
        hwNt = normalize( n + vec3( 0.0, 0.0, 0.001 ) );
        hwWetMask = clamp( wP + wA * 0.6, 0.0, 1.0 ) * smoothstep( 0.35, 0.65, big * 0.7 + hw_noise( p * 0.3 + 3.0 ) * 0.3 + 0.25 );
        hwRough = mix( r, r * 0.3, uWet * hwWetMask );
        diffuseColor.rgb = c * ( 1.0 - 0.3 * uWet * hwWetMask );
      `)
      .replace('#include <color_fragment>', '')
      .replace('#include <roughnessmap_fragment>', 'float roughnessFactor = clamp( hwRough, 0.04, 1.0 );')
      // terrain is near-horizontal: perturb the smooth vertex normal in the world x / -z tangent frame
      .replace('#include <normal_fragment_maps>', 'normal = normalize( normal + mat3( viewMatrix ) * vec3( hwNt.x, 0.0, -hwNt.y ) * 0.8 );');
  };
  if (lite) m.defines = { HW_LITE: '' };
  m.customProgramCacheKey = () => 'hw-ground-pbr' + (lite ? '-lite' : '');
  return m;
}

export function pavingMaterial(set, { wetness = true } = {}) {
  const m = new THREE.MeshStandardMaterial({ color: 0xffffff, roughness: 0.8, metalness: 0, envMapIntensity: 0.0 });
  m.onBeforeCompile = (sh) => {
    sh.uniforms.uAlb = { value: set.map }; sh.uniforms.uNrm = { value: set.normalMap }; sh.uniforms.uOrm = { value: set.ormMap };
    sh.uniforms.uSz = { value: set.size_m[0] }; sh.uniforms.uWet = shared.uWet;
    addWorldPos(sh);
    sh.fragmentShader = sh.fragmentShader
      .replace('#include <packing>', `#include <packing>
        uniform sampler2D uAlb, uNrm, uOrm; uniform float uSz, uWet; vec3 hwNt; float hwRough;`)
      .replace('#include <map_fragment>', `
        vec2 uv = vHWPos.xz / uSz;
        vec4 o = texture2D( uOrm, uv );
        hwNt = texture2D( uNrm, uv ).xyz * 2.0 - 1.0;
        float wm = ${wetness ? 'smoothstep( 0.35, 0.65, hw_fbm( vHWPos.xz * 0.25 + 3.0 ) + 0.25 )' : '0.0'};
        hwRough = mix( o.g, o.g * 0.3, uWet * wm );
        diffuseColor.rgb = texture2D( uAlb, uv ).rgb * ( 0.85 + 0.3 * hw_fbm( vHWPos.xz * 0.05 ) ) * ( 0.65 + 0.35 * o.r ) * ( 1.0 - 0.3 * uWet * wm );
      `)
      .replace('#include <color_fragment>', '')
      .replace('#include <roughnessmap_fragment>', 'float roughnessFactor = clamp( hwRough, 0.04, 1.0 );')
      .replace('#include <normal_fragment_maps>', 'normal = normalize( normal + mat3( viewMatrix ) * vec3( hwNt.x, 0.0, -hwNt.y ) * 0.8 );');
  };
  m.customProgramCacheKey = () => 'hw-paving-' + (set.map && set.map.uuid);
  return m;
}

// ---------------------------------------------------------------- leaf-card canopies
export function leafMaterial(lib) {
  const m = new THREE.MeshStandardMaterial({
    map: lib.leaf.map, alphaTest: 0.5, side: THREE.DoubleSide, roughness: 0.85, metalness: 0, color: 0xffffff,
  });
  // soft translucency: back-lit leaves glow a little (artistic approximation)
  m.onBeforeCompile = (sh) => {
    sh.fragmentShader = sh.fragmentShader.replace('#include <lights_fragment_end>', `#include <lights_fragment_end>
      reflectedLight.indirectDiffuse += diffuseColor.rgb * 0.12;`);
  };
  m.customProgramCacheKey = () => 'hw-leaf';
  return m;
}

// canopy of crossed alpha cards filling a unit sphere (radius 1); normals point outward for soft volume shading
export function canopyGeometry(cards = 34, seed = 3) {
  let a = seed;
  const rnd = () => { a |= 0; a = (a + 0x6d2b79f5) | 0; let t = Math.imul(a ^ (a >>> 15), 1 | a); t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
  const pos = [], nrm = [], uv = [], idx = [];
  const q = new THREE.Quaternion(), e = new THREE.Euler(), v = new THREE.Vector3(), c = new THREE.Vector3();
  for (let i = 0; i < cards; i++) {
    // centres biased to the shell for a fuller silhouette
    const r = 0.35 + 0.6 * Math.cbrt(rnd());
    const th = rnd() * Math.PI * 2, ph = Math.acos(2 * rnd() - 1);
    c.set(Math.sin(ph) * Math.cos(th) * r, Math.cos(ph) * r * 0.85, Math.sin(ph) * Math.sin(th) * r);
    e.set((rnd() - 0.5) * 2.2, rnd() * Math.PI * 2, (rnd() - 0.5) * 2.2); q.setFromEuler(e);
    const s = 0.75 + rnd() * 0.5;
    const base = pos.length / 3;
    for (const [x, y, u, w] of [[-1, -1, 0, 0], [1, -1, 1, 0], [1, 1, 1, 1], [-1, 1, 0, 1]]) {
      v.set(x * s * 0.5, y * s * 0.5, 0).applyQuaternion(q).add(c);
      pos.push(v.x, v.y, v.z);
      const n = v.clone().normalize().multiplyScalar(0.8).add(new THREE.Vector3(0, 0.45, 0)).normalize();
      nrm.push(n.x, n.y, n.z);
      uv.push(u, w);
    }
    idx.push(base, base + 1, base + 2, base, base + 2, base + 3);
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
  g.setAttribute('normal', new THREE.Float32BufferAttribute(nrm, 3));
  g.setAttribute('uv', new THREE.Float32BufferAttribute(uv, 2));
  g.setIndex(idx);
  return g;
}

// ---------------------------------------------------------------- per-building facade attribute
// aFac = (wall base y, storey height, nStoreys * 16 + style, seed)
export const STYLE = { machiya: 0, machiyaShop: 1, modern: 2, modernShop: 3, temple: 4, plain: 5 };
const SHOP = new Set(['402', '403', '404', '413', '414']);
export function styleOf(ex, storeys) {
  const u = String(ex.usage || '');
  const yr = parseInt(ex.year, 10) || 0;
  if (u === '421' || u === '422' || u === '441' || /寺|神社|堂/.test(ex.name || '')) return STYLE.temple;
  if (storeys >= 3 || (yr >= 1985 && (u === '401' || u === '412'))) return SHOP.has(u) || u === '401' ? STYLE.modernShop : STYLE.modern;
  if (ex.priority === 2 || SHOP.has(u)) return STYLE.machiyaShop;
  return STYLE.machiya;
}
export function hashStr(s) {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619); }
  return ((h >>> 0) % 10007) / 10007;
}
