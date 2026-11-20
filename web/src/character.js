// Original procedural traveller: indigo short coat (haori) over a light kimono, ochre sash, grey leggings,
// straw sandals, a wide shallow hat and a small cloth bundle on the back. Built from primitives only.
import * as THREE from 'three';

const mat = (c, r = 0.85) => new THREE.MeshStandardMaterial({ color: c, roughness: r, metalness: 0 });

function capsule(r, len, m) {
  const g = new THREE.CapsuleGeometry(r, len, 4, 10);
  g.translate(0, -len / 2 - r, 0);          // pivot at the top
  const mesh = new THREE.Mesh(g, m);
  mesh.castShadow = true;
  return mesh;
}

export class Traveller {
  constructor() {
    const M = {
      coat: mat(0x2f3f63), coatDark: mat(0x23304d), kimono: mat(0xc9bfa8), sash: mat(0xb8862e, 0.7),
      skin: mat(0xe0b08c, 0.7), hair: mat(0x1d1a18, 0.9), legging: mat(0x56575c), sandal: mat(0xb59a63),
      hat: mat(0xc8a865, 0.9), hatBand: mat(0x6b3a22), bundle: mat(0x7c2f2a, 0.8), cord: mat(0xe9dcc0),
    };
    this.M = M;
    const root = new THREE.Group();
    root.name = 'Traveller';
    this.root = root;
    const body = new THREE.Group();          // bobbing + leaning part
    root.add(body);
    this.body = body;

    // ---- legs (hip pivots)
    this.legs = [];
    for (const side of [-1, 1]) {
      const hip = new THREE.Group();
      hip.position.set(0.095 * side, 0.86, 0);
      const thigh = capsule(0.068, 0.3, M.kimono);
      hip.add(thigh);
      const knee = new THREE.Group();
      knee.position.y = -0.42;
      hip.add(knee);
      const shin = capsule(0.058, 0.3, M.legging);
      knee.add(shin);
      const foot = new THREE.Mesh(new THREE.BoxGeometry(0.1, 0.035, 0.24), M.sandal);
      foot.position.set(0, -0.42, 0.045);
      foot.castShadow = true;
      const toe = new THREE.Mesh(new THREE.BoxGeometry(0.085, 0.05, 0.12), M.legging);
      toe.position.set(0, 0.035, 0.0);
      foot.add(toe);
      knee.add(foot);
      body.add(hip);
      this.legs.push({ hip, knee, side });
    }

    // ---- torso
    const torso = new THREE.Group();
    torso.position.y = 0.86;
    body.add(torso);
    this.torso = torso;
    const kimonoSkirt = new THREE.Mesh(new THREE.CylinderGeometry(0.16, 0.2, 0.34, 14, 1, true), M.kimono);
    kimonoSkirt.position.y = -0.1; kimonoSkirt.castShadow = true;
    kimonoSkirt.material = M.kimono.clone(); kimonoSkirt.material.side = THREE.DoubleSide;
    torso.add(kimonoSkirt);
    const chest = new THREE.Mesh(new THREE.CylinderGeometry(0.175, 0.16, 0.5, 14), M.kimono);
    chest.position.y = 0.27; chest.castShadow = true;
    torso.add(chest);
    // haori coat: open front shell over the chest + skirt
    const coatG = new THREE.CylinderGeometry(0.195, 0.235, 0.66, 18, 1, true, Math.PI * 0.16, Math.PI * 1.68);
    const coatMat = M.coat.clone(); coatMat.side = THREE.DoubleSide;
    const coat = new THREE.Mesh(coatG, coatMat);
    coat.position.y = 0.17; coat.castShadow = true;
    coat.rotation.y = Math.PI;               // opening to the front (+z)
    torso.add(coat);
    this.coat = coat;
    const collar = new THREE.Mesh(new THREE.TorusGeometry(0.12, 0.028, 6, 16, Math.PI * 1.3), M.coatDark);
    collar.position.set(0, 0.5, 0.02); collar.rotation.set(Math.PI / 2 - 0.35, 0, Math.PI * 0.5 + Math.PI * 0.35);
    torso.add(collar);
    const sash = new THREE.Mesh(new THREE.CylinderGeometry(0.168, 0.168, 0.075, 16), M.sash);
    sash.position.y = 0.06; torso.add(sash);
    const knot = new THREE.Mesh(new THREE.BoxGeometry(0.07, 0.06, 0.04), M.sash);
    knot.position.set(0.05, 0.06, 0.17); torso.add(knot);
    // cloth bundle on the back (furoshiki) with a cord across the chest
    const bundle = new THREE.Mesh(new THREE.SphereGeometry(0.15, 12, 8), M.bundle);
    bundle.scale.set(1.15, 0.85, 0.65); bundle.position.set(0, 0.33, -0.23); bundle.castShadow = true;
    torso.add(bundle);
    const bk = new THREE.Mesh(new THREE.SphereGeometry(0.045, 8, 6), M.bundle);
    bk.position.set(0, 0.45, -0.2); torso.add(bk);
    const cord = new THREE.Mesh(new THREE.TorusGeometry(0.205, 0.012, 4, 24), M.cord);
    cord.position.set(0, 0.36, -0.03); cord.rotation.set(Math.PI / 2, 0.55, 0); cord.scale.set(1, 1.15, 1);
    torso.add(cord);

    // ---- arms (shoulder pivots) with wide sleeves
    this.arms = [];
    for (const side of [-1, 1]) {
      const sh = new THREE.Group();
      sh.position.set(0.215 * side, 0.47, 0);
      const sleeve = new THREE.Mesh(new THREE.CylinderGeometry(0.075, 0.115, 0.3, 10), M.coat);
      sleeve.position.y = -0.15; sleeve.castShadow = true;
      sh.add(sleeve);
      const elbow = new THREE.Group(); elbow.position.y = -0.27; sh.add(elbow);
      const fore = capsule(0.042, 0.17, M.skin); elbow.add(fore);
      const hand = new THREE.Mesh(new THREE.SphereGeometry(0.05, 8, 6), M.skin);
      hand.position.y = -0.27; hand.scale.set(0.9, 1.1, 0.8); elbow.add(hand);
      sh.rotation.z = 0.12 * side;
      torso.add(sh);
      this.arms.push({ sh, elbow, side });
    }

    // ---- head + hat
    const neck = new THREE.Group();
    neck.position.y = 0.55;
    torso.add(neck);
    this.neck = neck;
    const head = new THREE.Mesh(new THREE.SphereGeometry(0.105, 16, 12), M.skin);
    head.position.y = 0.13; head.scale.set(0.95, 1.08, 1); head.castShadow = true;
    neck.add(head);
    const hair = new THREE.Mesh(new THREE.SphereGeometry(0.11, 16, 10, 0, Math.PI * 2, 0, Math.PI * 0.55), M.hair);
    hair.position.set(0, 0.145, -0.012); hair.rotation.x = -0.35;
    neck.add(hair);
    const hat = new THREE.Group();
    hat.position.y = 0.235; hat.rotation.x = -0.08;
    const brim = new THREE.Mesh(new THREE.ConeGeometry(0.29, 0.13, 24, 1, true), M.hat.clone());
    brim.material.side = THREE.DoubleSide; brim.castShadow = true;
    hat.add(brim);
    const crown = new THREE.Mesh(new THREE.CylinderGeometry(0.09, 0.11, 0.05, 16), M.hat);
    crown.position.y = -0.03; hat.add(crown);
    const band = new THREE.Mesh(new THREE.TorusGeometry(0.105, 0.01, 4, 20), M.hatBand);
    band.rotation.x = Math.PI / 2; band.position.y = -0.045; hat.add(band);
    const tip = new THREE.Mesh(new THREE.SphereGeometry(0.018, 6, 4), M.hatBand);
    tip.position.y = 0.065; hat.add(tip);
    neck.add(hat);

    root.traverse((o) => { if (o.isMesh) { o.castShadow = true; o.receiveShadow = true; } });

    this.phase = 0;
    this.idleT = 0;
    this.lean = 0;
    this.renderY = null;
    this.prevSpeed = 0;
  }

  // speed: horizontal m/s; run speed ~4.6
  update(dt, pos, facing, speed, grounded) {
    // smooth visual height (step-ups snap physically; the body glides)
    if (this.renderY === null || Math.abs(pos.y - this.renderY) > 2) this.renderY = pos.y;
    this.renderY += (pos.y - this.renderY) * (1 - Math.exp(-(pos.y > this.renderY ? 22 : 30) * dt));
    this.root.position.set(pos.x, this.renderY, pos.z);
    this.root.rotation.y = facing;

    const s = Math.min(speed, 5.5);
    const run = THREE.MathUtils.smoothstep(s, 2.2, 3.8);
    const walk = THREE.MathUtils.smoothstep(s, 0.05, 0.6);
    const stride = THREE.MathUtils.lerp(1.25, 2.1, run);   // m per full cycle
    this.phase += (s / stride) * Math.PI * 2 * dt;
    this.idleT += dt;
    const ph = this.phase;
    const sw = (0.5 + 0.28 * run) * walk;

    for (const L of this.legs) {
      const p = ph + (L.side > 0 ? 0 : Math.PI);
      L.hip.rotation.x = -Math.sin(p) * sw;
      L.knee.rotation.x = Math.max(0, Math.cos(p)) * (0.35 + 0.9 * run) * walk + 0.05;
    }
    for (const A of this.arms) {
      const p = ph + (A.side > 0 ? Math.PI : 0);
      A.sh.rotation.x = -Math.sin(p) * (0.32 + 0.4 * run) * walk + Math.sin(this.idleT * 1.6) * 0.02 * (1 - walk);
      A.elbow.rotation.x = -(0.15 + 0.85 * run) * walk - 0.12;
      A.sh.rotation.z = (0.12 + 0.05 * run) * A.side;
    }
    const bob = Math.abs(Math.cos(ph)) * (0.035 + 0.04 * run) * walk;
    const breathe = Math.sin(this.idleT * 2.0) * 0.006 * (1 - walk);
    this.body.position.y = bob - 0.02 * walk + breathe;
    // lean into the motion and into acceleration
    const acc = (s - this.prevSpeed) / Math.max(dt, 1e-3);
    this.prevSpeed = s;
    const targetLean = 0.05 * walk + 0.14 * run + THREE.MathUtils.clamp(acc * 0.015, -0.08, 0.1);
    this.lean += (targetLean - this.lean) * (1 - Math.exp(-6 * dt));
    this.torso.rotation.x = this.lean;
    this.torso.rotation.y = Math.sin(ph) * 0.08 * walk;
    this.coat.rotation.x = -this.lean * 0.4;
    this.coat.scale.set(1 + 0.04 * run, 1, 1 + 0.06 * run);
    this.neck.rotation.x = -this.lean * 0.6 + Math.sin(this.idleT * 0.7) * 0.02 * (1 - walk);
    this.neck.rotation.y = Math.sin(this.idleT * 0.37) * 0.25 * (1 - walk);
    if (!grounded) { for (const L of this.legs) L.knee.rotation.x = 0.5; }
  }
}
