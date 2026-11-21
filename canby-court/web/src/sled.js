// Sled mini-game physics + rules (winter). The sled is a point mass riding the collider surfaces (snow terrain +
// kicker meshes) sampled by BVH ray casts:
//   grounded: gravity along the surface, Coulomb snow friction (mu ~0.065 packed track, more off-track, brake, stop
//             zone), quadratic air drag, lateral grip (carve) with a skid limit, lean steering, hand paddling when slow
//   takeoff : when the surface falls away faster than gravity can follow (kicker lips) -> ballistic flight
//   air     : gravity + drag; Pop/Boost = one extra impulse, timed at the lip (window before/after takeoff, timing
//             bonus); tricks (Superman, Spread eagle, Grab) score only if finished before touch-down
//   landing : impact speed into the surface, sideways landings and unfinished tricks -> wipeout (tumble, reset to
//             the last checkpoint); obstacles (houses, trunks, hedges) -> bounce or crash; hay bales absorb
//   run-out : deep snow stop zone before the berm; the run ends when the sled stops past the last kicker
// Fixed 1/120 s sub-steps; simulate() runs the same physics headless (tests, tuning).
import * as THREE from 'three';
import { SLED } from './config.js';
import { angDiff, clamp } from './util.js';

const H = 1 / 120;
const UP = new THREE.Vector3(0, 1, 0);
const _r = new THREE.Ray(), _v = new THREE.Vector3(), _n = new THREE.Vector3(), _f = new THREE.Vector3(), _l = new THREE.Vector3(), _a = new THREE.Vector3();
const _sph = new THREE.Sphere(), _tp = new THREE.Vector3(), _box = new THREE.Box3();

// run path helper (local 2D polyline): projection -> arc length + signed lateral offset
export class RunPath {
  constructor(pts) {
    this.p = pts; this.cum = [0];
    for (let i = 1; i < pts.length; i++) this.cum.push(this.cum[i - 1] + Math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]));
    this.length = this.cum[this.cum.length - 1];
  }
  project(x, y) {
    let best = { d: Infinity, s: 0, lat: 0, i: 0 };
    for (let i = 0; i < this.p.length - 1; i++) {
      const [ax, ay] = this.p[i], [bx, by] = this.p[i + 1];
      const dx = bx - ax, dy = by - ay, L2 = dx * dx + dy * dy;
      let t = ((x - ax) * dx + (y - ay) * dy) / L2;
      const tc = clamp(t, 0, 1);
      const px = ax + dx * tc, py = ay + dy * tc, d = Math.hypot(x - px, y - py);
      if (d < best.d) {
        const L = Math.sqrt(L2);
        best = { d, s: this.cum[i] + tc * L + (i === this.p.length - 2 && t > 1 ? (t - 1) * L : 0) + (i === 0 && t < 0 ? t * L : 0), lat: ((x - ax) * dy - (y - ay) * dx) / L, i };
      }
    }
    return best;
  }
  at(s) {
    s = clamp(s, 0, this.length);
    let i = 0; while (i < this.cum.length - 2 && this.cum[i + 1] < s) i++;
    const t = (s - this.cum[i]) / Math.max(1e-6, this.cum[i + 1] - this.cum[i]);
    const [ax, ay] = this.p[i], [bx, by] = this.p[i + 1];
    return [ax + (bx - ax) * t, ay + (by - ay) * t];
  }
}

export class SledGame {
  constructor({ jumps, berm, path, onEvent = () => {} }) {
    this.jumps = jumps;              // jumpMeta() (local coords)
    this.berm = berm;
    this.path = new RunPath(path);
    this.bermArc = this.path.project(berm.center_local[0], berm.center_local[1]).s;
    this.lastJumpArc = Math.max(...jumps.map((j) => this.path.project(j.lip[0], j.lip[1]).s));
    this.checkpointArcs = [0, ...jumps.map((j) => this.path.project(j.start[0], j.start[1]).s - 16)].filter((a, i) => i === 0 || a > 4);
    this.onEvent = onEvent;
    this.col = null;
    this.pos = new THREE.Vector3(); this.vel = new THREE.Vector3();
    this.normal = new THREE.Vector3(0, 1, 0);
    this.heading = 0;
    this.quat = new THREE.Quaternion();
    this.active = false;
    this.reset();
  }

  setCollider(col) {
    this.col = col;
    this.objId = col.colGeom.attributes.objId; this.index = col.colGeom.index;
  }
  infoOf(faceIndex) { const a = this.index.getX(faceIndex * 3); return this.col.objInfo[Math.round(this.objId.getX(a))] || { walkable: true }; }

  // ground under world (x, z) near height y: {y, n, info} (first hit from above y + up)
  ground(x, y, z, up = 1.2, down = 6) {
    _r.origin.set(x, y + up, z); _r.direction.set(0, -1, 0);
    const hit = this.col.bvh.raycastFirst(_r, THREE.DoubleSide, 0, up + down);
    if (!hit) return null;
    return { y: hit.point.y, info: this.infoOf(hit.faceIndex), faceIndex: hit.faceIndex };
  }
  // smoothed normal from four samples around (x, z) along the heading
  groundNormal(x, y, z, out) {
    const s = 0.45, fx = Math.sin(this.heading) * s, fz = Math.cos(this.heading) * s;
    const gf = this.ground(x + fx, y, z + fz), gb = this.ground(x - fx, y, z - fz);
    const gr = this.ground(x - fz, y, z + fx), gl = this.ground(x + fz, y, z - fx);
    if (!gf || !gb || !gr || !gl) return out.set(0, 1, 0);
    const a = _a.set(2 * fx, gf.y - gb.y, 2 * fz);
    const b = _tp.set(-2 * fz, gr.y - gl.y, 2 * fx);
    out.crossVectors(b, a).normalize();
    if (out.y < 0) out.negate();
    return out;
  }

  // ---------------------------------------------------------------- run control
  reset() {
    this.grounded = true; this.airTime = 0; this.trick = null; this.wipe = null;
    this.popUsed = false; this.popBuffered = null; this.takeoff = null;
    this.time = 0; this.runTime = 0; this.score = 0; this.jumpLog = []; this.events = [];
    this.finished = null; this.stillT = 0; this.countdown = 0; this.lastCheckpoint = null; this.cpIndex = 0;
    this.skid = 0; this.maxSpeed = 0; this.surfaceKind = 'snow'; this.arc = 0; this.lat = 0;
    this.airTricks = []; this.started = false;
  }

  startAt(local, terrainH, heading, { countdown = 2.4 } = {}) {
    this.reset();
    this.heading = heading;
    const g = this.ground(local[0], terrainH + 2, -local[1], 3, 8);
    this.pos.set(local[0], g ? g.y : terrainH, -local[1]);
    this.vel.set(0, 0, 0);
    this.groundNormal(this.pos.x, this.pos.y, this.pos.z, this.normal);
    this.countdown = countdown;
    this.active = true;
    this.startState = { pos: this.pos.clone(), heading };
    this.lastCheckpoint = { pos: this.pos.clone(), vel: new THREE.Vector3(), heading, arc: 0, idx: 0 };
    this.updateOrientation(1);
    this.emit('start', {});
  }

  restartRun() {
    const s = this.startState;
    if (!s) return;
    this.reset();
    this.pos.copy(s.pos); this.heading = s.heading; this.vel.set(0, 0, 0);
    this.countdown = 2.4; this.active = true;
    this.lastCheckpoint = { pos: s.pos.clone(), vel: new THREE.Vector3(), heading: s.heading, arc: 0, idx: 0 };
    this.groundNormal(this.pos.x, this.pos.y, this.pos.z, this.normal);
    this.updateOrientation(1);
    this.emit('start', { restart: true });
  }

  emit(type, data) {
    const e = { type, t: +this.time.toFixed(3), ...data };
    this.events.push(e);
    if (this.events.length > 400) this.events.shift();
    this.onEvent(e);
  }

  // ---------------------------------------------------------------- actions
  onRamp() {
    const x = this.pos.x, y = -this.pos.z;
    for (const j of this.jumps) {
      const dx = x - j.start[0], dy = y - j.start[1];
      const s = dx * j.dir[0] + dy * j.dir[1], w = -dx * j.dir[1] + dy * j.dir[0];
      if (s > -0.5 && s < j.L + 0.6 && Math.abs(w) < j.width / 2 + 1.0) return { j, s };
    }
    return null;
  }

  boost() {
    if (!this.active || this.wipe || this.finished || this.countdown > 0) return 'ignored';
    if (this.popUsed) return 'used';
    if (this.grounded) {
      const r = this.onRamp();
      if (r) { this.popBuffered = { t: this.time, jump: r.j.id }; return 'buffered'; }
      // flat ground: small ollie (no trick window worth speaking of)
      this.vel.addScaledVector(this.normal, SLED.ollie);
      this.grounded = false; this.popUsed = true; this.takeoff = { t: this.time, y: this.pos.y, jump: null, pos: this.pos.clone(), ollie: true };
      this.airTime = 0; this.airTricks = []; this.apexY = this.pos.y;
      this.emit('pop', { quality: 0, label: 'Ollie', points: 0 });
      return 'ollie';
    }
    if (this.takeoff && this.time - this.takeoff.t <= SLED.popWindowAfter) {
      const q = 1 - (this.time - this.takeoff.t) / SLED.popWindowAfter;
      this.applyPop(q * q);
      return 'late';
    }
    return 'missed';
  }

  applyPop(q) {
    this.popUsed = true;
    const dv = SLED.popBase + SLED.popBonus * q;
    const f = _f.set(this.vel.x, 0, this.vel.z); const hs = f.length(); if (hs > 0.1) f.divideScalar(hs);
    this.vel.y += dv * 0.95;
    this.vel.addScaledVector(f, dv * 0.22);
    const pts = Math.round(50 + 150 * q);
    const label = q > 0.75 ? 'Perfect pop!' : q > 0.35 ? 'Good pop' : 'Pop';
    this.pendingPop = { points: pts, label, q };
    this.emit('pop', { quality: +q.toFixed(2), label, points: pts });
  }

  trickPress(name) {
    if (!this.active || this.grounded || this.wipe || this.trick || !SLED.tricks[name]) return false;
    if (this.airTime < 0.06) return false;
    const T = SLED.tricks[name];
    this.trick = { name, t: 0, dur: T.dur, label: T.label, points: T.points };
    this.emit('trick-start', { name, label: T.label });
    return true;
  }

  // ---------------------------------------------------------------- update
  // input: {steer -1..1 (right +), brake 0..1, paddle 0..1}
  update(dt, input) {
    if (!this.active) return;
    let t = dt;
    while (t > 1e-6) { const h = Math.min(H, t); this.step(h, input); t -= h; }
  }

  step(h, input) {
    this.time += h;
    if (this.countdown > 0) {
      this.countdown -= h;
      if (this.countdown <= 0) {
        this.countdown = 0; this.started = true;
        this.vel.set(Math.sin(this.heading), 0, Math.cos(this.heading)).multiplyScalar(SLED.push);
        this.emit('go', {});
      }
      this.updateOrientation(h);
      return;
    }
    if (this.finished) { this.vel.multiplyScalar(Math.exp(-4 * h)); return; }
    if (this.wipe) { this.stepWipe(h); return; }
    this.runTime += h;
    if (this.grounded) this.stepGround(h, input); else this.stepAir(h, input);
    this.collide(h);
    // bookkeeping: arc along the run, checkpoints, stop / finish
    const pr = this.path.project(this.pos.x, -this.pos.z);
    this.arc = pr.s; this.lat = pr.lat;
    const sp = this.vel.length();
    this.maxSpeed = Math.max(this.maxSpeed, sp);
    if (this.grounded && !this.wipe) {
      while (this.cpIndex + 1 < this.checkpointArcs.length && this.arc > this.checkpointArcs[this.cpIndex + 1]) {
        this.cpIndex++;
        this.lastCheckpoint = { pos: this.pos.clone(), vel: this.vel.clone(), heading: this.heading, arc: this.arc, idx: this.cpIndex };
        this.emit('checkpoint', { idx: this.cpIndex, arc: +this.arc.toFixed(1) });
      }
    }
    if (this.grounded && sp < 0.3) this.stillT += h; else this.stillT = 0;
    if (this.arc > this.path.length - 3) this.finish('38th St!', true);
    else if (this.stillT > 0.7 && this.arc > this.lastJumpArc + 6) this.finish('Stopped', false);
  }

  finish(reason, overrun) {
    if (this.finished) return;
    const stopPos = { x: +this.pos.x.toFixed(2), n: +(-this.pos.z).toFixed(2) };
    this.finished = { reason, overrun, time: +this.runTime.toFixed(2), score: this.score, arc: +this.arc.toFixed(1), stopPos, toJunction: +(this.path.length - this.arc).toFixed(1) };
    this.emit('finish', this.finished);
  }

  muAt() {
    let mu = Math.abs(this.lat) < 2.6 ? SLED.mu : SLED.muOffTrack;
    // stop zone: deep, loose snow over the last 18 m before the berm (and beyond it)
    const z0 = this.bermArc - 18;
    if (this.arc > z0) mu = Math.max(mu, SLED.mu + (SLED.muStop - SLED.mu) * clamp((this.arc - z0) / 14, 0, 1));
    return mu;
  }

  frame() {
    // tangent frame from heading + ground normal
    const n = this.normal;
    _f.set(Math.sin(this.heading), 0, Math.cos(this.heading));
    _f.addScaledVector(n, -_f.dot(n)).normalize();
    _l.crossVectors(n, _f).normalize();   // left
  }

  stepGround(h, input) {
    const n = this.normal;
    const steer = clamp(input.steer || 0, -1, 1);
    const sp0 = this.vel.length();
    // steering: lean changes the heading (rate falls off when very slow)
    this.heading -= steer * SLED.steerRate * clamp(sp0 / 3, 0.35, 1) * h;
    if (Math.abs(steer) < 0.1 && sp0 > 1.2) {
      const vh = Math.atan2(this.vel.x, this.vel.z);
      this.heading += angDiff(this.heading, vh) * (1 - Math.exp(-1.6 * h));
    }
    this.frame();
    const N = Math.max(0, 9.81 * n.y);
    // gravity along the surface
    _a.set(0, -9.81, 0); _a.addScaledVector(n, -_a.dot(n));
    // paddling with the hands when slow
    if (input.paddle > 0 && sp0 < 3.2) _a.addScaledVector(_f, 1.4 * input.paddle);
    this.vel.addScaledVector(_a, h);
    // friction (Coulomb, never reverses the motion) + brake + drag
    let mu = this.muAt() + (input.brake || 0) * SLED.muBrake;
    const vl = this.vel.dot(_l);
    const latCap = (Math.abs(steer) > 0.7 && sp0 > 7 ? SLED.muLatSkid : SLED.muLat) * N * h;
    const dl = clamp(vl, -latCap, latCap);
    const spPre = this.vel.length();
    this.vel.addScaledVector(_l, -dl);
    // carving turns the velocity rather than scrubbing it: keep most of the speed
    const spPost = this.vel.length();
    if (spPost > 1e-3) this.vel.multiplyScalar(1 + (spPre / spPost - 1) * SLED.carve);
    const skidding = Math.abs(vl) > latCap * 1.05 && sp0 > 3;
    this.skid = skidding ? Math.min(1, Math.abs(vl - dl) / 3) : this.skid * Math.exp(-6 * h);
    if (skidding) mu += 0.12;
    const sp = this.vel.length();
    if (sp > 1e-4) {
      const dv = Math.min(sp, (mu * N + SLED.dragK * sp * sp) * h);
      this.vel.multiplyScalar((sp - dv) / sp);
    }
    // kicker lips launch along the lip angle (robust to how finely the kicker mesh is tessellated)
    const r = this.onRamp();
    if (r && r.s >= r.j.L - 0.02 && r.s < r.j.L + 0.5 && sp0 > 2.2 && !this.launchedFrom) {
      const j = r.j;
      const a = Math.atan2(this.vel.x, this.vel.z);
      const hs = Math.hypot(this.vel.x, this.vel.z);
      if (Math.abs(angDiff(a, Math.atan2(j.dir[0], -j.dir[1]))) < 1.0) {
        const pitch = THREE.MathUtils.degToRad(j.angle) - (j.grade || 0);
        const spd = this.vel.length();
        this.vel.set(Math.sin(a) * Math.cos(pitch), Math.sin(pitch), Math.cos(a) * Math.cos(pitch)).multiplyScalar(spd);
        void hs;
        this.launchedFrom = j.id;
        this.pos.y += 0.01;
        this.takeOff(j.id);
        return;
      }
    }
    if (!r) this.launchedFrom = null;
    // move, then follow the surface or take off
    const p = _v.copy(this.pos).addScaledVector(this.vel, h);
    const g = this.ground(p.x, p.y, p.z, 1.0, 3);
    if (!g) { this.takeOff(); this.pos.copy(p); return; }
    const gap = p.y - g.y;
    if (gap > 0.025 && gap > 0.5 * 9.81 * n.y * h * h * 6) {
      this.pos.copy(p);
      this.takeOff();
      return;
    }
    p.y = g.y;
    this.pos.copy(p);
    const before = this.vel.length();
    const n2 = this.groundNormal(p.x, p.y, p.z, _n);
    const turn = n2.dot(n);
    this.normal.copy(n2);
    this.vel.addScaledVector(n2, -this.vel.dot(n2));
    // smooth transitions keep the speed (curved ramp), sharp ones lose the normal component (impact)
    const after = this.vel.length();
    if (after > 1e-4 && turn > 0.94) this.vel.multiplyScalar(before / after);
    this.surfaceKind = g.info.kind || 'snow';
    this.updateOrientation(h);
  }

  takeOff(forced = null) {
    this.grounded = false;
    this.airTime = 0;
    this.airTricks = [];
    this.apexY = this.pos.y;
    // which kicker? nearest lip within 4 m
    let jump = forced, best = forced ? -1 : 4;
    for (const j of this.jumps) {
      const d = Math.hypot(this.pos.x - j.lip[0], -this.pos.z - j.lip[1]);
      if (d < best) { best = d; jump = j.id; }
    }
    this.takeoff = { t: this.time, y: this.pos.y, jump, pos: this.pos.clone(), speed: +this.vel.length().toFixed(2), vy: +this.vel.y.toFixed(2) };
    this.pendingPop = null;
    if (this.popBuffered && this.time - this.popBuffered.t <= SLED.popWindowBefore + 1e-6) {
      const early = this.time - this.popBuffered.t;
      const q = clamp(1 - Math.max(0, early - 0.06) / (SLED.popWindowBefore - 0.06), 0, 1);
      this.popBuffered = null;
      this.applyPop(q);
    }
    this.popBuffered = null;
    if (jump) this.emit('takeoff', { jump, speed: this.takeoff.speed });
  }

  stepAir(h, input) {
    this.airTime += h;
    this.vel.y -= 9.81 * h;
    const sp = this.vel.length();
    if (sp > 1e-4) this.vel.multiplyScalar(1 - Math.min(0.5, SLED.dragK * sp * h));
    this.heading -= clamp(input.steer || 0, -1, 1) * SLED.airSteerRate * h;
    if (this.popBuffered && this.time - this.popBuffered.t > SLED.popWindowBefore) this.popBuffered = null;
    if (this.trick) {
      this.trick.t += h;
      if (this.trick.t >= this.trick.dur) {
        const n = this.airTricks.length + 1;
        const pts = Math.round(this.trick.points * (1 + 0.5 * (n - 1)));
        this.airTricks.push({ name: this.trick.name, label: this.trick.label, points: pts });
        this.emit('trick-done', { name: this.trick.name, label: this.trick.label, points: pts, combo: n });
        this.trick = null;
      }
    }
    this.pos.addScaledVector(this.vel, h);
    this.apexY = Math.max(this.apexY, this.pos.y);
    const g = this.ground(this.pos.x, this.pos.y, this.pos.z, 0.6 + Math.max(0, -this.vel.y * h), 30);
    if (g && this.pos.y <= g.y && this.vel.y <= 0.5) this.land(g);
    else if (!g && this.pos.y < 80) this.startWipe('Lost the ground');
    this.updateOrientation(h);
  }

  land(g) {
    this.pos.y = g.y;
    const n = this.groundNormal(this.pos.x, this.pos.y, this.pos.z, _n);
    const impact = -this.vel.dot(n);
    const vh = Math.atan2(this.vel.x, this.vel.z);
    const yawErr = Math.abs(angDiff(this.heading, vh));
    const air = this.airTime;
    const to = this.takeoff || { y: this.pos.y, jump: null };
    const apex = this.apexY - to.y;
    this.normal.copy(n);
    this.vel.addScaledVector(n, -Math.min(0, this.vel.dot(n)) * 1);   // lose the normal component
    this.vel.addScaledVector(n, -this.vel.dot(n));
    this.grounded = true;
    let fail = null;
    if (this.trick) {
      const frac = this.trick.t / this.trick.dur;
      if (frac < SLED.trickFinish) fail = `Landed mid-${this.trick.label}!`;
      else { const pts = Math.round(this.trick.points * 0.5); this.airTricks.push({ name: this.trick.name, label: this.trick.label + ' (sketchy)', points: pts }); this.emit('trick-done', { name: this.trick.name, label: this.trick.label, points: pts, sketchy: true }); }
      this.trick = null;
    }
    if (!fail && impact > SLED.wipeImpact) fail = 'Too hard!';
    if (!fail && yawErr > SLED.wipeYaw && Math.hypot(this.vel.x, this.vel.z) > 3) fail = 'Sideways landing!';
    const rec = { jump: to.jump, airtime: +air.toFixed(3), apex: +apex.toFixed(3), impact: +impact.toFixed(2), pop: this.pendingPop || null, tricks: this.airTricks.slice(), clean: !fail, takeoffSpeed: to.speed, takeoffVy: to.vy, ollie: !!to.ollie };
    if (to.jump || air > 0.35) {
      const airPts = Math.round(air * 100) + (apex > 2.2 ? 100 : 0);
      const trickPts = this.airTricks.reduce((s, x) => s + x.points, 0);
      const popPts = this.pendingPop ? this.pendingPop.points : 0;
      rec.points = fail ? 0 : airPts + trickPts + popPts + 50;
      this.jumpLog.push(rec);
      if (!fail) { this.score += rec.points; this.emit('land', { ...rec, label: 'Clean landing' }); }
    }
    this.popUsed = false; this.pendingPop = null; this.takeoff = null; this.airTricks = [];
    if (fail) { rec.fail = fail; if (!(to.jump || air > 0.35)) this.jumpLog.push(rec); this.startWipe(fail); }
  }

  collide(h) {
    // sphere around the rider vs non-walkable triangles (walls, trunks, hedges, cars, hay)
    const c = _sph.center.copy(this.pos).addScaledVector(this.normal, 0.5);
    _sph.radius = 0.45;
    _box.setFromCenterAndSize(c, _tp.set(1, 1, 1));
    let hitInfo = null; const push = new THREE.Vector3();
    const tri = new THREE.Vector3();
    this.col.bvh.shapecast({
      intersectsBounds: (b) => b.intersectsSphere(_sph),
      intersectsTriangle: (t, ti) => {
        const info = this.infoOf(ti);
        if (info.walkable) return false;
        t.closestPointToPoint(c, tri);
        const d = tri.distanceTo(c);
        if (d < _sph.radius) {
          const nn = _tp.subVectors(c, tri); nn.y = 0;
          const l = nn.length(); if (l < 1e-5) return false;
          nn.divideScalar(l);
          push.addScaledVector(nn, _sph.radius - d);
          hitInfo = info;
        }
        return false;
      },
    });
    if (!hitInfo) return;
    const pl = push.length();
    if (pl < 1e-5) return;
    const nrm = push.clone().divideScalar(pl);
    this.pos.add(push);
    const vn = this.vel.dot(nrm);
    if (vn >= 0) return;
    if (hitInfo.kind === 'hay') {
      this.vel.multiplyScalar(0.25); this.vel.addScaledVector(nrm, -this.vel.dot(nrm));
      this.emit('hay', {});
      return;
    }
    if (-vn > 6.5 && this.started) { this.startWipe(`Crashed into ${hitInfo.kind || 'something'}!`); return; }
    this.vel.addScaledVector(nrm, -vn * 1.3);
    this.emit('bump', { speed: +(-vn).toFixed(2) });
  }

  startWipe(reason) {
    if (this.wipe) return;
    this.trick = null;
    const axis = new THREE.Vector3(Math.random() - 0.5, 0.3, Math.random() - 0.5).normalize();
    this.wipe = { t: 0, reason, riderPos: this.pos.clone().add(new THREE.Vector3(0, 0.4, 0)), riderVel: this.vel.clone().multiplyScalar(0.85).add(new THREE.Vector3(0, 2.2, 0)), axis, spin: 6 + Math.random() * 4, rot: 0 };
    this.emit('wipeout', { reason });
  }

  stepWipe(h) {
    const w = this.wipe;
    w.t += h;
    // sled slides on with high friction, rider tumbles separately
    const sp = this.vel.length();
    if (sp > 1e-4) this.vel.multiplyScalar(Math.max(0, sp - 4.5 * h) / sp);
    this.vel.y -= 9.81 * h;
    this.pos.addScaledVector(this.vel, h);
    const g = this.ground(this.pos.x, this.pos.y, this.pos.z, 1, 4);
    if (g && this.pos.y < g.y) { this.pos.y = g.y; this.vel.y = Math.max(0, this.vel.y); }
    w.riderVel.y -= 9.81 * h;
    const rs = Math.hypot(w.riderVel.x, w.riderVel.z);
    w.riderPos.addScaledVector(w.riderVel, h);
    const gr = this.ground(w.riderPos.x, w.riderPos.y, w.riderPos.z, 1, 4);
    if (gr && w.riderPos.y < gr.y + 0.25) {
      w.riderPos.y = gr.y + 0.25; w.riderVel.y = Math.abs(w.riderVel.y) * 0.3;
      if (rs > 1e-3) { const k = Math.max(0, rs - 6 * h) / rs; w.riderVel.x *= k; w.riderVel.z *= k; }
      w.spin *= Math.exp(-1.8 * h);
    }
    w.rot += w.spin * h;
    this.updateOrientation(h);
    if (w.t > 2.3) this.respawn();
  }

  respawn() {
    const c = this.lastCheckpoint;
    this.wipe = null; this.trick = null; this.popUsed = false; this.popBuffered = null; this.takeoff = null;
    this.pos.copy(c.pos); this.vel.copy(c.vel); this.heading = c.heading;
    this.grounded = true; this.airTime = 0; this.stillT = 0;
    this.groundNormal(this.pos.x, this.pos.y, this.pos.z, this.normal);
    this.updateOrientation(1);
    this.emit('respawn', { checkpoint: c.idx });
  }

  updateOrientation(h) {
    // sled body: up = ground normal (or tilted with the flight path in the air), forward = heading
    const up = _a.copy(this.grounded || this.wipe ? this.normal : UP);
    const fwd = _f.set(Math.sin(this.heading), 0, Math.cos(this.heading));
    if (!this.grounded && !this.wipe) {
      // nose follows the flight path (half way)
      const hs = Math.hypot(this.vel.x, this.vel.z);
      const pitch = Math.atan2(this.vel.y, Math.max(hs, 0.1)) * 0.55;
      fwd.multiplyScalar(Math.cos(pitch)).setY(Math.sin(pitch));
      up.set(0, 1, 0).addScaledVector(fwd, -fwd.y).normalize();
    }
    fwd.addScaledVector(up, -fwd.dot(up)).normalize();
    const left = _l.crossVectors(up, fwd).normalize();
    const m = new THREE.Matrix4().makeBasis(left, up, fwd);
    const q = new THREE.Quaternion().setFromRotationMatrix(m);
    if (this.wipe) q.multiply(new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 0, 1), Math.min(this.wipe.t * 4, 1.4)));
    this.quat.slerp(q, h >= 1 ? 1 : 1 - Math.exp(-14 * h));
  }

  summary() {
    return {
      active: this.active, grounded: this.grounded, countdown: +this.countdown.toFixed(2), time: +this.runTime.toFixed(2),
      speed: +this.vel.length().toFixed(2), arc: +this.arc.toFixed(2), lat: +this.lat.toFixed(2), airTime: +this.airTime.toFixed(2),
      score: this.score, trick: this.trick && this.trick.name, wipe: this.wipe && this.wipe.reason, finished: this.finished,
      jumps: this.jumpLog, x: +this.pos.x.toFixed(2), n: +(-this.pos.z).toFixed(2), y: +this.pos.y.toFixed(2), maxSpeed: +this.maxSpeed.toFixed(2),
    };
  }
}

// ---------------------------------------------------------------- autopilot (tests / demo): follows the run path,
// pops at the lips, optionally performs tricks. Returns an input object + actions for SledGame.
export class Autopilot {
  constructor(game, { pop = true, tricks = {}, look = 7 } = {}) {
    this.g = game; this.pop = pop; this.tricks = tricks; this.look = look; this.popped = new Set(); this.done = new Set();
  }
  input() {
    const g = this.g;
    const s = g.arc + this.look + g.vel.length() * 0.25;
    const [tx, ty] = g.path.at(s);
    const want = Math.atan2(tx - g.pos.x, -ty - g.pos.z);
    const err = angDiff(g.heading, want);
    const steer = clamp(-err * 2.2, -1, 1);
    // actions
    if (g.grounded && this.pop) {
      const r = g.onRamp();
      if (r && !this.popped.has(r.j.id)) {
        const sp = Math.max(1, g.vel.length());
        if (r.s > r.j.L - sp * 0.1) { this.popped.add(r.j.id); g.boost(); }
      }
    }
    if (!g.grounded && g.takeoff && g.takeoff.jump && !g.trick) {
      const want2 = this.tricks[g.takeoff.jump];
      const key = g.takeoff.jump + ':' + g.takeoff.t;
      if (want2 && !this.done.has(key) && g.airTime > 0.08) { this.done.add(key); g.trickPress(want2); }
    }
    return { steer, brake: 0, paddle: g.vel.length() < 1.5 ? 1 : 0 };
  }
}

// headless run (same physics) for tests/tuning
export function simulate(game, startLocal, terrainH, heading, opts = {}, maxT = 60) {
  game.startAt(startLocal, terrainH, heading, { countdown: 0.01 });
  const ap = new Autopilot(game, opts);
  let t = 0;
  while (t < maxT && !game.finished) {
    game.step(H, ap.input());
    t += H;
  }
  return game.summary();
}
