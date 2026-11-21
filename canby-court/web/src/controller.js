// Kinematic capsule character controller on a three-mesh-bvh collider.
//  - horizontal: capsule (lifted by STEP_UP so risers <= 0.35 m are ignored) pushed out of triangles, slides along walls
//  - vertical: ground snap by downward rays (centre + 4), step-up <= STEP_UP, gravity when airborne
//  - slopes steeper than MAX_SLOPE cannot be walked up
//  - soft boundary at the edge of the data box (CONTEXT)
// (from the Higashiyama explorer, kyoto-3d-render-test/web/src/controller.js)
import * as THREE from 'three';
import { CONTEXT, SOFT_MARGIN } from './config.js';

export const RADIUS = 0.3;
export const HEIGHT = 1.68;
export const STEP_UP = 0.35;
const SNAP_DOWN = 0.55;
const MAX_SLOPE = THREE.MathUtils.degToRad(40);
const MIN_NY = Math.cos(MAX_SLOPE);
const GRAVITY = 20;
export const WALK = 1.45;   // walk clip speed 1.30 m/s, run clip 3.2 m/s (character agent)
export const RUN = 3.6;

const _seg = new THREE.Line3();
const _box = new THREE.Box3();
const _tri = new THREE.Vector3();
const _cap = new THREE.Vector3();
const _push = new THREE.Vector3();
const _ray = new THREE.Ray();
const _v = new THREE.Vector3();
const DOWN = new THREE.Vector3(0, -1, 0);

export class Controller {
  constructor(col) {
    this.setCollider(col);
    this.pos = new THREE.Vector3();
    this.vel = new THREE.Vector3();
    this.grounded = false;
    this.groundName = '';
    this.groundNormal = new THREE.Vector3(0, 1, 0);
    this.speed = 0;            // horizontal speed (m/s)
    this.facing = 0;           // yaw (rad) the character faces
    this.edgeWarn = false;
    this.blockedBySlope = false;
    this.wallContact = false;
  }

  setCollider(col) {
    this.bvh = col.bvh;
    this.objInfo = col.objInfo;
    this.objIdAttr = col.colGeom.attributes.objId;
    this.index = col.colGeom.index;
  }

  objAt(faceIndex) {
    const a = this.index.getX(faceIndex * 3);
    return this.objInfo[Math.round(this.objIdAttr.getX(a))] || { name: '?', role: '?', walkable: false };
  }

  // highest walkable surface under (x,z) between y+up and y-down. returns {y, normal, info} or null
  probeGround(x, y, z, up = STEP_UP + 0.05, down = SNAP_DOWN) {
    let best = null;
    const offs = [[0, 0], [0.16, 0], [-0.16, 0], [0, 0.16], [0, -0.16]];
    for (const [ox, oz] of offs) {
      _ray.origin.set(x + ox, y + up, z + oz);
      _ray.direction.copy(DOWN);
      const hit = this.bvh.raycastFirst(_ray, THREE.DoubleSide, 0, up + down);
      if (!hit) continue;
      if (!best || hit.point.y > best.y + 1e-4 || (ox === 0 && oz === 0 && Math.abs(hit.point.y - best.y) < 1e-4)) {
        const n = hit.face.normal.clone();
        if (n.y < 0) n.negate();
        best = { y: hit.point.y, normal: n, faceIndex: hit.faceIndex, center: ox === 0 && oz === 0 };
      }
    }
    if (best) best.info = this.objAt(best.faceIndex);
    return best;
  }

  // full-height probe from high above (teleports)
  dropTo(x, z, fromY = 240) {
    _ray.origin.set(x, fromY, z); _ray.direction.copy(DOWN);
    const hit = this.bvh.raycastFirst(_ray, THREE.DoubleSide, 0, 200);
    if (!hit) return null;
    const n = hit.face.normal.clone(); if (n.y < 0) n.negate();
    return { y: hit.point.y, normal: n, info: this.objAt(hit.faceIndex) };
  }

  // is the standing capsule at feet position p free of geometry?
  capsuleFree(p) {
    _seg.start.set(p.x, p.y + STEP_UP + RADIUS, p.z);
    _seg.end.set(p.x, p.y + HEIGHT - RADIUS, p.z);
    _box.makeEmpty(); _box.expandByPoint(_seg.start); _box.expandByPoint(_seg.end); _box.expandByScalar(RADIUS);
    let free = true;
    this.bvh.shapecast({
      intersectsBounds: (b) => b.intersectsBox(_box),
      intersectsTriangle: (tri) => {
        const d = tri.closestPointToSegment(_seg, _tri, _cap);
        if (d < RADIUS - 0.02) { free = false; return true; }
        return false;
      },
    });
    return free;
  }

  // find a walkable, collision-free spot near (x, z): spiral search
  findSpot(x, z, maxR = 10) {
    for (let r = 0; r <= maxR; r += 0.5) {
      const n = r === 0 ? 1 : Math.ceil(2 * Math.PI * r / 0.6);
      for (let k = 0; k < n; k++) {
        const a = (k / n) * Math.PI * 2;
        const px = x + Math.cos(a) * r, pz = z + Math.sin(a) * r;
        const g = this.dropTo(px, pz);
        if (!g || !g.info.walkable || g.normal.y < MIN_NY) continue;
        const p = new THREE.Vector3(px, g.y, pz);
        if (this.capsuleFree(p)) return { pos: p, offset: r, ground: g.info.name };
      }
    }
    return null;
  }

  jump(v = 4.0) {
    if (!this.grounded) return false;
    this.grounded = false; this.vel.y = v; this.pos.y += 0.02;
    return true;
  }

  teleport(p, facing) {
    this.pos.copy(p);
    this.vel.set(0, 0, 0);
    this.facing = facing;
    this.grounded = true;
  }

  // push the lifted capsule at `p` out of geometry (horizontal only). returns total push
  resolveHorizontal(p) {
    let contact = false;
    for (let it = 0; it < 3; it++) {
      _seg.start.set(p.x, p.y + STEP_UP + RADIUS, p.z);
      _seg.end.set(p.x, p.y + HEIGHT - RADIUS, p.z);
      _box.makeEmpty(); _box.expandByPoint(_seg.start); _box.expandByPoint(_seg.end); _box.expandByScalar(RADIUS);
      let moved = false;
      this.bvh.shapecast({
        intersectsBounds: (b) => b.intersectsBox(_box),
        intersectsTriangle: (tri) => {
          const d = tri.closestPointToSegment(_seg, _tri, _cap);
          if (d >= RADIUS) return false;
          _push.subVectors(_cap, _tri);
          _push.y = 0;
          let h = _push.length();
          if (h < 1e-5) {
            // segment passes through the triangle: use its normal
            tri.getNormal(_push); _push.y = 0; h = _push.length();
            if (h < 0.2) return false;     // floor / ceiling-like: ignore
          }
          _push.multiplyScalar((RADIUS - d) / h);
          _seg.start.add(_push); _seg.end.add(_push);
          p.x += _push.x; p.z += _push.z;
          moved = contact = true;
          return false;
        },
      });
      if (!moved) break;
    }
    return contact;
  }

  update(dt, moveDir, running) {
    // moveDir: THREE.Vector3 in world xz, length 0..1
    const target = _v.copy(moveDir).multiplyScalar(running ? RUN : WALK);
    const accel = this.grounded ? 12 : 2.5;
    const k = 1 - Math.exp(-accel * dt);
    this.vel.x += (target.x - this.vel.x) * k;
    this.vel.z += (target.z - this.vel.z) * k;
    if (moveDir.lengthSq() > 0.0004) {
      const want = Math.atan2(moveDir.x, moveDir.z);
      let d = want - this.facing;
      d = Math.atan2(Math.sin(d), Math.cos(d));
      this.facing += d * (1 - Math.exp(-10 * dt));
    }

    const steps = Math.max(1, Math.min(6, Math.ceil(Math.hypot(this.vel.x, this.vel.z) * dt / (RADIUS * 0.5))));
    const h = dt / steps;
    this.wallContact = false;
    this.blockedBySlope = false;
    const start = this.pos.clone();
    for (let i = 0; i < steps; i++) this.substep(h);
    const moved = Math.hypot(this.pos.x - start.x, this.pos.z - start.z);
    this.speed = moved / Math.max(dt, 1e-4);
  }

  substep(h) {
    const p = this.pos.clone();
    if (!this.grounded) this.vel.y -= GRAVITY * h;
    p.x += this.vel.x * h;
    p.z += this.vel.z * h;

    // soft invisible wall at the edge of the data box (local north = -z)
    const [x0, y0, x1, y1] = CONTEXT, m = RADIUS + 0.2, n = -p.z;
    this.edgeWarn = p.x < x0 + SOFT_MARGIN || p.x > x1 - SOFT_MARGIN || n < y0 + SOFT_MARGIN || n > y1 - SOFT_MARGIN;
    if (p.x < x0 + m) { p.x = x0 + m; this.vel.x *= 0.2; }
    if (p.x > x1 - m) { p.x = x1 - m; this.vel.x *= 0.2; }
    if (n < y0 + m) { p.z = -(y0 + m); this.vel.z *= 0.2; }
    if (n > y1 - m) { p.z = -(y1 - m); this.vel.z *= 0.2; }

    if (this.resolveHorizontal(p)) this.wallContact = true;

    // vertical
    if (this.grounded) {
      const g = this.probeGround(p.x, p.y, p.z);
      if (g) {
        const rise = g.y - this.pos.y;
        if (g.normal.y < MIN_NY && rise > 0.04) {
          // steeper than 40 degrees and going up: stay put
          this.blockedBySlope = true;
          p.x = this.pos.x; p.z = this.pos.z;
          this.vel.x *= 0.5; this.vel.z *= 0.5;
        } else {
          p.y = g.y;
          this.groundNormal.copy(g.normal);
          this.groundName = g.info.name;
        }
        this.vel.y = 0;
      } else {
        this.grounded = false;
        this.vel.y = 0;
      }
    } else {
      p.y += this.vel.y * h;
      const g = this.probeGround(p.x, p.y, p.z, STEP_UP + 0.05, Math.max(0.05, -this.vel.y * h + 0.05));
      if (g && this.vel.y <= 0) {
        p.y = g.y; this.vel.y = 0; this.grounded = true;
        this.groundNormal.copy(g.normal); this.groundName = g.info.name;
      }
      if (p.y < 90) { // fell out of the world: recover
        const s = this.findSpot(p.x, p.z, 20);
        if (s) { p.copy(s.pos); this.grounded = true; this.vel.set(0, 0, 0); }
      }
    }
    this.pos.copy(p);
  }
}
