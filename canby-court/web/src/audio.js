// Optional procedural sound (Web Audio, no files): wind bed, summer birdsong, winter hush, sled runner hiss scaled
// by speed and skid, pop / landing / wipeout cues. Started only from the sound button (user gesture).
export class Sound {
  constructor() { this.ctx = null; this.on = false; this.season = 'summer'; this.birdT = 2; }
  start() {
    if (!this.ctx) {
      const AC = window.AudioContext || window.webkitAudioContext;
      if (!AC) return false;
      const c = this.ctx = new AC();
      const noise = c.createBuffer(1, c.sampleRate * 2, c.sampleRate);
      const d = noise.getChannelData(0);
      let b = 0;
      for (let i = 0; i < d.length; i++) { const w = Math.random() * 2 - 1; b = 0.985 * b + 0.15 * w; d[i] = b * 0.6 + w * 0.08; }
      this.noise = noise;
      this.master = c.createGain(); this.master.gain.value = 0.8; this.master.connect(c.destination);
      const src = (buf) => { const s = c.createBufferSource(); s.buffer = buf; s.loop = true; s.start(); return s; };
      // wind
      this.windF = c.createBiquadFilter(); this.windF.type = 'lowpass'; this.windF.frequency.value = 500;
      this.windG = c.createGain(); this.windG.gain.value = 0.12;
      src(noise).connect(this.windF); this.windF.connect(this.windG); this.windG.connect(this.master);
      // sled hiss
      this.hissF = c.createBiquadFilter(); this.hissF.type = 'bandpass'; this.hissF.frequency.value = 2400; this.hissF.Q.value = 0.7;
      this.hissG = c.createGain(); this.hissG.gain.value = 0;
      const white = c.createBuffer(1, c.sampleRate, c.sampleRate); const wd = white.getChannelData(0); for (let i = 0; i < wd.length; i++) wd[i] = Math.random() * 2 - 1;
      this.white = white;
      src(white).connect(this.hissF); this.hissF.connect(this.hissG); this.hissG.connect(this.master);
    }
    this.ctx.resume();
    this.on = true; this.master.gain.setTargetAtTime(0.8, this.ctx.currentTime, 0.1);
    return true;
  }
  stop() { if (this.ctx) { this.master.gain.setTargetAtTime(0, this.ctx.currentTime, 0.1); } this.on = false; }
  update(dt, { speed = 0, sledding = false, airborne = false, skid = 0 }) {
    if (!this.on || !this.ctx) return;
    const t = this.ctx.currentTime;
    const gust = 0.5 + 0.5 * Math.sin(t * 0.31) * Math.sin(t * 0.13 + 1);
    const winter = this.season === 'winter';
    this.windG.gain.setTargetAtTime((winter ? 0.1 : 0.06) + gust * 0.06 + (sledding ? Math.min(0.25, speed * 0.012) : 0), t, 0.3);
    this.windF.frequency.setTargetAtTime(350 + gust * 300 + speed * 40, t, 0.3);
    const hiss = sledding && !airborne ? Math.min(0.35, speed * 0.025) + skid * 0.3 : 0;
    this.hissG.gain.setTargetAtTime(hiss, t, 0.05);
    this.hissF.frequency.setTargetAtTime(1600 + speed * 90 + skid * 1500, t, 0.1);
    if (!winter) { this.birdT -= dt; if (this.birdT <= 0) { this.bird(); this.birdT = 2.5 + Math.random() * 6; } }
  }
  bird() {
    const c = this.ctx, t = c.currentTime;
    const n = 2 + Math.floor(Math.random() * 4), f0 = 2600 + Math.random() * 1800;
    for (let i = 0; i < n; i++) {
      const o = c.createOscillator(), g = c.createGain();
      const s = t + i * (0.09 + Math.random() * 0.05);
      o.frequency.setValueAtTime(f0 * (1 + 0.15 * Math.random()), s);
      o.frequency.exponentialRampToValueAtTime(f0 * (0.7 + Math.random() * 0.6), s + 0.07);
      g.gain.setValueAtTime(0, s); g.gain.linearRampToValueAtTime(0.025, s + 0.01); g.gain.exponentialRampToValueAtTime(0.0005, s + 0.08);
      const pan = c.createStereoPanner ? c.createStereoPanner() : null;
      o.connect(g); if (pan) { pan.pan.value = Math.random() * 1.6 - 0.8; g.connect(pan); pan.connect(this.master); } else g.connect(this.master);
      o.start(s); o.stop(s + 0.1);
    }
  }
  cue(type) {
    if (!this.on || !this.ctx) return;
    const c = this.ctx, t = c.currentTime;
    if (type === 'land' || type === 'wipeout' || type === 'bump') {
      const s = c.createBufferSource(); s.buffer = this.noise;
      const f = c.createBiquadFilter(); f.type = 'lowpass'; f.frequency.value = type === 'wipeout' ? 900 : 500;
      const g = c.createGain(); g.gain.setValueAtTime(type === 'wipeout' ? 0.9 : 0.6, t); g.gain.exponentialRampToValueAtTime(0.001, t + (type === 'wipeout' ? 0.7 : 0.25));
      s.connect(f); f.connect(g); g.connect(this.master); s.start(t); s.stop(t + 0.8);
    } else if (type === 'pop' || type === 'trick' || type === 'go') {
      const o = c.createOscillator(), g = c.createGain();
      o.type = 'triangle';
      const f = type === 'trick' ? 880 : type === 'go' ? 660 : 440;
      o.frequency.setValueAtTime(f, t); o.frequency.exponentialRampToValueAtTime(f * 1.5, t + 0.12);
      g.gain.setValueAtTime(0.12, t); g.gain.exponentialRampToValueAtTime(0.001, t + 0.2);
      o.connect(g); g.connect(this.master); o.start(t); o.stop(t + 0.22);
    }
  }
}
