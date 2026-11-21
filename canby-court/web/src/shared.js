// Uniforms shared by every procedural material (one object each, so a single assignment updates all programs).
import * as THREE from 'three';
export const SU = {
  uSeason: { value: 0 },                          // 0 summer ... 1 winter
  uNoise: { value: null },                        // RGBA tileable noise (terrain.js noiseTexture)
  uSunDirW: { value: new THREE.Vector3(0, 1, 0) },
  uTime: { value: 0 },
};

// snow-cover chunk for vegetation / props: world normal facing up + noise, scaled by the season
export const SNOW_GLSL = /* glsl */`
float ccSnow(vec3 wn, vec3 wp, float bias) {
  float n = texture2D(uNoise, wp.xz * 0.21).g;
  return uSeason * smoothstep(0.15, 0.55, wn.y + bias + (n - 0.5) * 0.5);
}`;
