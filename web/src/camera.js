// Third-person follow camera: smooth orbit around the traveller, collision-aware (pulls in when a building
// or wall blocks the view, eases back out), never ends up inside geometry.
import * as THREE from 'three';

const _ray = new THREE.Ray();
const _off = new THREE.Vector3();
const _right = new THREE.Vector3();
const _up = new THREE.Vector3();

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

  get forward() { return new THREE.Vector3(-Math.sin(this.yaw), 0, -Math.cos(this.yaw)); }

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
    const dir = new THREE.Vector3(Math.sin(this.yaw) * cp, Math.sin(this.pitch), Math.cos(this.yaw) * cp).normalize();
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
