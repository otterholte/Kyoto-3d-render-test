// "Renders" gallery: shows the Cycles finals listed in assets/renders/renders.json (path from dist/manifest.json).
// Accepted shapes: [ "a.jpg", ... ]  |  [ {file|src, title, caption, thumb?}, ... ]  |  { renders: [...] }.
// File paths are relative to the json's folder unless they start with "assets/".
export class Gallery {
  constructor({ list, empty, lightbox, img, caption, close, prev, next }, url) {
    Object.assign(this, { list, empty, lightbox, img, caption, url });
    this.items = null;
    this.i = 0;
    close.onclick = () => this.hide();
    prev.onclick = () => this.show(this.i - 1);
    next.onclick = () => this.show(this.i + 1);
    lightbox.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') { e.stopPropagation(); this.hide(); }
      if (e.key === 'ArrowLeft') this.show(this.i - 1);
      if (e.key === 'ArrowRight') this.show(this.i + 1);
    });
    lightbox.addEventListener('click', (e) => { if (e.target === lightbox) this.hide(); });
  }

  async open() {
    if (this.items) return;
    this.items = [];
    if (this.url) {
      try {
        const r = await fetch(this.url, { cache: 'no-store' });
        const j = r.ok ? await r.json() : [];
        const arr = Array.isArray(j) ? j : (j.renders || j.images || []);
        const dir = this.url.replace(/[^/]*$/, '');
        const res = (p) => (/^assets\//.test(p) ? p : dir + p);
        this.items = arr.map((x) => (typeof x === 'string' ? { file: x } : x)).filter((x) => x.file || x.src)
          .map((x) => ({ src: res(x.file || x.src), thumb: res(x.thumb || x.file || x.src), title: x.title || '', caption: x.caption || x.note || '' }));
      } catch (e) { console.warn('renders.json unavailable', e); }
    }
    this.list.textContent = '';
    this.empty.hidden = this.items.length > 0;
    this.items.forEach((it, i) => {
      const li = document.createElement('li');
      const b = document.createElement('button');
      b.className = 'thumb';
      const im = document.createElement('img');
      im.loading = 'lazy'; im.decoding = 'async'; im.src = it.thumb; im.alt = it.title || `Render ${i + 1}`;
      const t = document.createElement('span'); t.textContent = it.title || `Render ${i + 1}`;
      b.append(im, t);
      b.onclick = () => this.show(i);
      li.appendChild(b); this.list.appendChild(li);
    });
  }

  show(i) {
    if (!this.items || !this.items.length) return;
    this.i = (i + this.items.length) % this.items.length;
    const it = this.items[this.i];
    this.img.src = it.src; this.img.alt = it.title || 'Render';
    this.caption.textContent = [it.title, it.caption].filter(Boolean).join(' — ');
    this.lightbox.hidden = false;
    this.lightbox.focus();
  }

  hide() { this.lightbox.hidden = true; this.img.removeAttribute('src'); }
}
