// Player character: assets/character.glb (rigged human by the character agent: summer + winter outfits, clips idle,
// walk, run, jump, sled_sit, sled_lean_left/right, sled_air, superman, spread_eagle, grab|sled_grab) and the sled
// (assets/sled.glb with a "SledSeat" empty, or a "Sled" node inside character.glb). Falls back to a simple
// placeholder figure / sled when the GLBs are missing or fail to load.
import * as THREE from 'three';
import { loadGLB } from './util.js';

const CLIP_SPEED = { walk: 1.3, run: 3.2 };   // m/s the in-place clips were authored for (character/clips.py)

function placeholderFigure() {
  const g = new THREE.Group(); g.name = 'PlaceholderFigure';
  const mat = (c, r = 0.8) => new THREE.MeshStandardMaterial({ color: c, roughness: r });
  const M = { skin: mat(0xd2a07c, 0.6), top: mat(0x3d5a80), legs: mat(0x2b2f3a), shoe: mat(0x222222), hat: mat(0xb03a2e) };
  const part = (geo, m, x, y, z) => { const o = new THREE.Mesh(geo, m); o.position.set(x, y, z); o.castShadow = true; g.add(o); return o; };
  const legs = [part(new THREE.CapsuleGeometry(0.075, 0.7, 4, 8), M.legs, -0.1, 0.45, 0), part(new THREE.CapsuleGeometry(0.075, 0.7, 4, 8), M.legs, 0.1, 0.45, 0)];
  part(new THREE.CapsuleGeometry(0.17, 0.45, 4, 10), M.top, 0, 1.15, 0);
  const arms = [part(new THREE.CapsuleGeometry(0.055, 0.55, 4, 8), M.top, -0.25, 1.1, 0), part(new THREE.CapsuleGeometry(0.055, 0.55, 4, 8), M.top, 0.25, 1.1, 0)];
  part(new THREE.SphereGeometry(0.11, 14, 10), M.skin, 0, 1.6, 0);
  const hat = part(new THREE.SphereGeometry(0.115, 12, 8, 0, Math.PI * 2, 0, Math.PI / 2), M.hat, 0, 1.63, 0);
  g.userData.parts = { legs, arms, hat, M };
  return g;
}

function placeholderSled() {
  const g = new THREE.Group(); g.name = 'PlaceholderSled';
  const m = new THREE.MeshStandardMaterial({ color: 0xc4231c, roughness: 0.35, metalness: 0 });
  const shape = new THREE.Shape();
  shape.moveTo(-0.3, -0.62); shape.lineTo(0.3, -0.62); shape.lineTo(0.3, 0.45); shape.quadraticCurveTo(0.3, 0.62, 0, 0.66); shape.quadraticCurveTo(-0.3, 0.62, -0.3, 0.45); shape.closePath();
  const geo = new THREE.ExtrudeGeometry(shape, { depth: 0.1, bevelEnabled: true, bevelSize: 0.02, bevelThickness: 0.02, bevelSegments: 2 });
  geo.rotateX(Math.PI / 2); geo.translate(0, 0.12, 0);
  const body = new THREE.Mesh(geo, m); body.castShadow = true; g.add(body);
  const seat = new THREE.Object3D(); seat.name = 'SledSeat'; seat.position.set(0, 0.03, -0.18); g.add(seat);
  return g;
}

export class Character {
  constructor() {
    this.root = new THREE.Group(); this.root.name = 'Player';
    this.model = null; this.mixer = null; this.actions = {}; this.isGLB = false;
    this.sledRoot = new THREE.Group(); this.sledRoot.name = 'SledRig';
    this.sled = null; this.seat = null;
    this.mode = 'walk'; this.season = 'summer';
    this.renderY = null; this.phase = 0;
    this.trickAction = null; this.trickName = null;
    this.head = null;
    this.tumble = new THREE.Group(); this.tumble.name = 'TumblePivot';
    this.lean = 0;
  }

  async load(manifest, onProgress) {
    const v = '?v=' + encodeURIComponent(manifest.generated || '');
    let gltf = null, sledGltf = null;
    if (manifest.character) {
      try { gltf = await loadGLB(manifest.character.file + v, onProgress); } catch (e) { console.warn('character.glb failed, placeholder figure', e); }
    }
    if (manifest.sled) {
      try { sledGltf = await loadGLB(manifest.sled.file + v); } catch (e) { console.warn('sled.glb failed, placeholder sled', e); }
    }
    if (gltf) {
      this.isGLB = true;
      this.model = gltf.scene;
      this.mixer = new THREE.AnimationMixer(this.model);
      for (const clip of gltf.animations) {
        const name = clip.name === 'sled_grab' ? 'grab' : clip.name;
        const a = this.mixer.clipAction(clip);
        a.enabled = true; a.setEffectiveWeight(0); a.play();
        this.actions[name] = a;
      }
      for (const n of ['jump', 'superman', 'spread_eagle', 'grab']) if (this.actions[n]) { this.actions[n].setLoop(THREE.LoopOnce, 1); this.actions[n].clampWhenFinished = true; this.actions[n].stop(); }
      this.model.traverse((o) => {
        if (o.isMesh) { o.castShadow = true; o.receiveShadow = true; o.frustumCulled = false; }
        if (o.isBone && /^head$/i.test(o.name)) this.head = o;
      });
      // inside character.glb there may be a sled too
      const s = this.model.getObjectByName('Sled');
      if (s && !sledGltf) { s.parent.remove(s); this.sled = s; }
    } else {
      this.model = placeholderFigure();
    }
    this.root.add(this.tumble);
    this.tumble.add(this.model);
    if (sledGltf) this.sled = sledGltf.scene;
    if (!this.sled) this.sled = placeholderSled();
    this.sled.traverse((o) => { if (o.isMesh) { o.castShadow = true; o.receiveShadow = true; } });
    this.seat = this.sled.getObjectByName('SledSeat') || this.sled;
    this.sledRoot.add(this.sled);
    this.sledRoot.visible = false;
    this.setSeason('summer');
    this.setWeights({ idle: 1 });
    return this;
  }

  setSeason(season) {
    this.season = season;
    if (!this.isGLB) { const P = this.model.userData.parts; P.hat.visible = season === 'winter'; P.M.top.color.set(season === 'winter' ? 0x1f4e79 : 0x8a9a5b); return; }
    this.model.traverse((o) => {
      if (!o.isMesh && !o.isGroup) return;
      const n = o.name;
      if (/^Summer_|Hair_Cap_Summer/.test(n)) o.visible = season === 'summer';
      else if (/^Winter_|Hair_Cap_Winter/.test(n)) o.visible = season === 'winter';
      else if (/^Body_Arms/.test(n)) o.visible = season === 'summer';
    });
  }

  setWeights(w) {
    for (const [k, a] of Object.entries(this.actions)) {
      if (['jump', 'superman', 'spread_eagle', 'grab'].includes(k) && a === this.trickAction) continue;
      const target = w[k] || 0;
      a.setEffectiveWeight(target);
    }
  }

  // smoothed weights (exponential blend toward targets)
  blend(dt, w, k = 8) {
    this._w = this._w || {};
    const f = 1 - Math.exp(-k * dt);
    for (const name of Object.keys(this.actions)) {
      if (this.trickAction && this.actions[name] === this.trickAction) continue;
      const cur = this._w[name] || 0, tgt = w[name] || 0;
      const v = dt === 0 ? tgt : cur + (tgt - cur) * f;
      this._w[name] = v;
      this.actions[name].setEffectiveWeight(v);
    }
  }

  setMode(mode) {
    if (mode === this.mode) return;
    this.mode = mode;
    this.stopTrick();
    if (mode === 'sled') {
      this.sledRoot.visible = true;
      this.seat.add(this.root);
      this.root.position.set(0, 0, 0); this.root.rotation.set(0, 0, 0);
      this.tumble.position.set(0, 0, 0); this.tumble.quaternion.identity();
      this.blend(0, { sled_sit: 1 });
    } else {
      this.sledRoot.visible = false;
      if (this.root.parent) this.root.parent.remove(this.root);
      this.tumble.quaternion.identity(); this.tumble.position.set(0, 0, 0);
      this.renderY = null;
      this.blend(0, { idle: 1 });
    }
  }

  // ---------------------------------------------------------------- walk
  updateWalk(dt, pos, facing, speed, grounded) {
    if (this.renderY === null || Math.abs(pos.y - this.renderY) > 2) this.renderY = pos.y;
    this.renderY += (pos.y - this.renderY) * (1 - Math.exp(-(pos.y > this.renderY ? 20 : 28) * dt));
    this.root.position.set(pos.x, this.renderY, pos.z);
    this.root.rotation.y = facing;
    if (!this.isGLB) { this.animatePlaceholder(dt, speed, grounded); return; }
    const s = speed;
    const wWalk = THREE.MathUtils.smoothstep(s, 0.08, 0.7) * (1 - THREE.MathUtils.smoothstep(s, 2.0, 3.0));
    const wRun = THREE.MathUtils.smoothstep(s, 2.0, 3.0);
    const air = !grounded;
    const w = air ? { jump: 1, idle: 0, walk: 0.15 * wWalk, run: 0.15 * wRun } : { idle: 1 - wWalk - wRun, walk: wWalk, run: wRun };
    if (this.actions.walk) this.actions.walk.timeScale = THREE.MathUtils.clamp(s / CLIP_SPEED.walk, 0.6, 1.6);
    if (this.actions.run) this.actions.run.timeScale = THREE.MathUtils.clamp(s / CLIP_SPEED.run, 0.7, 1.4);
    // jump: the clip's flight section while airborne
    const j = this.actions.jump;
    if (j) {
      if (air && !this._jumping) { this._jumping = true; j.reset(); j.time = 0.38; j.timeScale = 1; j.play(); }
      if (!air && this._jumping) this._jumping = false;
    }
    this.blend(dt, w, 10);
    this.mixer.update(dt);
  }

  animatePlaceholder(dt, speed, grounded) {
    const P = this.model.userData.parts;
    this.phase += speed * dt * 4.2;
    const sw = Math.min(1, speed / 1.4) * 0.5;
    P.legs[0].rotation.x = Math.sin(this.phase) * sw; P.legs[1].rotation.x = -Math.sin(this.phase) * sw;
    P.arms[0].rotation.x = -Math.sin(this.phase) * sw * 0.8; P.arms[1].rotation.x = Math.sin(this.phase) * sw * 0.8;
    if (!grounded) { P.legs[0].rotation.x = -0.4; P.legs[1].rotation.x = 0.3; }
  }

  // ---------------------------------------------------------------- sled
  // place the sled rig (world) from the physics state and animate the rider
  updateSled(dt, game, steer) {
    this.sledRoot.position.copy(game.pos);
    this.sledRoot.quaternion.copy(game.quat);
    const w = game.wipe;
    if (w) {
      // rider tumbles separately from the sled
      if (this.root.parent !== this.tumbleWorld) {
        this.tumbleWorld = this.tumbleWorld || new THREE.Group();
        if (!this.tumbleWorld.parent && this.sledRoot.parent) this.sledRoot.parent.add(this.tumbleWorld);
        this.tumbleWorld.add(this.root);
        this.root.position.set(0, 0, 0); this.root.rotation.set(0, 0, 0);
        this.stopTrick();
      }
      this.tumbleWorld.position.copy(w.riderPos);
      this.tumble.position.set(0, 0.0, 0);
      this.tumble.quaternion.setFromAxisAngle(w.axis, w.rot);
      if (this.isGLB) { this.blend(dt, { sled_air: 1 }, 6); this.mixer.update(dt); }
      return;
    }
    if (this.root.parent !== this.seat) {
      this.seat.add(this.root);
      this.root.position.set(0, 0, 0); this.root.rotation.set(0, 0, 0);
      this.tumble.quaternion.identity(); this.tumble.position.set(0, 0, 0);
    }
    if (!this.isGLB) {
      const P = this.model.userData.parts;
      this.model.rotation.x = game.trick ? -0.9 : 0; this.model.position.y = -0.45; P.legs.forEach((l) => (l.rotation.x = -1.4));
      this.model.rotation.z = steer * 0.25;
      return;
    }
    this.lean += (steer - this.lean) * (1 - Math.exp(-6 * dt));
    const air = !game.grounded;
    // tricks
    if (game.trick && this.trickName !== game.trick.name) this.playTrick(game.trick.name, game.trick.dur);
    if (!game.trick && this.trickAction) this.stopTrick();
    const L = Math.max(0, -this.lean), R = Math.max(0, this.lean);
    const base = air ? { sled_air: 1 } : { sled_sit: 1 - Math.min(1, L + R), sled_lean_left: L, sled_lean_right: R };
    if (this.trickAction) for (const k of Object.keys(base)) base[k] *= 0.0;
    this.blend(dt, base, air ? 7 : 9);
    this.mixer.update(dt);
  }

  playTrick(name, dur) {
    const a = this.actions[name];
    this.stopTrick();
    if (!a) return;
    a.reset();
    a.setLoop(THREE.LoopOnce, 1); a.clampWhenFinished = true;
    a.timeScale = a.getClip().duration / dur;
    a.setEffectiveWeight(1);
    a.play();
    this._w = this._w || {}; this._w[name] = 1;
    this.trickAction = a; this.trickName = name;
  }

  stopTrick() {
    // the blend() smoothing fades the clip out from here on
    if (!this.trickAction) return;
    this.trickAction = null; this.trickName = null;
  }

  headWorld(out) {
    if (this.head) return this.head.getWorldPosition(out);
    return this.root.getWorldPosition(out).add(new THREE.Vector3(0, 1.6, 0));
  }
}
