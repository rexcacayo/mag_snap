# SPDX-FileCopyrightText: 2026 Ricardo Lugaresi
# SPDX-License-Identifier: GPL-3.0-or-later

"""Corte curvo: la pieza se separa siguiendo la línea dibujada sobre la superficie.

Cómo funciona:
1. Entre clic y clic la línea va pegada a la superficie (se ajusta punto a punto).
2. Con la línea cerrada se tiende una «pompa de jabón» (superficie mínima) que la tiene por borde:
   es la cara del corte. Sigue la barbilla, la axila o el borde del músculo y no corta nada más.
3. Esa cara se convierte en una lámina finísima y se resta del modelo: queda partido justo por
   ahí. Cada trozo se asigna a un lado de la lámina y salen dos piezas.
4. Los conectores se colocan sobre la cara del corte, perpendiculares a ella, donde hay pared.

En «Recto» la cara es plana (el plano medio de la línea), pero igualmente solo corta dentro de la
línea: un plano no atraviesa otras partes del modelo que estén lejos.
"""
import math

import bmesh
import bpy
import numpy as np
from mathutils import Vector, geometry
from mathutils.bvhtree import BVHTree

from . import common

KERF_MM = 0.05          # grosor de la lámina que separa las piezas
MARGIN_MM = 1.0         # lo que la cara del corte sobresale de la superficie
MIN_RING, MAX_RING = 96, 320


# --------------------------------------------------------------------------- línea sobre la superficie
def _snap(tree, p):
    hit = tree.find_nearest(Vector(p))
    return np.array(hit[0]) if hit[0] is not None else np.asarray(p, float)


def segment_on_surface(tree, a, b, step):
    """Puntos entre a y b (sin incluir b) pegados a la superficie."""
    a, b = np.asarray(a, float), np.asarray(b, float)
    n = max(1, int(math.ceil(np.linalg.norm(b - a) / max(step, 1e-9))))
    out = [a]
    for i in range(1, n):
        out.append(_snap(tree, a + (b - a) * (i / n)))
    return out


def surface_loop(tree, clicks, step):
    """Línea cerrada densa pegada a la superficie que pasa por los clics."""
    clicks = [np.asarray(c, float) for c in clicks]
    pts, fixed = [], []
    for i, a in enumerate(clicks):
        seg = segment_on_surface(tree, a, clicks[(i + 1) % len(clicks)], step)
        fixed.append(len(pts))
        pts += seg
    P = np.array(pts)
    fix = np.zeros(len(P), bool)
    fix[fixed] = True
    # suavizado suave (la línea no zigzaguea por el ruido de la malla) y vuelta a la superficie
    for _ in range(3):
        avg = (np.roll(P, 1, 0) + np.roll(P, -1, 0)) / 2
        P = np.where(fix[:, None], P, 0.5 * P + 0.5 * avg)
        P = np.array([p if f else _snap(tree, p) for p, f in zip(P, fix)])
    return P


def open_path(tree, clicks, step):
    """Para dibujar mientras se pincha: tramos pegados a la superficie entre los clics."""
    pts = []
    for a, b in zip(clicks, clicks[1:]):
        pts += segment_on_surface(tree, a, b, step)
    if clicks:
        pts.append(np.asarray(clicks[-1], float))
    return pts


def resample_closed(P, n):
    seg = np.linalg.norm(np.roll(P, -1, 0) - P, axis=1)
    s = np.concatenate([[0], np.cumsum(seg)])
    total = s[-1]
    t = np.linspace(0, total, n, endpoint=False)
    Q = np.vstack([P, P[:1]])
    out = np.empty((n, 3))
    for k in range(3):
        out[:, k] = np.interp(t, s, Q[:, k])
    return out, total


def perimeter(P):
    return float(np.linalg.norm(np.roll(P, -1, 0) - P, axis=1).sum())


# --------------------------------------------------------------------------- cara del corte
def _fit(P):
    c = P.mean(0)
    _u, sv, vt = np.linalg.svd(P - c)
    if sv[1] < 1e-9 * max(sv[0], 1e-12):
        raise common.AddonError('Los puntos están en línea recta: rodea la pieza con la línea.')
    n = vt[2]
    dom = int(np.argmax(np.abs(n)))
    if n[dom] < 0:
        n = -n
    u = vt[0]
    v = np.cross(n, u)
    return c, u, v, n


def _signed_area(xy):
    x, y = xy[:, 0], xy[:, 1]
    return 0.5 * float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))


def _simple(xy):
    """True si el contorno 2D no se cruza consigo mismo."""
    a = xy
    b = np.roll(xy, -1, 0)
    n = len(a)
    d = b - a

    def cross(p, q):
        return p[..., 0] * q[..., 1] - p[..., 1] * q[..., 0]
    for i in range(n):
        j = np.arange(i + 2, n)
        if i == 0:
            j = j[j != n - 1]
        if not len(j):
            continue
        r, s = d[i], d[j]
        den = cross(r, s)
        qp = a[j] - a[i]
        with np.errstate(divide='ignore', invalid='ignore'):
            t = cross(qp, s) / den
            w = cross(qp, r) / den
        if np.any((np.abs(den) > 1e-15) & (t > 0) & (t < 1) & (w > 0) & (w < 1)):
            return False
    return True


def _outward(xy):
    """Normal hacia fuera en cada punto del contorno 2D (antihorario), algo suavizada."""
    t = np.zeros_like(xy)
    for k in (1, 2, 3):
        t += np.roll(xy, -k, 0) - np.roll(xy, k, 0)
    t /= np.maximum(np.linalg.norm(t, axis=1, keepdims=True), 1e-12)
    return np.column_stack([t[:, 1], -t[:, 0]])


def _point_in_poly(pts, poly):
    a, b = poly, np.roll(poly, -1, 0)
    x, y = pts[:, 0:1], pts[:, 1:2]
    crosses = (a[:, 1] > y) != (b[:, 1] > y)
    with np.errstate(divide='ignore', invalid='ignore'):
        xi = (b[:, 0] - a[:, 0]) * (y - a[:, 1]) / (b[:, 1] - a[:, 1]) + a[:, 0]
    return (np.count_nonzero(crosses & (x < xi), axis=1) % 2) == 1


def _dist_to_poly(pts, poly):
    a, b = poly, np.roll(poly, -1, 0)
    d = b - a
    dd = np.maximum((d ** 2).sum(1), 1e-30)
    out = np.empty(len(pts))
    for s in range(0, len(pts), 512):
        p = pts[s:s + 512, None, :]
        t = np.clip(((p - a) * d).sum(2) / dd, 0, 1)
        out[s:s + 512] = np.sqrt((((a + t[..., None] * d) - p) ** 2).sum(2)).min(1)
    return out


def _harmonic(n_verts, edges, fixed, values, iterations=400):
    """Alturas que minimizan la «tensión» (superficie mínima aproximada): gradiente conjugado
    sobre el laplaciano del grafo con los puntos del borde fijos."""
    free = ~fixed
    x = np.where(fixed, values, 0.0)
    if not free.any():
        return x
    i, j = edges[:, 0], edges[:, 1]
    deg = np.bincount(i, minlength=n_verts) + np.bincount(j, minlength=n_verts)

    def lap(z):                        # (L z) con L = D - A
        out = deg * z
        np.subtract.at(out, i, z[j])
        np.subtract.at(out, j, z[i])
        return out

    def A(z):                          # restringido a los libres
        full = np.zeros(n_verts); full[free] = z
        return lap(full)[free]
    b = -lap(np.where(fixed, values, 0.0))[free]
    z = np.zeros(int(free.sum()))
    r = b - A(z)
    p = r.copy()
    rs = float(r @ r)
    for _ in range(iterations):
        if rs < 1e-20:
            break
        Ap = A(p)
        alpha = rs / max(float(p @ Ap), 1e-30)
        z += alpha * p
        r -= alpha * Ap
        new = float(r @ r)
        p = r + (new / rs) * p
        rs = new
    x[free] = z
    return x


def build_film(loop, margin, curved=True):
    """Cara del corte que tiene la línea por borde (más un reborde que sobresale `margin`).
    Devuelve dict con verts (mundo), tris, normal media, máscara de los puntos dentro de la línea."""
    c, u, v, n = _fit(loop)
    q = loop - c
    xy = np.column_stack([q @ u, q @ v])
    h = q @ n
    if _signed_area(xy) < 0:
        xy, h, loop = xy[::-1].copy(), h[::-1].copy(), loop[::-1].copy()
    if not _simple(xy):
        raise common.AddonError('La línea se cruza consigo misma vista desde el corte. '
                                'Rodea la pieza con una línea más sencilla.')
    if not curved:
        dev = float(np.abs(h).max())
        h = np.zeros_like(h)
        margin = margin + 2 * dev
    nb = len(xy)
    spacing = perimeter(np.column_stack([xy, np.zeros(nb)])) / nb
    ring = None
    m = margin
    for _ in range(6):
        cand = xy + _outward(xy) * m
        if _simple(cand):
            ring = cand
            break
        m *= 0.6
    if ring is None:
        raise common.AddonError('No se pudo preparar la cara del corte: la línea hace curvas muy cerradas.')
    lo, hi = xy.min(0), xy.max(0)
    gx, gy = np.meshgrid(np.arange(lo[0], hi[0], spacing), np.arange(lo[1], hi[1], spacing))
    grid = np.column_stack([gx.ravel(), gy.ravel()])
    if len(grid):
        grid = grid[_point_in_poly(grid, xy)]
        grid = grid[_dist_to_poly(grid, xy) > 0.6 * spacing]
    pts2 = np.vstack([ring, xy, grid]) if len(grid) else np.vstack([ring, xy])
    verts_in = [Vector((float(a), float(b))) for a, b in pts2]
    edges_in = [(nb + k, nb + (k + 1) % nb) for k in range(nb)]
    faces_in = [list(range(nb))]
    out = geometry.delaunay_2d_cdt(verts_in, edges_in, faces_in, 1, spacing * 1e-4, True)
    overts, oedges, ofaces, orig_v = out[0], out[1], out[2], out[3]
    V2 = np.array([tuple(p) for p in overts])
    nv = len(V2)
    fixed = np.zeros(nv, bool)
    values = np.zeros(nv)
    inside = np.zeros(nv, bool)
    for k, origs in enumerate(orig_v):
        for o in origs:
            if o < nb:
                fixed[k] = True; values[k] = h[o]
            elif o < 2 * nb:
                fixed[k] = True; values[k] = h[o - nb]
                inside[k] = True
            else:
                inside[k] = True
    tris = []
    for f in ofaces:
        for t in range(1, len(f) - 1):
            tris.append((f[0], f[t], f[t + 1]))
    tris = np.array(tris, int)
    E = np.array([tuple(e) for e in oedges], int)
    hh = _harmonic(nv, E, fixed, values) if curved else np.zeros(nv)
    W = c + np.outer(V2[:, 0], u) + np.outer(V2[:, 1], v) + np.outer(hh, n)
    # orientar triángulos hacia +n
    a, b, cc = W[tris[:, 0]], W[tris[:, 1]], W[tris[:, 2]]
    fn = np.cross(b - a, cc - a)
    flip = (fn @ n) < 0
    tris[flip] = tris[flip][:, ::-1]
    # el contorno exterior (reborde) en orden
    return {'verts': W, 'tris': tris, 'normal': n, 'center': c, 'inside': inside,
            'spacing': spacing, 'loop': loop}


def vertex_normals(film):
    W, T = film['verts'], film['tris']
    fn = np.cross(W[T[:, 1]] - W[T[:, 0]], W[T[:, 2]] - W[T[:, 0]])
    vn = np.zeros_like(W)
    for k in range(3):
        np.add.at(vn, T[:, k], fn)
    vn /= np.maximum(np.linalg.norm(vn, axis=1, keepdims=True), 1e-30)
    return vn


def slab_bmesh(film, kerf):
    """Lámina cerrada de grosor `kerf` alrededor de la cara del corte."""
    W, T = film['verts'], film['tris']
    vn = vertex_normals(film)
    bm = bmesh.new()
    top = [bm.verts.new(tuple(p + d * kerf / 2)) for p, d in zip(W, vn)]
    bot = [bm.verts.new(tuple(p - d * kerf / 2)) for p, d in zip(W, vn)]
    for a, b, c in T:
        bm.faces.new((top[a], top[b], top[c]))
        bm.faces.new((bot[c], bot[b], bot[a]))
    # paredes en el borde exterior: aristas que solo tienen un triángulo
    count = {}
    for a, b, c in T:
        for e in ((a, b), (b, c), (c, a)):
            count[e] = count.get(e, 0) + 1
    for (a, b), k in count.items():
        if (b, a) not in count:
            bm.faces.new((top[b], top[a], bot[a], bot[b]))
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    return bm


def film_tree(film):
    return BVHTree.FromPolygons([tuple(p) for p in film['verts']], [tuple(t) for t in film['tris']])


def prepare(tree, clicks, scale, curved=True):
    """Línea densa + cara del corte a partir de los clics. scale = mm por unidad."""
    clicks = [np.asarray(c, float) for c in clicks]
    if len(clicks) < 3:
        raise common.AddonError('Hacen falta al menos tres puntos: rodea la pieza con la línea.')
    rough = perimeter(np.array(clicks))
    step = rough / 400
    dense = surface_loop(tree, clicks, step)
    total = perimeter(dense)
    n = int(np.clip(total / max(0.4 / scale, 1e-9), MIN_RING, MAX_RING))
    loop, total = resample_closed(dense, n)
    margin = max(MARGIN_MM / scale, 2 * total / n)
    film = build_film(loop, margin, curved)
    film['dense'] = dense
    return film


# --------------------------------------------------------------------------- separar
def _components(bm):
    """Trozos sueltos del bmesh: lista de listas de caras."""
    seen = set()
    parts = []
    for f in bm.faces:
        if f.index in seen:
            continue
        stack, part = [f], []
        seen.add(f.index)
        while stack:
            g = stack.pop()
            part.append(g)
            for e in g.edges:
                for h in e.link_faces:
                    if h.index not in seen:
                        seen.add(h.index)
                        stack.append(h)
        parts.append(part)
    return parts


def _side_of(ftree, points, kerf):
    """+1 / -1 según el lado de la cara del corte; usa los puntos pegados a la lámina si los hay."""
    near_sign, far = [], []
    for p in points:
        loc, nrm, _i, dist = ftree.find_nearest(p)
        if loc is None:
            continue
        s = (p - loc).dot(nrm)
        if dist < kerf * 2:
            near_sign.append(1 if s > 0 else -1)
        far.append(s)
    if near_sign:
        return (1 if sum(near_sign) >= 0 else -1), True
    return (1 if sum(far) >= 0 else -1), False


def _connector_points(model_tree, film, radius, depth, wall, count, eps):
    """Puntos de la cara del corte (y su normal) donde cabe el conector a los dos lados."""
    W, inside = film['verts'], film['inside']
    vn = vertex_normals(film)
    idx = np.nonzero(inside)[0]
    cand, clear = [], []
    for k in idx:
        p = Vector(W[k])
        loc, nrm, _i, dist = model_tree.find_nearest(p)
        if loc is None or (p - loc).dot(nrm) > 0:      # fuera del modelo
            continue
        if dist >= radius + wall:
            cand.append(k); clear.append(dist)
    best = max(clear) if clear else 0.0
    if not cand:
        return [], best
    order = np.argsort(-np.array(clear))
    step = max(1, len(order) // 400)
    need = depth + wall
    good = []
    for o in order[::step]:
        k = cand[o]
        p, n = Vector(W[k]), Vector(vn[k])
        qn = n.to_track_quat('Z', 'Y')
        rim = [Vector()] + [qn @ Vector((radius * math.cos(i * math.pi / 4), radius * math.sin(i * math.pi / 4), 0))
                            for i in range(8)]
        ok = True
        for direction in (n, -n):
            for off in rim:
                loc, _nn, _i, dist = model_tree.ray_cast(p + off + direction * eps, direction)
                if loc is None or dist + eps < need:
                    ok = False; break
            if not ok:
                break
        if ok:
            good.append((k, clear[o]))
    if not good:
        return [], best
    pts = np.array([W[k] for k, _c in good])
    chosen = [good[0][0]]
    if count >= 2 and len(good) > 1:
        dist = np.linalg.norm(pts[:, None] - pts[None], axis=2)
        i, j = np.unravel_index(int(np.argmax(dist)), dist.shape)
        if dist[i, j] >= 2 * radius + wall:
            chosen = [good[i][0], good[j][0]]
    return [(Vector(W[k]), Vector(vn[k])) for k in chosen], best


def _clean(bm, dist):
    """Quita las astillas que deja la lámina en el borde (las booleanas posteriores fallan con ellas)."""
    bmesh.ops.remove_doubles(bm, verts=bm.verts[:], dist=dist)
    bmesh.ops.dissolve_degenerate(bm, edges=bm.edges[:], dist=dist)
    loose = [v for v in bm.verts if not v.link_faces]
    if loose:
        bmesh.ops.delete(bm, geom=loose, context='VERTS')
    bmesh.ops.triangulate(bm, faces=[f for f in bm.faces if len(f.verts) > 4])
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])


def _work_copy(context, model, col):
    bm = common.world_bmesh(context, model)
    try:
        return common.new_object(bm, model.name + '_corte', col, model)
    finally:
        bm.free()


def _slab_object(film, kerf, col, hole=None):
    sb = slab_bmesh(film, kerf)
    slab = common.new_object(sb, 'Lamina_temporal', col)
    sb.free()
    if hole is not None:
        point, normal, r = hole
        span = max(kerf * 40, r * 4)
        cyl = common.cylinder('Agujero_lamina', point, normal, r, span, col)
        try:
            common.boolean(bpy.context, slab, cyl)
        finally:
            common.remove_objects([cyl])
    return slab


def _separate(context, work, slab, ftree, kerf):
    """Resta la lámina y reparte los trozos sueltos a cada lado. Devuelve (bmesh, lados, tocados)."""
    common.boolean(context, work, slab)
    bm = bmesh.new()
    bm.from_mesh(work.data)
    bm.faces.ensure_lookup_table()
    sides = {1: [], -1: []}
    touched = {1: 0, -1: 0}
    for part in _components(bm):
        verts = {v for f in part for v in f.verts}
        pts = [v.co.copy() for v in verts]
        if len(pts) > 600:
            pts = pts[::len(pts) // 600]
        s, near = _side_of(ftree, pts, kerf)
        sides[s].append(part)
        touched[s] += int(near)
    return bm, sides, touched


def _bigger(sides):
    def volume(faces):
        return abs(sum(f.calc_area() * f.normal.dot(f.calc_center_median()) for f in faces) / 3)
    vol = {s: sum(volume(p) for p in sides[s]) for s in (1, -1)}
    return 1 if vol[1] >= vol[-1] else -1


# --------------------------------------------------------------------------- corte desde la vista
def parse_rays(text):
    """'ox,oy,oz,dx,dy,dz;...' -> [(origen, dirección)]."""
    out = []
    for item in text.split(';'):
        if item.strip():
            v = [float(x) for x in item.split(',')]
            out.append((np.array(v[:3]), np.array(v[3:6]) / max(np.linalg.norm(v[3:6]), 1e-12)))
    return out


def _bbox_corners(model):
    from mathutils import Vector as V
    return np.array([tuple(model.matrix_world @ V(c)) for c in model.bound_box])


def view_film(tree, rays, model, scale):
    """Cara del corte «desde la vista»: la línea dibujada se lleva en línea recta hacia el fondo,
    como un cuchillo, atravesando toda la pieza. Los extremos se alargan hasta salir del modelo."""
    if len(rays) < 2:
        raise common.AddonError('Hacen falta al menos dos puntos: pincha de un lado a otro de la pieza.')
    corners = _bbox_corners(model)
    diag = float(np.linalg.norm(corners.max(0) - corners.min(0)))
    center = corners.mean(0)
    o0, d0 = rays[0]
    persp = all(np.linalg.norm(o - o0) < 1e-6 * max(1.0, diag) for o, _d in rays)
    tc = float((center - o0) @ d0)

    def point(o, d):
        return o + d * float((center - o) @ d)

    def ray_to(o_ref, d_ref, target):
        if persp:
            dd = target - o0
            return o0.copy(), dd / max(np.linalg.norm(dd), 1e-12)
        return o_ref + (target - point(o_ref, d_ref)), d_ref.copy()

    def hits(o, d):
        return tree.ray_cast(Vector(o), Vector(d))[0] is not None

    def extend(rs, at_end):
        (oa, da), (ob, db) = (rs[-2], rs[-1]) if at_end else (rs[1], rs[0])
        pa, pb = point(oa, da), point(ob, db)
        step_dir = pb - pa
        step_dir /= max(np.linalg.norm(step_dir), 1e-12)
        step = diag / 100.0
        extra = []
        target = pb
        for k in range(100):          # hasta que el rayo ya no toque el modelo, y un poco más
            target = target + step_dir * step
            o, d = ray_to(ob, db, target)
            extra.append((o, d))
            if not hits(o, d) and k >= 2:
                break
        for _ in range(3):
            target = target + step_dir * step
            extra.append(ray_to(ob, db, target))
        return rs + extra if at_end else extra[::-1] + rs
    rs = [(np.asarray(o, float), np.asarray(d, float)) for o, d in rays]
    rs = extend(extend(rs, True), False)
    # remuestrear a lo largo de la línea (en la profundidad del centro)
    P = np.array([point(o, d) for o, d in rs])
    seg = np.linalg.norm(np.diff(P, axis=0), axis=1)
    s = np.concatenate([[0], np.cumsum(seg)])
    n = int(np.clip(s[-1] / max(diag / 150.0, 1e-9), 40, 400))
    ts = np.linspace(0, s[-1], n)
    idx = np.clip(np.searchsorted(s, ts, side='right') - 1, 0, len(rs) - 2)
    w = ((ts - s[idx]) / np.maximum(seg[idx], 1e-12))[:, None]
    O = np.array([rs[i][0] for i in idx]) * (1 - w) + np.array([rs[i + 1][0] for i in idx]) * w
    D = np.array([rs[i][1] for i in idx]) * (1 - w) + np.array([rs[i + 1][1] for i in idx]) * w
    D /= np.linalg.norm(D, axis=1, keepdims=True)
    # profundidad: de delante a detrás de toda la caja del modelo
    t_all = np.einsum('kij,ij->ki', corners[:, None, :] - O[None, :, :], D)
    t0 = float(t_all.min()) - diag * 0.05
    t1 = float(t_all.max()) + diag * 0.05
    m = int(np.clip((t1 - t0) / max(diag / 120.0, 1e-9), 20, 160))
    T = np.linspace(t0, t1, m)
    W = O[:, None, :] + D[:, None, :] * T[None, :, None]          # n × m
    verts = W.reshape(-1, 3)
    tris = []
    for i in range(n - 1):
        for j in range(m - 1):
            a, b, c, d = i * m + j, (i + 1) * m + j, (i + 1) * m + j + 1, i * m + j + 1
            tris.append((a, b, c)); tris.append((a, c, d))
    tris = np.array(tris, int)
    fn = np.cross(verts[tris[:, 1]] - verts[tris[:, 0]], verts[tris[:, 2]] - verts[tris[:, 0]])
    normal = fn.sum(0)
    normal /= max(np.linalg.norm(normal), 1e-12)
    return {'verts': verts, 'tris': tris, 'normal': normal, 'center': verts.mean(0),
            'inside': np.ones(len(verts), bool), 'spacing': diag / 150.0,
            'loop': P, 'dense': np.array([point(o, d) for o, d in zip(O, D)]), 'open': True}


def split_by_line(context, model, clicks, curved, kind, radius_mm, length_mm, tolerance_mm, wall_mm,
                  mode='AUTO', unit='AUTO', film=None, shape_name=None):
    """Separa `model` por la línea (corte curvo o recto limitado a la línea) y pone conectores."""
    common.require_solid(context, model)
    unit_code, scale = common.resolve_unit(context.scene, unit, model)
    col = common._collection_of(model, context)
    flat_note = ''
    if kind == 'PIVOT' and curved:
        curved, film = False, None          # para girar, la cara tiene que ser plana
        flat_note = ' (corte recto: para girar la cara tiene que ser plana)'
    bm = common.world_bmesh(context, model)
    try:
        mtree = BVHTree.FromBMesh(bm)
    finally:
        bm.free()
    if film is None:
        film = prepare(mtree, clicks, scale, curved)
    kerf = KERF_MM / scale
    eps = max(.01 / scale, 1e-6 * max(1.0, Vector(film['center']).length))

    # conectores (se calculan sobre el modelo entero, antes de cortar)
    placements, pivot, best = [], None, 0.0
    if kind == 'PIVOT':
        pivot = common.pivot_dims(radius_mm, length_mm, tolerance_mm)
        radius, depth, wall = pivot['hole_r'] / scale, pivot['hole_depth'] / scale, wall_mm / scale
        placements, best = _connector_points(mtree, film, radius, depth, wall, 1, eps)
        if not placements:
            fits = max(0.0, (best - wall) * scale - pivot['lip'] - pivot['c']) * 2
            raise common.AddonError(f'No cabe un eje de giro de Ø{radius_mm * 2:g} mm con {wall_mm:g} mm de pared en este corte '
                                    f'(lo más grueso admite unos Ø{fits:.1f} mm). Usa uno más fino o mueve el corte.')
        n_avg = Vector(film['normal'])
        placements = [(placements[0][0], n_avg)]
    elif kind != 'NONE':
        radius = (radius_mm + tolerance_mm) / scale
        depth = ((length_mm / 2 + tolerance_mm) if kind == 'DOWEL' else (length_mm + tolerance_mm)) / scale
        wall = wall_mm / scale
        placements, best = _connector_points(mtree, film, radius, depth, wall, 1 if mode == 'ONE' else 2, eps)
        if not placements:
            fits = max(0.0, (best - wall) * scale - tolerance_mm) * 2
            what = (f'ninguna espiga de Ø{radius_mm * 2:g} mm' if kind == 'DOWEL'
                    else f'ningún imán de Ø{radius_mm * 2:g} × {length_mm:g} mm')
            raise common.AddonError(f'No cabe {what} con {wall_mm:g} mm de pared en este corte '
                                    f'(lo más grueso admite unos Ø{fits:.1f} mm). Usa uno más pequeño o mueve el corte.')
        if mode == 'TWO' and len(placements) < 2:
            raise common.AddonError('No caben dos alojamientos en este corte. Elige «Automático» para poner uno.')

    created = []
    ftree = film_tree(film)
    try:
        big = None
        if kind == 'PIVOT':
            # hay que saber antes qué lado es la pieza pequeña (la que gira): primera pasada solo
            # para medir los dos lados
            probe = _work_copy(context, model, col); created.append(probe)
            slab = _slab_object(film, kerf, col); created.append(slab)
            bm, sides, _touched = _separate(context, probe, slab, ftree, kerf)
            big = _bigger(sides)
            bm.free()
            for o in (slab, probe):
                created.remove(o)
            common.remove_objects([slab, probe])

        # 1) copia del modelo con los conectores hechos en la pieza entera (antes de partirla:
        #    es mucho más fiable que hacer booleanas sobre las piezas ya cortadas)
        work = _work_copy(context, model, col); created.append(work)
        slab_hole = None
        if kind in {'MAGNET', 'DOWEL'}:
            for point, normal in placements:
                cutter = common.cylinder('Cortador_temporal', point, normal, radius, depth * 2, col)
                created.append(cutter)
                common.boolean(context, work, cutter)
                created.remove(cutter); common.remove_objects([cutter])
        elif kind == 'PIVOT':
            point, normal = placements[0]
            normal = normal * (-big)            # de la pieza grande (_01) hacia la pequeña (_02)
            peg, cut, slot = common.pivot_objects(point, normal, pivot, scale, col)
            temp = [o for o in (peg, cut, slot) if o is not None]
            created += temp
            if slot is not None:
                common.boolean(context, peg, slot)
            common.boolean(context, work, cut)          # agujero en el lado de la pieza pequeña
            common.boolean(context, work, peg, 'UNION')  # eje pegado al lado grande, suelto en el agujero
            for o in temp:
                created.remove(o)
            common.remove_objects(temp)
            # la lámina no debe cortar el eje: lleva un agujero algo mayor que él (cae en la holgura)
            slab_hole = (point, normal, (pivot['r'] + pivot['c'] / 2) / scale)

        # 2) partir con la lámina y repartir los trozos a cada lado
        slab = _slab_object(film, kerf, col, slab_hole); created.append(slab)
        bm, sides, touched = _separate(context, work, slab, ftree, kerf)
        created.remove(slab); common.remove_objects([slab])
        if not touched[1] or not touched[-1]:
            bm.free()
            raise common.AddonError('La línea no separa la pieza: rodéala del todo, pinchando por toda la vuelta.')
        big = _bigger(sides) if big is None else big
        outputs = []
        for s, suffix in ((big, '_01'), (-big, '_02')):
            keep = {f.index for p in sides[s] for f in p}
            nb = bm.copy()
            nb.faces.index_update()
            nb.faces.ensure_lookup_table()
            bmesh.ops.delete(nb, geom=[f for f in nb.faces if f.index not in keep], context='FACES')
            bmesh.ops.recalc_face_normals(nb, faces=nb.faces[:])
            if any(not e.is_manifold for e in nb.edges):
                nb.free()
                bm.free()
                raise common.AddonError('El corte dejó una pieza abierta. Mueve un poco la línea y vuelve a probar.')
            obj = common.new_object(nb, model.name + suffix, col, model)
            nb.free()
            created.append(obj)
            outputs.append(obj)
        bm.free()
        created.remove(work); common.remove_objects([work])
        if kind == 'DOWEL':
            lo, hi = common._model_box(model)
            r = radius_mm / scale
            for i in range(len(placements)):
                dowel = common.cylinder(model.name + '_Espiga', (hi.x + r * 4, lo.y + i * r * 4, r), (0, 1, 0), r,
                                        length_mm / scale, col)
                created.append(dowel); outputs.append(dowel)
        if unit_code != 'SCENE':
            for o in outputs:
                o[common.UNIT_PROP] = unit_code
        common._finish(context, model, outputs)
    except Exception:
        common.remove_objects(created)
        raise
    loose = sum(len(sides[s]) for s in (1, -1)) - 2
    tail = f' Hay {loose} trozo{"s" if loose > 1 else ""} suelto{"s" if loose > 1 else ""} dentro de las piezas.' if loose > 0 else ''
    shape = shape_name or ('curvo' if curved else 'recto')
    if kind == 'NONE':
        return f'Separado en 2 piezas (corte {shape}) sin conectores. Original conservado y oculto.' + tail
    if kind == 'PIVOT':
        extra = ' a presión' if pivot['snap'] else ' (a fricción: eje pequeño)'
        return f'Separado con eje de giro Ø{radius_mm * 2:g} mm{extra}{flat_note}: la pieza pequeña gira. Original conservado y oculto.' + tail
    name = 'imán(es)' if kind == 'MAGNET' else 'espiga(s)'
    return f'Separado (corte {shape}): {len(placements)} {name} por cara. Original conservado y oculto.' + tail
