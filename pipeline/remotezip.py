"""Read individual members of a huge remote ZIP via HTTP Range requests (no full download)."""
import io
import zipfile
import requests

UA = {"User-Agent": "higashiyama-research/1.0 (open-data reconstruction)"}


class RangeFile(io.RawIOBase):
    def __init__(self, url, block=1 << 20):
        self.url, self.pos, self.block = url, 0, block
        r = requests.head(url, headers=UA, allow_redirects=True, timeout=60)
        self.url = r.url
        self.size = int(r.headers["Content-Length"])
        self.cache = {}

    def seekable(self):
        return True

    def readable(self):
        return True

    def tell(self):
        return self.pos

    def seek(self, off, whence=0):
        self.pos = off if whence == 0 else self.pos + off if whence == 1 else self.size + off
        return self.pos

    def _blk(self, i):
        if i not in self.cache:
            a = i * self.block
            b = min(self.size, a + self.block) - 1
            for attempt in range(5):
                try:
                    r = requests.get(self.url, headers={**UA, "Range": f"bytes={a}-{b}"}, timeout=120)
                    r.raise_for_status()
                    self.cache[i] = r.content
                    break
                except Exception:
                    if attempt == 4:
                        raise
            if len(self.cache) > 256:
                self.cache.pop(next(iter(self.cache)))
        return self.cache[i]

    def read(self, n=-1):
        if n < 0:
            n = self.size - self.pos
        out = bytearray()
        while n > 0 and self.pos < self.size:
            i, o = divmod(self.pos, self.block)
            chunk = self._blk(i)[o:o + n]
            out += chunk
            self.pos += len(chunk)
            n -= len(chunk)
        return bytes(out)

    def readinto(self, b):
        d = self.read(len(b))
        b[:len(d)] = d
        return len(d)


def open_remote_zip(url):
    return zipfile.ZipFile(RangeFile(url))
