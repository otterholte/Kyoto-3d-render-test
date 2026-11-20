// Input: keyboard (WASD / arrows, Shift run), mouse drag orbit + wheel zoom,
// touch: left virtual joystick, right-side drag look, pinch zoom, run toggle.
export class Input {
  constructor(canvas, ui) {
    this.canvas = canvas;
    this.keys = new Set();
    this.move = { x: 0, y: 0 };      // x = right, y = forward (-1..1)
    this.lookDelta = { x: 0, y: 0 };
    this.zoomFactor = 1;
    this.runToggle = false;
    this.touchMode = false;
    this.joy = { id: null, ox: 0, oy: 0, x: 0, y: 0 };
    this.lookers = new Map();        // pointerId -> {x, y}
    this.pinchD = 0;
    this.joyEl = ui.joy; this.knobEl = ui.knob;
    this.anyInput = false;
    this.R = 58;

    addEventListener('keydown', (e) => {
      if (e.target && /INPUT|TEXTAREA|SELECT/.test(e.target.tagName) && e.target.type !== 'range') return;
      const k = e.key.toLowerCase();
      if (['w', 'a', 's', 'd', 'arrowup', 'arrowdown', 'arrowleft', 'arrowright', 'shift'].includes(k)) {
        this.keys.add(k); this.anyInput = true;
        if (k.startsWith('arrow') && e.target === document.body) e.preventDefault();
      }
    });
    addEventListener('keyup', (e) => this.keys.delete(e.key.toLowerCase()));
    addEventListener('blur', () => { this.keys.clear(); this.endJoy(); this.lookers.clear(); });

    canvas.addEventListener('contextmenu', (e) => e.preventDefault());
    canvas.addEventListener('pointerdown', (e) => this.down(e));
    addEventListener('pointermove', (e) => this.moveEv(e), { passive: false });
    addEventListener('pointerup', (e) => this.up(e));
    addEventListener('pointercancel', (e) => this.up(e));
    canvas.addEventListener('wheel', (e) => { e.preventDefault(); this.zoomFactor *= Math.exp(e.deltaY * 0.0012); }, { passive: false });
    document.addEventListener('gesturestart', (e) => e.preventDefault());
  }

  down(e) {
    this.anyInput = true;
    if (e.pointerType === 'touch') {
      this.touchMode = true;
      const w = innerWidth;
      if (this.joy.id === null && e.clientX < w * 0.45 && e.clientY > innerHeight * 0.3) {
        this.joy.id = e.pointerId; this.joy.ox = e.clientX; this.joy.oy = e.clientY; this.joy.x = this.joy.y = 0;
        this.joyEl.style.left = e.clientX + 'px'; this.joyEl.style.top = e.clientY + 'px';
        this.joyEl.classList.add('on'); this.knobEl.style.transform = 'translate(0px,0px)';
      } else {
        this.lookers.set(e.pointerId, { x: e.clientX, y: e.clientY });
        if (this.lookers.size === 2) this.pinchD = this.pinchDist();
      }
    } else {
      this.lookers.set(e.pointerId, { x: e.clientX, y: e.clientY });
      try { this.canvas.setPointerCapture(e.pointerId); } catch { /* ignore */ }
    }
  }

  pinchDist() {
    const [a, b] = [...this.lookers.values()];
    return Math.hypot(a.x - b.x, a.y - b.y);
  }

  moveEv(e) {
    if (e.pointerId === this.joy.id) {
      let dx = e.clientX - this.joy.ox, dy = e.clientY - this.joy.oy;
      const l = Math.hypot(dx, dy);
      if (l > this.R) { dx *= this.R / l; dy *= this.R / l; }
      this.joy.x = dx / this.R; this.joy.y = -dy / this.R;
      this.knobEl.style.transform = `translate(${dx}px,${dy}px)`;
      e.preventDefault();
      return;
    }
    const L = this.lookers.get(e.pointerId);
    if (!L) return;
    if (this.lookers.size === 2) {
      L.x = e.clientX; L.y = e.clientY;
      const d = this.pinchDist();
      if (this.pinchD > 0 && d > 0) this.zoomFactor *= this.pinchD / d;
      this.pinchD = d;
    } else {
      const s = e.pointerType === 'touch' ? 0.0065 : 0.005;
      this.lookDelta.x += (e.clientX - L.x) * s;
      this.lookDelta.y += (e.clientY - L.y) * s * 0.8;
      L.x = e.clientX; L.y = e.clientY;
    }
    e.preventDefault();
  }

  up(e) {
    if (e.pointerId === this.joy.id) { this.endJoy(); return; }
    this.lookers.delete(e.pointerId);
    this.pinchD = this.lookers.size === 2 ? this.pinchDist() : 0;
  }

  endJoy() {
    this.joy.id = null; this.joy.x = this.joy.y = 0;
    this.joyEl.classList.remove('on');
  }

  // per-frame read
  sample() {
    const k = this.keys;
    let x = 0, y = 0;
    if (k.has('w') || k.has('arrowup')) y += 1;
    if (k.has('s') || k.has('arrowdown')) y -= 1;
    if (k.has('d') || k.has('arrowright')) x += 1;
    if (k.has('a') || k.has('arrowleft')) x -= 1;
    let mag = Math.hypot(x, y);
    if (mag > 1) { x /= mag; y /= mag; }
    let run = k.has('shift');
    if (this.joy.id !== null) {
      const jm = Math.hypot(this.joy.x, this.joy.y);
      if (jm > 0.12) {
        const f = (jm - 0.12) / 0.88 / jm;
        x = this.joy.x * f; y = this.joy.y * f;
        if (jm > 0.97 && this.runToggle) run = true;
      }
      run = run || this.runToggle;
    } else if (this.runToggle) run = true;
    const look = { x: this.lookDelta.x, y: this.lookDelta.y };
    this.lookDelta.x = this.lookDelta.y = 0;
    const zoom = this.zoomFactor;
    this.zoomFactor = 1;
    return { x, y, run, look, zoom };
  }
}
