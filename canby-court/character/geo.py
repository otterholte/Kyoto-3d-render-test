"""Small numpy/scipy mesh helpers used by the garment, hair and sled builders."""
import numpy as np
import scipy.sparse as sp
import bpy


def faces_to_edges(faces):
    e = []
    for f in faces:
        n = len(f)
        for i in range(n):
            a, b = f[i], f[(i + 1) % n]
            e.append((min(a, b), max(a, b)))
    return e


def adjacency(nv, faces):
    e = np.array(sorted(set(faces_to_edges(faces))), dtype=np.int64)
    if len(e) == 0:
        return sp.csr_matrix((nv, nv))
    data = np.ones(len(e) * 2)
    rows = np.concatenate([e[:, 0], e[:, 1]])
    cols = np.concatenate([e[:, 1], e[:, 0]])
    return sp.csr_matrix((data, (rows, cols)), shape=(nv, nv))


def laplacian_avg(A):
    deg = np.asarray(A.sum(axis=1)).ravel()
    deg[deg == 0] = 1
    return sp.diags(1.0 / deg) @ A


def taubin(co, A, iters=10, lam=0.5, mu=-0.53, fixed=None, weights=None):
    """Volume-preserving smoothing. weights: per-vertex 0..1 amount."""
    L = laplacian_avg(A)
    co = co.copy()
    w = np.ones(len(co)) if weights is None else weights
    if fixed is not None:
        w = w.copy()
        w[fixed] = 0
    w = w[:, None]
    for _ in range(iters):
        co = co + lam * w * (L @ co - co)
        co = co + mu * w * (L @ co - co)
    return co


def smooth_field(f, A, iters=5, lam=0.5):
    L = laplacian_avg(A)
    for _ in range(iters):
        f = f + lam * (L @ f - f)
    return f


def vertex_normals(co, faces):
    n = np.zeros_like(co)
    for f in faces:
        p = co[list(f)]
        # Newell normal
        nn = np.zeros(3)
        for i in range(len(f)):
            a, b = p[i], p[(i + 1) % len(f)]
            nn += np.array([(a[1] - b[1]) * (a[2] + b[2]), (a[2] - b[2]) * (a[0] + b[0]),
                            (a[0] - b[0]) * (a[1] + b[1])])
        for i in f:
            n[i] += nn
    ln = np.linalg.norm(n, axis=1, keepdims=True)
    ln[ln == 0] = 1
    return n / ln


def vertex_normals_fast(co, faces_arr_list):
    """faces given as list of lists; triangulate fan and accumulate area-weighted normals."""
    tris = []
    for f in faces_arr_list:
        for i in range(1, len(f) - 1):
            tris.append((f[0], f[i], f[i + 1]))
    t = np.array(tris, dtype=np.int64)
    fn = np.cross(co[t[:, 1]] - co[t[:, 0]], co[t[:, 2]] - co[t[:, 0]])
    n = np.zeros_like(co)
    for k in range(3):
        np.add.at(n, t[:, k], fn)
    ln = np.linalg.norm(n, axis=1, keepdims=True)
    ln[ln == 0] = 1
    return n / ln


def boundary_loops(faces):
    """Return list of ordered vertex loops along open boundaries."""
    cnt = {}
    nxt = {}
    for f in faces:
        n = len(f)
        for i in range(n):
            a, b = f[i], f[(i + 1) % n]
            k = (min(a, b), max(a, b))
            cnt[k] = cnt.get(k, 0) + 1
            nxt[(a, b)] = True
    bedges = [k for k, c in cnt.items() if c == 1]
    # orient using face winding: boundary edge (a,b) appears as directed (a,b) in its face
    succ = {}
    for a, b in bedges:
        if (a, b) in nxt:
            succ[b] = a  # reverse so loop runs opposite to face winding
        else:
            succ[a] = b
    loops, seen = [], set()
    for s in list(succ.keys()):
        if s in seen:
            continue
        loop = [s]
        seen.add(s)
        c = succ.get(s)
        while c is not None and c not in seen:
            loop.append(c)
            seen.add(c)
            c = succ.get(c)
        loops.append(loop)
    return loops


def make_object(name, co, faces, collection, uv_loops=None, smooth=True, uv_name="UVMap"):
    me = bpy.data.meshes.new(name)
    me.from_pydata([tuple(map(float, c)) for c in co], [], [list(map(int, f)) for f in faces])
    if uv_loops is not None:
        uvl = me.uv_layers.new(name=uv_name)
        uvl.data.foreach_set("uv", np.asarray(uv_loops, dtype=np.float32).ravel())
    me.update()
    if smooth:
        me.shade_smooth() if hasattr(me, "shade_smooth") else None
        for p in me.polygons:
            p.use_smooth = True
    ob = bpy.data.objects.new(name, me)
    collection.objects.link(ob)
    return ob


def mesh_arrays(ob):
    me = ob.data
    co = np.zeros(len(me.vertices) * 3)
    me.vertices.foreach_get("co", co)
    co = co.reshape(-1, 3)
    faces = [list(p.vertices) for p in me.polygons]
    uv = None
    if me.uv_layers:
        uv = np.zeros(len(me.loops) * 2)
        me.uv_layers[0].data.foreach_get("uv", uv)
        uv = uv.reshape(-1, 2)
    return co, faces, uv


def value_noise3(p, freq, seed=0):
    """Cheap smooth 3D value noise in [-1,1] for arrays of points (n,3)."""
    rng = np.random.default_rng(seed)
    N = 64
    grid = rng.uniform(-1, 1, (N, N, N))
    q = p * freq
    i0 = np.floor(q).astype(np.int64)
    f = q - i0
    f = f * f * (3 - 2 * f)
    out = 0
    for dx in (0, 1):
        for dy in (0, 1):
            for dz in (0, 1):
                w = ((f[:, 0] if dx else 1 - f[:, 0]) * (f[:, 1] if dy else 1 - f[:, 1])
                     * (f[:, 2] if dz else 1 - f[:, 2]))
                out = out + w * grid[(i0[:, 0] + dx) % N, (i0[:, 1] + dy) % N, (i0[:, 2] + dz) % N]
    return out


def fbm3(p, freq, octaves=4, seed=0):
    s, a, tot = 0, 1.0, 0
    for o in range(octaves):
        s = s + a * value_noise3(p, freq * (2 ** o), seed + o)
        tot += a
        a *= 0.5
    return s / tot
