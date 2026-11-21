// Post-processing chain (quality tiered):
//   RenderPass -> GTAO (high/photo) -> UnrealBloom (high/photo) -> OutputPass (ACES + sRGB)
//   -> colour grade + vignette (medium+) -> FXAA (medium) | SMAA (photo, when no MSAA)
// One composer for the page lifetime; passes are enabled/disabled per tier (no GPU resource churn).
import * as THREE from 'three';
import { EffectComposer } from 'three/addons/postprocessing/EffectComposer.js';
import { RenderPass } from 'three/addons/postprocessing/RenderPass.js';
import { UnrealBloomPass } from 'three/addons/postprocessing/UnrealBloomPass.js';
import { OutputPass } from 'three/addons/postprocessing/OutputPass.js';
import { ShaderPass } from 'three/addons/postprocessing/ShaderPass.js';
import { GTAOPass } from 'three/addons/postprocessing/GTAOPass.js';
import { SMAAPass } from 'three/addons/postprocessing/SMAAPass.js';
import { FXAAShader } from 'three/addons/shaders/FXAAShader.js';

// GTAO at a fraction of the composer resolution; objects flagged userData.noAO (sky, leaf cards, particles,
// halos) are hidden from its normal/depth pre-pass so alpha cards do not cast square AO
class LeanGTAOPass extends GTAOPass {
  constructor(scene, camera, w, h) { super(scene, camera, w, h); this.resScale = 0.5; }
  setSize(w, h) { super.setSize(Math.max(1, Math.round(w * this.resScale)), Math.max(1, Math.round(h * this.resScale))); }
  overrideVisibility() {
    const cache = this._visibilityCache;
    this.scene.traverse((o) => {
      cache.set(o, o.visible);
      if (o.isPoints || o.isLine || o.userData.noAO) o.visible = false;
    });
  }
}

const GradeShader = {
  name: 'HWGrade',
  uniforms: {
    tDiffuse: { value: null },
    uSat: { value: 1.06 }, uContrast: { value: 1.05 },
    uShadowTint: { value: new THREE.Vector3(0.985, 0.995, 1.03) }, uHighTint: { value: new THREE.Vector3(1.03, 1.0, 0.965) },
    uVignette: { value: 0.14 }, uAspect: { value: 1 },
  },
  vertexShader: /* glsl */`varying vec2 vUv; void main() { vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4( position, 1.0 ); }`,
  fragmentShader: /* glsl */`
    uniform sampler2D tDiffuse; uniform float uSat, uContrast, uVignette, uAspect; uniform vec3 uShadowTint, uHighTint;
    varying vec2 vUv;
    void main() {
      vec4 c = texture2D( tDiffuse, vUv );            // display-referred (after tone mapping)
      float l = dot( c.rgb, vec3( 0.2126, 0.7152, 0.0722 ) );
      c.rgb = mix( vec3( l ), c.rgb, uSat );
      c.rgb = ( c.rgb - 0.5 ) * uContrast + 0.5;       // gentle S
      c.rgb *= mix( uShadowTint, uHighTint, smoothstep( 0.15, 0.75, l ) );   // split toning: cool shadows, warm highs
      vec2 q = ( vUv - 0.5 ) * vec2( uAspect, 1.0 );
      c.rgb *= 1.0 - uVignette * smoothstep( 0.35, 1.05, length( q ) );
      gl_FragColor = vec4( clamp( c.rgb, 0.0, 1.0 ), c.a );
    }`,
};

export class Post {
  constructor(renderer, scene, camera) {
    this.renderer = renderer; this.scene = scene; this.camera = camera;
    const rt = new THREE.WebGLRenderTarget(1, 1, { type: THREE.HalfFloatType, samples: 4 });
    this.composer = new EffectComposer(renderer, rt);
    this.render = new RenderPass(scene, camera);
    this.gtao = new LeanGTAOPass(scene, camera, 2, 2);
    this.gtao.blendIntensity = 0.6;
    this.gtao.updateGtaoMaterial({ radius: 0.6, distanceExponent: 1.4, thickness: 1.2, scale: 1.0, samples: 12, distanceFallOff: 1.0 });
    this.gtao.updatePdMaterial({ lumaPhi: 10, depthPhi: 2, normalPhi: 3, radius: 6, rings: 2, samples: 12 });
    this.bloom = new UnrealBloomPass(new THREE.Vector2(256, 256), 0.5, 0.55, 0.95);
    this.output = new OutputPass();
    this.grade = new ShaderPass(GradeShader);
    this.fxaa = new ShaderPass(FXAAShader);
    this.smaa = new SMAAPass(2, 2);
    for (const p of [this.render, this.gtao, this.bloom, this.output, this.grade, this.fxaa, this.smaa]) this.composer.addPass(p);
    this.enabled = false;
    this.tier = null;
  }

  // tier: {post, ao, aoScale, bloom, aa: 'msaa'|'fxaa'|'smaa'|'none'}
  configure(tier) {
    this.tier = tier;
    this.enabled = !!tier.post;
    this.gtao.enabled = !!tier.ao;
    this.gtao.resScale = tier.aoScale || 0.5;
    if (tier.ao) this.gtao.updateGtaoMaterial({ samples: tier.aoSamples || 12 });
    this.bloom.enabled = !!tier.bloom;
    this.grade.enabled = true;
    this.fxaa.enabled = tier.aa === 'fxaa';
    this.smaa.enabled = tier.aa === 'smaa';
    this.composer.renderTarget1.samples = this.composer.renderTarget2.samples = tier.aa === 'msaa' || tier.aa === 'smaa' ? 4 : 0;
    this.composer.renderTarget1.dispose(); this.composer.renderTarget2.dispose(); // re-allocated at next render
  }

  setSize(w, h, pr) {
    this.composer.setPixelRatio(pr);
    this.composer.setSize(w, h);
    const W = Math.round(w * pr), H = Math.round(h * pr);
    this.fxaa.material.uniforms.resolution.value.set(1 / W, 1 / H);
    this.grade.material.uniforms.uAspect.value = w / h;
  }

  draw(dt) { this.composer.render(dt); }
}
