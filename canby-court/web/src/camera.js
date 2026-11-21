// Third-person follow camera: smooth orbit around the traveller, collision-aware (pulls in when a building
// or wall blocks the view, eases back out), never ends up inside geometry.
import * as THREE from 'three';

const _ray = new THREE.Ray();
const _off = new THREE.Vector3();
const _right = new THREE.Vector3();
const _up = new THREE.Vector3();
const _dir = new THREE.Vector3();
const _fwd = new THREE.Vector3();

export class FollowCamera {
  constructor(camera, bvh) {
    this.camera = camera;
    this.bvh = bvh;
    this.yaw = -Math.PI / 2;     // camera sits at target + (sin yaw, ., cos yaw) * d ; -pi/2 => looking east
    this.pitch = 0.22;
    this.dist = 5.2;
    this.minDist = 1.4;
    this.maxDist = 14;
    this.curDist = this.dist;
    this.target = new THREE.Vector3();
    this.inited = false;
    this.lastLook = -1e9;
  }

  // shared scratch vector: copy it if you need to keep it
  get forward() { return _fwd.set(-Math.sin(this.yaw), 0, -Math.cos(this.yaw)); }

  look(dx, dy, now) {
    this.yaw -= dx;
    this.pitch = THREE.MathUtils.clamp(this.pitch + dy, -0.35, 1.25);
    this.lastLook = now;
  }

  zoom(f) { this.dist = THREE.MathUtils.clamp(this.dist * f, this.minDist, this.maxDist); }

  snap(pos, yaw) {
    this.yaw = yaw; this.inited = false; this.update(0, pos, 0, false, 0);
  }

  // shortest free distance along the view ray (centre + 4 offset rays approximate a small sphere)
  clearance(from, dir, maxD) {
    let best = maxD;
    _right.set(Math.cos(this.yaw), 0, -Math.sin(this.yaw));
    _up.crossVectors(_right, dir).normalize();
    const offs = [[0, 0], [0.22, 0], [-0.22, 0], [0, 0.18], [0, -0.18]];
    for (const [a, b] of offs) {
      _ray.origin.copy(from).addScaledVector(_right, a).addScaledVector(_up, b);
      _ray.direction.copy(dir);
      const hit = this.bvh.raycastFirst(_ray, THREE.DoubleSide, 0, maxD + 0.4);
      if (hit) best = Math.min(best, hit.distance - 0.35);
    }
    return Math.max(0.3, best);
  }

  update(dt, playerPos, playerFacing, moving, now, autoAlign = false) {
    const tgt = _off.set(playerPos.x, playerPos.y + 1.45, playerPos.z);
    if (!this.inited) { this.target.copy(tgt); this.curDist = this.dist; this.inited = true; }
    else this.target.lerp(tgt, 1 - Math.exp(-12 * dt));

    // gentle auto-follow behind the walker (touch only, after 1.5 s without manual look)
    if (autoAlign && moving && now - this.lastLook > 1500) {
      const behind = playerFacing + Math.PI;
      let d = behind - this.yaw; d = Math.atan2(Math.sin(d), Math.cos(d));
      if (Math.abs(d) < 2.4) this.yaw += d * (1 - Math.exp(-0.9 * dt));
    }

    const cp = Math.cos(this.pitch);
    const dir = _dir.set(Math.sin(this.yaw) * cp, Math.sin(this.pitch), Math.cos(this.yaw) * cp).normalize();
    const free = this.clearance(this.target, dir, this.dist);
    // pull in fast, ease out slowly
    if (free < this.curDist) this.curDist += (free - this.curDist) * (1 - Math.exp(-30 * dt || 1));
    else this.curDist += (Math.min(free, this.dist) - this.curDist) * (1 - Math.exp(-3 * dt));
    if (dt === 0) this.curDist = Math.min(free, this.dist);
    this.camera.position.copy(this.target).addScaledVector(dir, this.curDist);
    // keep the camera above the ground directly under it
    _ray.origin.set(this.camera.position.x, this.camera.position.y + 0.6, this.camera.position.z);
    _ray.direction.set(0, -1, 0);
    const g = this.bvh.raycastFirst(_ray, THREE.DoubleSide, 0, 1.0);
    if (g && this.camera.position.y < g.point.y + 0.3) this.camera.position.y = g.point.y + 0.3;
    this.camera.lookAt(this.target);
  }
}

// Sled chase camera: behind the direction of travel, speed-based FOV, smooth (looser vertically while airborne so
// the height of a jump reads), collision-aware (pulls in when the view ray hits geometry), drag to glance around.
const _c = { want: new THREE.Vector3(), tgt: new THREE.Vector3(), dir: new THREE.Vector3(), f: new THREE.Vector3(), ray: new THREE.Ray() };
export class ChaseCamera {
  constructor(camera, bvh) {
    this.camera = camera; this.bvh = bvh;
    this.pos = new THREE.Vector3(); this.look = new THREE.Vector3();
    this.fwd = new THREE.Vector3(0, 0, 1);
    this.yawOff = 0; this.pitchOff = 0; this.lastLook = -1e9;
    this.baseFov = 58; this.fov = 58;
  }
  reset(p, heading) {
    this.fwd.set(Math.sin(heading), 0, Math.cos(heading));
    this.pos.copy(p).addScaledVector(this.fwd, -5).add(new THREE.Vector3(0, 2.2, 0));
    this.look.copy(p).addScaledVector(this.fwd, 3);
    this.yawOff = 0; this.pitchOff = 0;
  }
  glance(dx, dy, now) { this.yawOff = THREE.MathUtils.clamp(this.yawOff - dx, -2.6, 2.6); this.pitchOff = THREE.MathUtils.clamp(this.pitchOff + dy, -0.3, 0.6); this.lastLook = now; }
  update(dt, p, vel, heading, airborne, now) {
    const { want, tgt, dir, f, ray } = _c;
    const hs = Math.hypot(vel.x, vel.z);
    // forward: travel direction when moving, else the sled heading
    f.set(Math.sin(heading), 0, Math.cos(heading));
    if (hs > 1.5) { const vf = dir.set(vel.x, 0, vel.z).normalize(); f.lerp(vf, THREE.MathUtils.clamp((hs - 1.5) / 3, 0, 0.85)).normalize(); }
    this.fwd.lerp(f, 1 - Math.exp(-3.2 * dt)).normalize();
    if (now - this.lastLook > 1200) { this.yawOff *= Math.exp(-2.5 * dt); this.pitchOff *= Math.exp(-2.5 * dt); }
    const fw = dir.copy(this.fwd).applyAxisAngle(new THREE.Vector3(0, 1, 0), this.yawOff);
    const dist = 4.4 + Math.min(hs, 18) * 0.11;
    const height = 1.7 + Math.min(hs, 18) * 0.035 + this.pitchOff * 3;
    tgt.copy(p).add(new THREE.Vector3(0, 0.9, 0));
    want.copy(tgt).addScaledVector(fw, -dist); want.y = tgt.y + height;
    // collision: pull in along target->camera
    const to = new THREE.Vector3().subVectors(want, tgt); const L = to.length(); to.divideScalar(L);
    ray.origin.copy(tgt); ray.direction.copy(to);
    const hit = this.bvh.raycastFirst(ray, THREE.DoubleSide, 0, L + 0.3);
    if (hit && hit.distance < L + 0.3) want.copy(tgt).addScaledVector(to, Math.max(0.6, hit.distance - 0.35));
    const kxz = 1 - Math.exp(-7 * dt), ky = 1 - Math.exp(-(airborne ? 2.2 : 5) * dt);
    if (dt === 0) this.pos.copy(want);
    this.pos.x += (want.x - this.pos.x) * kxz; this.pos.z += (want.z - this.pos.z) * kxz; this.pos.y += (want.y - this.pos.y) * ky;
    // keep above the ground under the camera
    ray.origin.set(this.pos.x, this.pos.y + 3, this.pos.z); ray.direction.set(0, -1, 0);
    const g = this.bvh.raycastFirst(ray, THREE.DoubleSide, 0, 8);
    if (g && this.pos.y < g.point.y + 0.45) this.pos.y = g.point.y + 0.45;
    const lookT = dir.copy(tgt).addScaledVector(this.fwd, 2.5 + hs * 0.08);
    this.look.lerp(lookT, dt === 0 ? 1 : 1 - Math.exp(-9 * dt));
    this.fov += (this.baseFov + Math.min(hs, 18) * 1.05 - this.fov) * (1 - Math.exp(-2.5 * dt));
    this.camera.position.copy(this.pos);
    this.camera.lookAt(this.look);
    if (Math.abs(this.camera.fov - this.fov) > 0.01) { this.camera.fov = this.fov; this.camera.updateProjectionMatrix(); }
  }
}
