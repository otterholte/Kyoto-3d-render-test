"""Clip definitions (pose functions) for anim.Rig.bake.

Conventions (armature rest space): +X = character's left, -Y = forward, +Z = up.
  spine/neck/head : +X rotation = bend forward, +Z = turn left, +Y = lean left
  thigh           : -X = hip flexion (leg forward)
  calf            : +X = knee flexion
  foot            : +X = plantar flexion (toes down)
  upperarm        : -X = swing forward ; about Y: s*deg lowers (s=+1 left, -1 right)
All clips are in place. Walk/run speeds are given in CLIP_INFO so the game can
move the character root at the matching speed (feet then stay planted).
Sled clips assume the character root is parented to the sled's "SledSeat" empty.
"""
import math
from mathutils import Quaternion, Vector

from anim import Pose, q, ease, ease_io, lerp, X, Y, Z, FPS

SIDES = (("_l", 1), ("_r", -1))
FINGERS = ("index", "middle", "ring", "pinky")

# sled layout in character-root space (root == SledSeat)
SLED_GRIP = Vector((0.235, -0.30, 0.115))     # side handle (left; mirror x for right)
SLED_FOOT = Vector((0.13, -0.60, 0.085))      # ankle target with heels on the sled floor
SEAT_HIP_Z = 0.115                             # hip joint height above the seat


class Ctx:
    def __init__(self, rig):
        self.rig = rig
        h = rig.head
        self.hip_z = h["pelvis"].z
        self.ankle = {s: h["foot" + s].copy() for s, _ in SIDES}
        self.ankle_h = h["foot_l"].z
        self.ball_off = h["foot_l"].y - h["ball_l"].y          # ankle -> ball (forward)
        self.heel_off = 0.055                                  # ankle -> heel (back)
        # elbow flexion axes (rest)
        self.elbow_axis = {}
        for s, sg in SIDES:
            u = (rig.tail["upperarm" + s] - rig.head["upperarm" + s]).normalized()
            l = (rig.tail["lowerarm" + s] - rig.head["lowerarm" + s]).normalized()
            self.elbow_axis[s] = u.cross(l).normalized()
        self.leg_len = rig.len["thigh_l"] + rig.len["calf_l"]


# ------------------------------------------------------------------ building blocks
def relaxed_arms(p, c, lower=38.0, elbow=-22.0, swing=0.0, curl=18.0, side=None, wrist=0.0):
    for s, sg in SIDES:
        if side and s != side:
            continue
        p.add("upperarm" + s, q(Y, sg * lower))
        if swing:
            sw = swing if not isinstance(swing, dict) else swing[s]
            p.add("upperarm" + s, q(X, -sw))
        el = elbow if not isinstance(elbow, dict) else elbow[s]
        p.add("lowerarm" + s, q(c.elbow_axis[s], el))
        p.add("clavicle" + s, q(Y, sg * 4))
        hand_curl(p, c, s, curl)
        if wrist:
            p.add("hand" + s, q(X, wrist))


def hand_curl(p, c, s, deg, thumb=None, spread=0.0):
    r = c.rig
    for f in FINGERS:
        k = 1.0 + (0.15 if f in ("ring", "pinky") else 0.0)
        p.add(f"{f}_01{s}", q(r.curl_axis[f"{f}_01{s}"], deg * 0.8 * k))
        p.add(f"{f}_02{s}", q(r.curl_axis[f"{f}_02{s}"], deg * 1.1 * k))
        p.add(f"{f}_03{s}", q(r.curl_axis[f"{f}_03{s}"], deg * 0.8 * k))
    t = deg * 0.5 if thumb is None else thumb
    for k in ("02", "03"):
        p.add(f"thumb_{k}{s}", q(r.curl_axis[f"thumb_{k}{s}"], t))


def grip(p, c, s):
    hand_curl(p, c, s, 62, thumb=35)


def spine(p, fwd=0.0, turn=0.0, lean=0.0, dist=(0.3, 0.3, 0.4)):
    for b, w in zip(("spine_01", "spine_02", "spine_03"), dist):
        p.add(b, q(Y, lean * w) @ q(Z, turn * w) @ q(X, fwd * w))


def neck_head(p, fwd=0.0, turn=0.0, lean=0.0):
    p.add("neck_01", q(Y, lean * 0.4) @ q(Z, turn * 0.4) @ q(X, fwd * 0.4))
    p.add("head", q(Y, lean * 0.6) @ q(Z, turn * 0.6) @ q(X, fwd * 0.6))


def foot_target(c, s, ref, pitch, yaw=0.0):
    """Ankle position for a foot whose flat-foot ankle would be at `ref`,
    pitched by `pitch` deg (+ = heel up, pivot on the ball; - = toes up, pivot on heel)."""
    ref = Vector(ref)
    if pitch >= 0:
        piv = ref + Vector((0, -c.ball_off, -c.ankle_h + 0.01))
    else:
        piv = ref + Vector((0, c.heel_off, -c.ankle_h + 0.01))
    R = q(X, pitch)
    ank = piv + R @ (ref - piv)
    end = q(Z, yaw) @ R
    return ank, end


def leg_ik(p, c, s, ankle, end_rot, pole_fwd=1.0, toe=0.0):
    sg = 1 if s == "_l" else -1
    hipx = c.rig.head["thigh" + s].x
    p.ik["leg" + s] = dict(target=ankle, pole=Vector((hipx * 1.1 + sg * 0.05, -1.2 * pole_fwd, 0.55 + ankle.z * 0.5)),
                           end_rot=end_rot)
    if toe:
        p.add("ball" + s, q(X, toe))


def breathe(p, t, rate=0.25, amp=1.0):
    b = math.sin(2 * math.pi * rate * t)
    p.add("spine_02", q(X, -0.6 * amp * b))
    p.add("spine_03", q(X, -0.9 * amp * b))
    for s, sg in SIDES:
        p.add("clavicle" + s, q(Y, -sg * 0.8 * amp * b))
    p.add("neck_01", q(X, 0.8 * amp * b))
    return b


# ------------------------------------------------------------------ locomotion
def idle(c):
    T = 4.0

    def fn(t):
        p = Pose()
        ph = 2 * math.pi * t / T
        sway = math.sin(ph)
        b = breathe(p, t, rate=1 / T * 1, amp=1.0)  # one slow breath per 4 s
        b2 = math.sin(2 * math.pi * t / T * 2)
        hip = Vector((0.012 * sway, 0.004 * math.sin(2 * ph), c.hip_z - 0.012 + 0.002 * b2))
        p.pelvis_loc = hip
        p.pelvis_rot = q(Y, -1.6 * sway) @ q(Z, 1.0 * math.sin(ph + 0.6))
        spine(p, fwd=1.0, lean=1.4 * sway, turn=-1.2 * math.sin(ph + 0.6))
        neck_head(p, fwd=-1.5 + 0.8 * math.sin(2 * math.pi * t / T * 2 + 1), turn=3 * math.sin(ph * 1 + 2.0), lean=-0.8 * sway)
        relaxed_arms(p, c, lower=37, elbow={"_l": -32 + 1.5 * b, "_r": -32 - 1.5 * b},
                     swing={"_l": 2 + 1.0 * b, "_r": 2 - 1.0 * b}, curl=20)
        for s, sg in SIDES:
            a = c.ankle[s]
            ank, end = foot_target(c, s, (sg * 0.125, a.y + (0.03 if sg > 0 else -0.01), c.ankle_h), 0.0, yaw=sg * 7)
            leg_ik(p, c, s, ank, end)
        return p
    return fn, int(T * FPS), dict(loop=True, speed=0.0)


def gait(c, T, speed, stance, lift, hip_drop, bob, lean, arm_amp, elbow_base, elbow_amp,
         pelvis_yaw, pelvis_roll, hs_y, pitch_hs, pitch_to, run=False):
    L = speed * T

    def foot(s, ph):
        """ph in [0,1): 0 = heel strike of this foot."""
        sg = 1 if s == "_l" else -1
        x = sg * (0.095 if not run else 0.085)
        if ph < stance:
            u = ph / stance
            ref_y = hs_y + speed * ph * T
            # pitch: heel strike -> flat -> heel rise -> toe off
            if not run:
                if u < 0.2:
                    pitch = lerp(pitch_hs, 0, ease(u / 0.2))
                elif u < 0.55:
                    pitch = 0.0
                else:
                    pitch = lerp(0, pitch_to, ease((u - 0.55) / 0.45) ** 1.3)
            else:
                pitch = lerp(pitch_hs, 0, ease(u / 0.3)) if u < 0.3 else lerp(0, pitch_to, ease((u - 0.3) / 0.7))
            ank, end = foot_target(c, s, (x, ref_y, c.ankle_h), pitch)
            return ank, end, 0.0
        # swing
        u = (ph - stance) / (1 - stance)
        a0, e0 = foot_target(c, s, (x, hs_y + speed * stance * T, c.ankle_h), pitch_to)
        a1, e1 = foot_target(c, s, (x, hs_y, c.ankle_h), pitch_hs)
        y = lerp(a0.y, a1.y, ease_io(u) if not run else ease_io(u) ** 1.15)
        z0 = lerp(a0.z, a1.z, u)
        if run:
            # heel kicks up behind then the foot reaches forward
            zl = lift * math.sin(math.pi * min(u * 1.25, 1.0)) ** 0.8
            y = y + 0.10 * math.sin(math.pi * u) * (1 - u)
        else:
            zl = lift * math.sin(math.pi * u) ** 1.2
        if u < 0.5:
            pitch = lerp(pitch_to, 8 if not run else 40, ease(u / 0.5))
        else:
            pitch = lerp(8 if not run else 40, pitch_hs, ease((u - 0.5) / 0.5))
        R = q(X, pitch)
        return Vector((x, y, z0 + zl)), R, pitch

    def fn(t):
        p = Pose()
        ph = (t / T) % 1.0
        w = 2 * math.pi * ph
        z = c.hip_z - hip_drop + bob * math.cos(2 * w - (math.pi if not run else 0.0)) * (1 if not run else -1)
        p.pelvis_loc = Vector((0.018 * math.sin(w) * (0.5 if run else 1.0), 0.0, z))
        p.pelvis_rot = (q(Z, -pelvis_yaw * math.cos(w)) @ q(Y, -pelvis_roll * math.sin(w))
                        @ q(X, 0.0))
        spine(p, fwd=lean, turn=pelvis_yaw * 1.6 * math.cos(w), lean=pelvis_roll * 0.8 * math.sin(w))
        neck_head(p, fwd=-lean * 0.6 + (1.5 if not run else 0) * math.cos(2 * w), turn=-pelvis_yaw * 0.6 * math.cos(w),
                  lean=-pelvis_roll * 0.3 * math.sin(w))
        for s, sg in SIDES:
            phs = ph if s == "_l" else (ph + 0.5) % 1.0
            ank, end, _ = foot(s, phs)
            leg_ik(p, c, s, ank, end)
            # arm opposite to same-side leg: left arm forward when right leg forward
            sw = -arm_amp * math.cos(2 * math.pi * phs)
            el = elbow_base + elbow_amp * max(0.0, math.sin(2 * math.pi * phs - math.pi / 2) * -1) \
                if False else elbow_base + elbow_amp * 0.5 * (1 + math.cos(2 * math.pi * phs + math.pi))
            relaxed_arms(p, c, lower=34 if not run else 30, elbow=el, swing=sw, curl=22 if not run else 40, side=s)
        return p
    return fn


def walk(c):
    T = 32 / FPS
    fn = gait(c, T=T, speed=1.30, stance=0.60, lift=0.085, hip_drop=0.032, bob=0.016, lean=3.0,
              arm_amp=16.0, elbow_base=-12.0, elbow_amp=14.0, pelvis_yaw=5.0, pelvis_roll=3.5,
              hs_y=-0.30, pitch_hs=-16.0, pitch_to=34.0)
    return fn, 32, dict(loop=True, speed=1.30)


def run(c):
    T = 22 / FPS
    fn = gait(c, T=T, speed=3.2, stance=0.38, lift=0.30, hip_drop=0.07, bob=0.035, lean=11.0,
              arm_amp=34.0, elbow_base=58.0, elbow_amp=22.0, pelvis_yaw=9.0, pelvis_roll=4.0,
              hs_y=-0.26, pitch_hs=-6.0, pitch_to=42.0, run=True)
    return fn, 22, dict(loop=True, speed=3.2)


def jump(c):
    D = 1.4

    def fn(t):
        p = Pose()
        # pelvis height profile (key times)
        keys = [(0.0, 0.0), (0.30, -0.16), (0.42, 0.02), (0.68, 0.34), (0.92, 0.03), (1.05, -0.14), (1.4, 0.0)]
        z = keys[-1][1]
        for (t0, z0), (t1, z1) in zip(keys, keys[1:]):
            if t0 <= t <= t1:
                u = (t - t0) / (t1 - t0)
                z = lerp(z0, z1, ease_io(u) if not (0.42 <= t0 < 0.92) else u)
                if 0.42 <= t0 < 0.92:  # ballistic flight 0.42 -> 0.92
                    tt = (t - 0.42) / 0.5
                    z = 0.02 + 4 * 0.32 * tt * (1 - tt) + 0.01 * tt
                break
        airborne = 0.42 < t < 0.92
        crouch = max(0.0, -z) / 0.16
        p.pelvis_loc = Vector((0, 0.03 * crouch, c.hip_z - 0.01 + z))
        p.pelvis_rot = q(X, 0)
        spine(p, fwd=4 + 26 * crouch + (6 if airborne else 0))
        neck_head(p, fwd=-14 * crouch)
        # arms: back in the crouch, swing up at take-off, down for landing
        ak = [(0.0, 0), (0.30, -45), (0.45, 70), (0.68, 40), (0.92, 10), (1.05, -10), (1.4, 0)]
        sw = 0
        for (t0, a0), (t1, a1) in zip(ak, ak[1:]):
            if t0 <= t <= t1:
                sw = lerp(a0, a1, ease_io((t - t0) / (t1 - t0)))
                break
        relaxed_arms(p, c, lower=32 - max(sw, 0) * 0.15, elbow=-18 - 20 * crouch, swing=sw + 4, curl=25)
        for s, sg in SIDES:
            if not airborne:
                pitch = 0.0
                if 0.36 < t <= 0.42:
                    pitch = 35 * (t - 0.36) / 0.06
                ank, end = foot_target(c, s, (sg * 0.13, c.ankle[s].y, c.ankle_h), pitch)
            else:
                tt = (t - 0.42) / 0.5
                tuck = math.sin(math.pi * tt)
                ank = Vector((sg * 0.13, 0.05 * tuck, c.ankle_h + z - 0.02 + 0.20 * tuck))
                end = q(X, lerp(35, 10, min(tt * 2, 1)) if tt < 0.8 else lerp(10, 0, (tt - 0.8) / 0.2))
            leg_ik(p, c, s, ank, end)
        return p
    return fn, int(D * FPS), dict(loop=False)


# ------------------------------------------------------------------ sled set
def sled_base(c, t, lean=0.0, crouch=0.0, lift=0.0, grips=("_l", "_r")):
    """Seated on the sled, hands on the side handles, heels on the floor near the curl."""
    p = Pose()
    b = breathe(p, t, rate=0.35, amp=0.7)
    p.pelvis_loc = Vector((0.06 * lean, 0.01 + 0.02 * crouch, SEAT_HIP_Z + lift))
    p.pelvis_rot = q(Y, -10 * lean) @ q(X, -14 + 6 * crouch)
    spine(p, fwd=24 + 18 * crouch, lean=22 * lean, turn=6 * lean)
    neck_head(p, fwd=-16 - 14 * crouch, lean=-12 * lean)
    for s, sg in SIDES:
        g = SLED_GRIP.copy()
        g.x *= sg
        if s in grips:
            p.ik["arm" + s] = dict(target=g + Vector((0, 0, 0.0)),
                                  pole=Vector((sg * 0.9, 0.35, 0.35)), end_rot=None)
            p.add("hand" + s, q(Y, sg * 10))
            grip(p, c, s)
        f = SLED_FOOT.copy()
        f.x *= sg
        f.y += 0.20 * crouch
        f.z += 0.14 * crouch + lift * 0.4
        leg_ik(p, c, s, f + Vector((lean * 0.02, 0, 0)), q(X, -8 - 10 * crouch) @ q(Z, sg * 10), pole_fwd=0.6)
        # knees point up/out
        p.ik["leg" + s]["pole"] = Vector((sg * 0.45, -0.6, 0.9))
    return p


def sled_sit(c):
    D = 2.0
    def fn(t):
        return sled_base(c, t, lean=0.03 * math.sin(2 * math.pi * t / D))
    return fn, int(D * FPS), dict(loop=True)


def sled_lean(c, direction):
    D = 1.0
    def fn(t):
        wob = 0.05 * math.sin(2 * math.pi * t / D)
        return sled_base(c, t, lean=direction * (1.0 + wob))
    return fn, int(D * FPS), dict(loop=True)


def sled_air(c):
    D = 1.0
    def fn(t):
        w = math.sin(2 * math.pi * t / D)
        return sled_base(c, t, crouch=1.0 + 0.05 * w, lift=0.03)
    return fn, int(D * FPS), dict(loop=True)


def _phase(t, t_in, t_hold, t_out):
    """0 -> 1 over [0,t_in], hold, 1 -> 0 over [t_hold,t_out]."""
    if t < t_in:
        return ease_io(t / t_in)
    if t < t_hold:
        return 1.0
    return 1.0 - ease_io(min((t - t_hold) / (t_out - t_hold), 1.0))


def superman(c):
    D = 1.6
    def fn(t):
        a = _phase(t, 0.35, 1.15, D)
        base = sled_base(c, t, crouch=1.0 - a)
        if a <= 0.001:
            return base
        p = Pose()
        fl = math.sin(2 * math.pi * t / 0.8) * 0.015 * a
        # body flies out behind the sled, face down, arms straight to the handles
        hip_sit = base.pelvis_loc
        hip_sm = Vector((0, 0.60, 0.42 + fl))
        p.pelvis_loc = hip_sit.lerp(hip_sm, a)
        p.pelvis_rot = base.pelvis_rot.slerp(q(X, 84), a)
        spine(p, fwd=lerp(42, -14, a))
        neck_head(p, fwd=lerp(-30, -38, a))
        for s, sg in SIDES:
            g = SLED_GRIP.copy(); g.x *= sg
            p.ik["arm" + s] = dict(target=g, pole=Vector((sg * 0.8, 0.3, lerp(0.35, 1.0, a))), end_rot=None)
            grip(p, c, s)
            p.add("hand" + s, q(Y, sg * 10))
            # legs: straight back, slightly apart, toes pointed
            if a > 0.5:
                pass
            p.add("thigh" + s, q(Y, -sg * 6 * a) @ q(X, lerp(-70, 4, a)))
            p.add("calf" + s, q(X, lerp(80, 4, a)))
            p.add("foot" + s, q(X, lerp(0, 45, a)))
        # crossfade with the seated pose for the first/last frames (IK legs only when seated)
        if a < 0.999:
            for s, sg in SIDES:
                if a < 0.35:
                    p.ik["leg" + s] = base.ik["leg" + s]
        return p
    return fn, int(D * FPS), dict(loop=False)


def spread_eagle(c):
    """Star: off the seat, leaning back, legs straight and spread forward, arms up and out."""
    D = 1.4
    def fn(t):
        a = _phase(t, 0.30, 1.0, D)
        base = sled_base(c, t, crouch=1.0 - a)
        if a <= 0.001:
            return base
        p = Pose()
        fl = 0.012 * math.sin(2 * math.pi * t / 0.7) * a
        p.pelvis_loc = base.pelvis_loc.lerp(Vector((0, 0.08, 0.36 + fl)), a)
        p.pelvis_rot = base.pelvis_rot.slerp(q(X, -28), a)
        spine(p, fwd=lerp(42, 6, a))
        neck_head(p, fwd=lerp(-30, 8, a))
        for s, sg in SIDES:
            if a < 0.3:
                p.ik["arm" + s] = base.ik["arm" + s]
                grip(p, c, s)
                p.ik["leg" + s] = base.ik["leg" + s]
                continue
            p.add("upperarm" + s, q(Y, -sg * lerp(0, 78, a)) @ q(X, -16 * a))
            p.add("lowerarm" + s, q(c.elbow_axis[s], -34 * a))
            hand_curl(p, c, s, 4)
            p.add("thigh" + s, q(Y, -sg * 34 * a) @ q(X, -lerp(60, 62, a)))
            p.add("calf" + s, q(X, lerp(60, 4, a)))
            p.add("foot" + s, q(X, 25 * a))
        return p
    return fn, int(D * FPS), dict(loop=False)


def sled_grab(c):
    """Right hand grabs the sled side, left hand waves overhead."""
    D = 1.6
    def fn(t):
        a = _phase(t, 0.30, 1.25, D)
        p = sled_base(c, t, crouch=0.8, lift=0.04 * a, grips=("_r",) if a > 0.25 else ("_l", "_r"))
        if a > 0.25:
            s, sg = "_l", 1
            w = math.sin(2 * math.pi * 2.6 * t)
            p.add("upperarm_l", q(Y, -lerp(0, 128, a)) @ q(X, 12 * a))
            p.add("lowerarm_l", q(c.elbow_axis["_l"], -10 + 30 * a + 22 * w * a))
            p.add("hand_l", q(Z, 18 * w * a))
            hand_curl(p, c, "_l", 6)
            p.add("spine_03", q(Y, -8 * a) @ q(Z, 10 * a))
            p.add("head", q(Z, 18 * a) @ q(X, -6 * a))
            # torso twists towards the grabbing hand
            p.add("spine_02", q(Z, -6 * a))
        return p
    return fn, int(D * FPS), dict(loop=False)


CLIPS = {
    "idle": idle, "walk": walk, "run": run, "jump": jump,
    "sled_sit": sled_sit,
    "sled_lean_left": lambda c: sled_lean(c, 1.0),
    "sled_lean_right": lambda c: sled_lean(c, -1.0),
    "sled_air": sled_air, "superman": superman, "spread_eagle": spread_eagle, "sled_grab": sled_grab,
}
