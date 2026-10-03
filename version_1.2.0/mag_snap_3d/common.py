"""Núcleo común 1.2.0 de los complementos del taller (Blender 4.2 a 5.x).

Regla de la casa: TODO se ejecuta en modo Objeto.
- Nunca se entra ni se sale de modo Edición por código.
- Las piezas se eligen con objetos ayudantes que se mueven en modo Objeto:
  un «plano de corte» para separar y un «cortador» (cilindro, caja, esfera o
  cualquier malla cerrada) para sacar insertos.
- Si el usuario ya tenía caras marcadas de una sesión de Edición, también se
  pueden usar: se leen de la malla sin cambiar de modo.
- El original nunca se modifica: se oculta y se trabaja en copias.
- Booleanas sin bpy.ops (modificador evaluado → malla nueva): no dependen del
  contexto ni del objeto activo.
Todas las distancias públicas van en milímetros.
"""
import math
import re
import struct
from pathlib import Path

import bmesh
import bpy
import numpy as np
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree

ROLE = 'taller_role'
ROLE_PLANE = 'plano_corte'
ROLE_CUTTER = 'cortador'
TARGET = 'taller_modelo'
SHAPE = 'taller_forma'


class AddonError(ValueError):
    pass


# --------------------------------------------------------------------------- modo Objeto
def in_object_mode(context):
    return context.mode == 'OBJECT'


def poll_object_mode(cls, context):
    if context.mode != 'OBJECT':
        cls.poll_message_set('Pasa a modo Objeto (Tab) para usar este botón.')
        return False
    return True


def draw_mode_warning(layout, context):
    """Devuelve True si hay que avisar (y dibuja el aviso con botón para volver)."""
    if context.mode == 'OBJECT':
        return False
    box = layout.box()
    box.alert = True
    box.label(text='Estos botones trabajan en modo Objeto', icon='ERROR')
    box.operator('object.mode_set', text='Volver a modo Objeto', icon='OBJECT_DATAMODE').mode = 'OBJECT'
    return True


def is_helper(obj):
    return obj is not None and obj.get(ROLE) in (ROLE_PLANE, ROLE_CUTTER)


# --------------------------------------------------------------------------- unidades y nombres
def factor(scene, unit='SCENE'):
    """Milímetros por unidad de Blender."""
    return {'MM': 1.0, 'M': 1000.0}.get(unit, scene.unit_settings.scale_length * 1000.0)


def safe_name(name):
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', str(name)).strip(' .')[:100] or 'Pieza'
    if re.match(r'^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)', name, re.I):
        name = '_' + name
    return name


def unique_name(name, used):
    base = safe_name(name)
    candidate = base
    i = 2
    while candidate.casefold() in used:
        candidate = f'{base}_{i:03d}'
        i += 1
    used.add(candidate.casefold())
    return candidate


# --------------------------------------------------------------------------- exportación STL
def _world_triangles(obj, graph, scale):
    """Triángulos de la malla evaluada en mm, vectorizado. Devuelve (vértices n×3×3, normales, material)."""
    evaluated = obj.evaluated_get(graph)
    me = evaluated.to_mesh()
    try:
        me.calc_loop_triangles()
        n = len(me.loop_triangles)
        if not n:
            return np.zeros((0, 3, 3)), np.zeros((0, 3)), np.zeros(0, int)
        tri = np.empty(n * 3, np.int32)
        me.loop_triangles.foreach_get('vertices', tri)
        mats = np.empty(n, np.int32)
        me.loop_triangles.foreach_get('material_index', mats)
        co = np.empty(len(me.vertices) * 3, np.float64)
        me.vertices.foreach_get('co', co)
    finally:
        evaluated.to_mesh_clear()
    m = np.array(obj.matrix_world, dtype=np.float64)
    co = (co.reshape(-1, 3) @ m[:3, :3].T + m[:3, 3]) * scale
    tri = tri.reshape(-1, 3)
    if np.linalg.det(m[:3, :3]) < 0:
        tri = tri[:, [0, 2, 1]]
    v = co[tri]
    normal = np.cross(v[:, 1] - v[:, 0], v[:, 2] - v[:, 0])
    length = np.linalg.norm(normal, axis=1)
    ok = length > 1e-12
    return v[ok], normal[ok] / length[ok, None], mats[ok]


def _write_stl(target, v, normal):
    record = np.zeros(len(v), dtype=[('n', '<f4', (3,)), ('v', '<f4', (3, 3)), ('a', '<u2')])
    record['n'] = normal
    record['v'] = v
    with target.open('xb') as handle:  # nunca sobrescribe
        handle.write(b'Blender - coordenadas en milimetros'.ljust(80, b'\0'))
        handle.write(struct.pack('<I', len(v)))
        handle.write(record.tobytes())


def _material_name(obj, index):
    slots = obj.material_slots
    mat = slots[index].material if 0 <= index < len(slots) else None
    return mat.name if mat else 'Sin_Color'


def export_meshes(context, path, scope='SELECTED', unit='SCENE', by_color=False):
    """Exporta un STL binario en mm por objeto. Con by_color, una carpeta por color y,
    si un objeto tiene varios materiales, cada material sale en su carpeta."""
    if not path.strip():
        raise AddonError('Selecciona una carpeta de salida.')
    if path.startswith('//') and not bpy.data.filepath:
        raise AddonError('Guarda el .blend o elige una carpeta absoluta de salida.')
    if context.mode != 'OBJECT':
        raise AddonError('Exporta desde el modo Objeto.')
    candidates = context.selected_objects if scope == 'SELECTED' else context.visible_objects
    objects = sorted((o for o in candidates if o.type == 'MESH' and not is_helper(o)), key=lambda o: o.name)
    if not objects:
        raise AddonError('No hay mallas seleccionadas/visibles para exportar.')
    dest = Path(bpy.path.abspath(path)).resolve()
    if dest.exists() and not dest.is_dir():
        raise AddonError('La ruta de salida no es una carpeta.')
    scale = factor(context.scene, unit)
    graph = context.evaluated_depsgraph_get()
    color_dirs, used_dirs, planned = {}, set(), []
    for obj in objects:  # primero se calcula todo; si algo falla no queda nada a medias
        v, normal, mats = _world_triangles(obj, graph, scale)
        if not len(v):
            raise AddonError(f'{obj.name}: la malla no tiene triángulos válidos.')
        if not by_color:
            planned.append((dest, obj.name, v, normal))
            continue
        groups = {}
        for index in np.unique(mats):
            groups.setdefault(_material_name(obj, int(index)), []).append(mats == index)
        for color, masks in groups.items():
            keep = np.logical_or.reduce(masks)
            if color not in color_dirs:
                color_dirs[color] = unique_name(color, used_dirs)
            planned.append((dest / color_dirs[color], obj.name, v[keep], normal[keep]))
    created = []
    try:
        for folder, name, v, normal in planned:
            folder.mkdir(parents=True, exist_ok=True)
            used = {p.stem.casefold() for p in folder.iterdir()}
            target = folder / (unique_name(name, used) + '.stl')
            _write_stl(target, v, normal)
            created.append(target)
    except Exception:
        for file in created:
            if file.is_file():
                file.unlink()
        raise
    return created


# --------------------------------------------------------------------------- mallas auxiliares
def new_object(bm, name, collection, source=None):
    data = bpy.data.meshes.new(name)
    bm.to_mesh(data)
    data.update()
    obj = bpy.data.objects.new(name, data)
    collection.objects.link(obj)
    if source is not None:
        for slot in source.material_slots:
            data.materials.append(slot.material)
    return obj


def remove_objects(objects):
    for obj in reversed(list(objects)):
        if obj is not None and obj.name in bpy.data.objects:
            data = obj.data
            bpy.data.objects.remove(obj, do_unlink=True)
            if data is not None and data.users == 0:
                bpy.data.meshes.remove(data)


def world_bmesh(context, obj):
    """bmesh de la malla evaluada (con modificadores) en coordenadas de mundo."""
    graph = context.evaluated_depsgraph_get()
    evaluated = obj.evaluated_get(graph)
    me = evaluated.to_mesh()
    try:
        bm = bmesh.new()
        bm.from_mesh(me)
    finally:
        evaluated.to_mesh_clear()
    bm.transform(obj.matrix_world)
    if obj.matrix_world.determinant() < 0:
        bmesh.ops.reverse_faces(bm, faces=bm.faces[:])
    return bm


def solid_info(obj):
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    try:
        closed = bool(bm.faces) and all(e.is_manifold for e in bm.edges)
        volume = abs(bm.calc_volume(signed=True)) if closed else 0.0
        return closed, volume
    finally:
        bm.free()


def require_solid(context, obj):
    bm = world_bmesh(context, obj)
    try:
        if not bm.faces or any(not e.is_manifold for e in bm.edges):
            raise AddonError(f'{obj.name}: la malla debe estar cerrada (manifold). Repárala antes, por ejemplo en 3D LAB.')
    finally:
        bm.free()


def _solvers():
    return set(bpy.types.BooleanModifier.bl_rna.properties['solver'].enum_items.keys())


def boolean(context, obj, cutter, operation='DIFFERENCE'):
    """Aplica una booleana sin bpy.ops: se evalúa el modificador y se copia el resultado.
    Usa el solver «Manifold» (rápido) si esta versión de Blender lo tiene; si falla, «Exacto»."""
    before = solid_info(obj)[1]
    solvers = [s for s in ('MANIFOLD', 'EXACT') if s in _solvers()]
    last = None
    for solver in solvers:
        mod = obj.modifiers.new('Taller_booleana', 'BOOLEAN')
        mod.operation = operation
        mod.solver = solver
        mod.object = cutter
        try:
            context.view_layer.update()
            graph = context.evaluated_depsgraph_get()
            new = bpy.data.meshes.new_from_object(obj.evaluated_get(graph), preserve_all_data_layers=True, depsgraph=graph)
        finally:
            obj.modifiers.remove(mod)
        old = obj.data
        obj.data = new
        closed, after = solid_info(obj)
        valid = closed and after > 0 and (after < before - max(before * 1e-9, 1e-15) if operation == 'DIFFERENCE' else True)
        if valid:
            new.name = old.name
            if old.users == 0:
                bpy.data.meshes.remove(old)
            return
        obj.data = old
        bpy.data.meshes.remove(new)
        last = solver
    raise AddonError(f'La booleana no dio un sólido cerrado (solver {last}). El original se conserva.')


# --------------------------------------------------------------------------- primitivas
def cylinder_bmesh(center, axis, radius, height, segments=64):
    bm = bmesh.new()
    q = Vector(axis).normalized().to_track_quat('Z', 'Y')
    m = Matrix.Translation(Vector(center)) @ q.to_matrix().to_4x4()
    bmesh.ops.create_cone(bm, cap_ends=True, cap_tris=False, segments=segments,
                          radius1=radius, radius2=radius, depth=height, matrix=m)
    return bm


def cylinder(name, center, axis, radius, height, collection):
    bm = cylinder_bmesh(center, axis, radius, height)
    try:
        return new_object(bm, name, collection)
    finally:
        bm.free()


def primitive_bmesh(shape, size):
    """Primitiva centrada en el origen; size = (x, y, z) en unidades de Blender."""
    bm = bmesh.new()
    sx, sy, sz = size
    if shape == 'BOX':
        bmesh.ops.create_cube(bm, size=1.0)
        bmesh.ops.scale(bm, vec=(sx, sy, sz), verts=bm.verts[:])
    elif shape == 'SPHERE':
        bmesh.ops.create_uvsphere(bm, u_segments=48, v_segments=24, radius=.5)
        bmesh.ops.scale(bm, vec=(sx, sy, sz), verts=bm.verts[:])
    else:
        bmesh.ops.create_cone(bm, cap_ends=True, segments=64, radius1=.5, radius2=.5, depth=1.0)
        bmesh.ops.scale(bm, vec=(sx, sy, sz), verts=bm.verts[:])
    return bm


# --------------------------------------------------------------------------- ayudantes en escena
def _collection_of(obj, context):
    return obj.users_collection[0] if obj.users_collection else context.scene.collection


def pick_model(context):
    """El modelo con el que trabajar: la malla activa o seleccionada que no sea un ayudante;
    si sólo hay un ayudante seleccionado, el modelo que tiene apuntado."""
    active = context.active_object
    candidates = [active] + list(context.selected_objects)
    for obj in candidates:
        if obj is not None and obj.type == 'MESH' and not is_helper(obj):
            return obj
    for obj in candidates:
        if is_helper(obj):
            target = bpy.data.objects.get(obj.get(TARGET, ''))
            if target is not None and target.type == 'MESH':
                return target
    raise AddonError('Selecciona el modelo (una malla) en modo Objeto.')


def find_helper(context, role, model):
    """Ayudante a usar: el seleccionado; si no, el único de la escena para ese modelo (o el único)."""
    selected = [o for o in context.selected_objects if o.get(ROLE) == role]
    if len(selected) == 1:
        return selected[0]
    if len(selected) > 1:
        raise AddonError('Hay varios ayudantes seleccionados: deja sólo uno.')
    everyone = [o for o in context.scene.objects if o.get(ROLE) == role]
    mine = [o for o in everyone if o.get(TARGET) == model.name]
    for group in (mine, everyone):
        if len(group) == 1:
            return group[0]
        if len(group) > 1:
            raise AddonError('Hay varios ayudantes en la escena: selecciona el que quieres usar.')
    return None


def _model_box(model):
    corners = [model.matrix_world @ Vector(c) for c in model.bound_box]
    lo = Vector([min(c[i] for c in corners) for i in range(3)])
    hi = Vector([max(c[i] for c in corners) for i in range(3)])
    return lo, hi


def add_cut_plane(context, model, axis='Z'):
    """Plano guía (malla de 4 vértices, alambre) en el centro del modelo. Se mueve y gira libremente."""
    lo, hi = _model_box(model)
    center = (lo + hi) / 2
    size = max((hi - lo).length * .6, 1e-4)
    bm = bmesh.new()
    try:
        for x, y in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
            bm.verts.new((x * .5, y * .5, 0))
        bm.faces.new(bm.verts[:])
        obj = new_object(bm, 'Plano_corte', _collection_of(model, context))
    finally:
        bm.free()
    obj.scale = (size, size, size)
    obj.location = center
    obj.rotation_euler = {'X': (0, math.pi / 2, 0), 'Y': (math.pi / 2, 0, 0)}.get(axis, (0, 0, 0))
    obj.display_type = 'WIRE'
    obj.show_in_front = True
    obj.hide_render = True
    obj[ROLE] = ROLE_PLANE
    obj[TARGET] = model.name
    _select_only(context, obj)
    return obj


def plane_frame(plane):
    m = plane.matrix_world
    return m.translation.copy(), (m.to_3x3() @ Vector((0, 0, 1))).normalized()


def add_cutter(context, model, shape='CYLINDER', size_mm=(10, 10, 6), unit='SCENE'):
    """Cortador para insertos: se coloca sobre la zona (ojo, logo...) hundido lo que se quiera de profundidad."""
    scale = factor(context.scene, unit)
    size = tuple(s / scale for s in size_mm)
    lo, hi = _model_box(model)
    bm = primitive_bmesh(shape, size)
    try:
        obj = new_object(bm, 'Cortador', _collection_of(model, context))
    finally:
        bm.free()
    obj.location = ((lo.x + hi.x) / 2, lo.y, (lo.z + hi.z) / 2)   # delante del modelo, a la altura media
    obj.display_type = 'WIRE'
    obj.show_in_front = True
    obj.hide_render = True
    obj[ROLE] = ROLE_CUTTER
    obj[TARGET] = model.name
    obj[SHAPE] = shape
    obj['taller_tam'] = list(size)
    _select_only(context, obj)
    return obj


def _select_only(context, obj):
    for o in context.selected_objects:
        o.select_set(False)
    obj.select_set(True)
    context.view_layer.objects.active = obj


# --------------------------------------------------------------------------- geometría 2D del corte
def _plane_axes(normal):
    u = normal.orthogonal().normalized()
    return u, normal.cross(u).normalized()


def _segments(loops_2d):
    a = np.concatenate([lp for lp in loops_2d])
    b = np.concatenate([np.roll(lp, -1, axis=0) for lp in loops_2d])
    return a, b


def _inside(points, a, b):
    """Par-impar respecto a todos los contornos (admite islas y huecos)."""
    x, y = points[:, 0:1], points[:, 1:2]
    ax, ay, bx, by = a[:, 0], a[:, 1], b[:, 0], b[:, 1]
    crosses = (ay > y) != (by > y)
    with np.errstate(divide='ignore', invalid='ignore'):
        xint = (bx - ax) * (y - ay) / (by - ay) + ax
    return (np.count_nonzero(crosses & (x < xint), axis=1) % 2) == 1


def _clearance(points, a, b):
    """Distancia de cada punto al contorno más cercano (negativa si está fuera)."""
    out = np.empty(len(points))
    d = b - a
    dd = np.maximum((d ** 2).sum(1), 1e-30)
    for start in range(0, len(points), 256):
        p = points[start:start + 256, None, :]
        t = np.clip(((p - a) * d).sum(2) / dd, 0, 1)
        dist = np.sqrt((((a + t[..., None] * d) - p) ** 2).sum(2)).min(1)
        out[start:start + 256] = dist
    inside = _inside(points, a, b)
    return np.where(inside, out, -out)


def connector_points(loops_2d, radius, wall, count):
    """Mejor posición (una o dos) para alojamientos dentro de la sección, con pared mínima."""
    a, b = _segments(loops_2d)
    lo, hi = a.min(0), a.max(0)
    gx, gy = np.meshgrid(np.linspace(lo[0], hi[0], 41)[1:-1], np.linspace(lo[1], hi[1], 41)[1:-1])
    pts = np.column_stack([gx.ravel(), gy.ravel()])
    clear = _clearance(pts, a, b)
    ok = clear >= radius + wall
    if not ok.any():
        raise AddonError('No cabe el alojamiento con la pared mínima indicada.')
    pts, clear = pts[ok], clear[ok]
    if count == 1:
        return [tuple(pts[int(np.argmax(clear))])]
    step = max(1, len(pts) // 300)
    sub = pts[::step]
    dist = np.linalg.norm(sub[:, None] - sub[None], axis=2)
    i, j = np.unravel_index(int(np.argmax(dist)), dist.shape)
    if dist[i, j] < 2 * radius + wall:
        raise AddonError('No caben dos alojamientos con la separación y pared mínimas indicadas.')
    return [tuple(sub[i]), tuple(sub[j])]


# --------------------------------------------------------------------------- separar por plano
def _cap(bm, normal):
    """Tapa las aberturas del corte. triangle_fill admite secciones con huecos (piezas vaciadas)."""
    edges = [e for e in bm.edges if e.is_boundary]
    if not edges:
        return []
    faces = [g for g in bmesh.ops.triangle_fill(bm, use_beauty=True, use_dissolve=False, edges=edges, normal=normal)['geom']
             if isinstance(g, bmesh.types.BMFace)]
    rest = [e for e in bm.edges if e.is_boundary]
    if rest:
        raise AddonError('No se pudo cerrar la cara del corte (contorno abierto o cruzado).')
    return faces


def _half(context, source, co, normal, keep_positive, name, collection):
    bm = world_bmesh(context, source)
    try:
        bmesh.ops.bisect_plane(bm, geom=bm.verts[:] + bm.edges[:] + bm.faces[:], dist=1e-7,
                               plane_co=co, plane_no=normal, clear_outer=keep_positive is False, clear_inner=keep_positive)
        if not bm.faces:
            raise AddonError('El plano no corta el modelo: muévelo para que lo atraviese.')
        cap_normal = -normal if keep_positive else normal     # la tapa mira hacia fuera de cada mitad
        cap = _cap(bm, cap_normal)
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
        if not cap:
            raise AddonError('El plano no corta el modelo: muévelo para que lo atraviese.')
        return new_object(bm, name, collection, source)
    finally:
        bm.free()


def _section_loops(context, source, co, normal):
    """Contornos de la sección del modelo por el plano, en 2D (u, v)."""
    bm = world_bmesh(context, source)
    try:
        cut = bmesh.ops.bisect_plane(bm, geom=bm.verts[:] + bm.edges[:] + bm.faces[:], dist=1e-7,
                                     plane_co=co, plane_no=normal)['geom_cut']
        edges = [e for e in cut if isinstance(e, bmesh.types.BMEdge)]
        u, v = _plane_axes(normal)
        adjacent = {}
        for e in edges:
            for vert in e.verts:
                adjacent.setdefault(vert, []).append(e)
        seen, loops = set(), []
        for e in edges:
            if e in seen:
                continue
            start = e.verts[0]
            current, last, ring = start, None, []
            while True:
                ring.append(current.co.copy())
                nxt = next((x for x in adjacent.get(current, []) if x is not last and x not in seen), None)
                if nxt is None:
                    break
                seen.add(nxt)
                current, last = nxt.other_vert(current), nxt
                if current is start:
                    break
            if len(ring) >= 3:
                loops.append(np.array([((p - co).dot(u), (p - co).dot(v)) for p in ring]))
        if not loops:
            raise AddonError('El plano no corta el modelo: muévelo para que lo atraviese.')
        return loops, u, v
    finally:
        bm.free()


def depth_check(obj, point, direction, radius, depth, wall, mm_factor):
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    try:
        tree = BVHTree.FromBMesh(bm)
        q = direction.to_track_quat('Z', 'Y')
        eps = .001 / mm_factor
        offsets = [Vector()] + [q @ Vector((radius * math.cos(i * math.pi / 4), radius * math.sin(i * math.pi / 4), 0)) for i in range(8)]
        for off in offsets:
            loc, _n, _i, distance = tree.ray_cast(point + off + direction * eps, direction)
            if loc is None or distance + eps < depth + wall:
                raise AddonError('La pieza no tiene espesor suficiente para el alojamiento y la pared mínima.')
    finally:
        bm.free()


def _finish(context, source, outputs, helpers=()):
    source.hide_set(True)
    source.hide_render = True
    source['taller_original_conservado'] = True
    for helper in helpers:
        if helper is not None and helper.name in bpy.data.objects:
            helper.hide_set(True)
    for o in context.selected_objects:
        o.select_set(False)
    for o in outputs:
        o['taller_origen'] = source.name
        o.select_set(True)
    context.view_layer.objects.active = outputs[0]


def split_with_plane(context, kind, radius_mm, length_mm, tolerance_mm, wall_mm, mode='ONE', unit='SCENE'):
    """Separa el modelo por el plano de corte y abre alojamientos enfrentados en las dos caras.
    kind: 'MAGNET' (alojamiento de imán en cada cara), 'DOWEL' (agujeros + espiga suelta) o 'NONE'."""
    model = pick_model(context)
    plane = find_helper(context, ROLE_PLANE, model)
    if plane is None:
        raise AddonError('Añade primero un plano de corte y colócalo donde quieras separar.')
    require_solid(context, model)
    scale = factor(context.scene, unit)
    co, normal = plane_frame(plane)
    col = _collection_of(model, context)
    created = []
    try:
        base = _half(context, model, co, normal, False, model.name + '_Base', col); created.append(base)
        piece = _half(context, model, co, normal, True, model.name + '_Pieza', col); created.append(piece)
        count = 0
        if kind != 'NONE':
            radius = (radius_mm + tolerance_mm) / scale
            depth = ((length_mm / 2 + tolerance_mm) if kind == 'DOWEL' else (length_mm + tolerance_mm)) / scale
            loops, u, v = _section_loops(context, model, co, normal)
            want = 2 if mode in {'TWO', 'AUTO'} and kind == 'MAGNET' else 1
            try:
                points = connector_points(loops, radius, wall_mm / scale, want)
            except AddonError:
                if mode != 'AUTO':
                    raise
                points = connector_points(loops, radius, wall_mm / scale, 1)
            for x, y in points:
                point = co + u * x + v * y
                depth_check(base, point, -normal, radius, depth, wall_mm / scale, scale)
                depth_check(piece, point, normal, radius, depth, wall_mm / scale, scale)
                cutter = cylinder('Cortador_temporal', point, normal, radius, depth * 2, col); created.append(cutter)
                boolean(context, base, cutter)
                boolean(context, piece, cutter)
                created.remove(cutter); remove_objects([cutter])
            count = len(points)
        outputs = [base, piece]
        if kind == 'DOWEL':
            lo, hi = _model_box(model)
            r = radius_mm / scale
            for i in range(count):
                dowel = cylinder(model.name + '_Espiga', (hi.x + r * 4, lo.y + i * r * 4, r), (0, 1, 0), r, length_mm / scale, col)
                created.append(dowel); outputs.append(dowel)
        _finish(context, model, outputs, [plane])
        return count
    except Exception:
        remove_objects(created)
        raise


# --------------------------------------------------------------------------- caras marcadas (sin modo Edición)
def marked_mask(obj):
    """Caras marcadas en la última sesión de Edición, leídas de la malla en modo Objeto."""
    if obj.type != 'MESH':
        raise AddonError('El objeto activo no es una malla.')
    if any(m.show_viewport for m in obj.modifiers):
        raise AddonError('La malla tiene modificadores activos: aplícalos en una copia antes de usar caras marcadas.')
    mask = np.zeros(len(obj.data.polygons), bool)
    obj.data.polygons.foreach_get('select', mask)
    if not mask.any() or mask.all():
        raise AddonError('No hay caras marcadas (o están todas). Usa mejor el plano de corte o el cortador.')
    return mask


def _mesh_bmesh(obj):
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bm.transform(obj.matrix_world)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    bm.faces.ensure_lookup_table()
    return bm


def split_marked(context, kind, radius_mm, length_mm, tolerance_mm, wall_mm, mode='ONE', unit='SCENE'):
    """Como 1.1 pero en modo Objeto: separa las caras marcadas por su borde (que debe ser plano)."""
    model = pick_model(context)
    require_solid(context, model)
    mask = marked_mask(model)
    bm = _mesh_bmesh(model)
    try:
        selected = [f for f in bm.faces if mask[f.index]]
        chosen = set(selected)
        edges = [e for e in bm.edges if sum(f in chosen for f in e.link_faces) == 1]
        pts = [v.co.copy() for e in edges for v in e.verts]
    finally:
        bm.free()
    if not pts:
        raise AddonError('No se ha encontrado el borde de las caras marcadas.')
    center = sum(pts, Vector()) / len(pts)
    arr = np.array([tuple(p - center) for p in pts])
    normal = Vector(np.linalg.svd(arr, full_matrices=False)[2][-1])
    scale = factor(context.scene, unit)
    if np.abs(arr @ np.array(normal)).max() * scale > .02:
        raise AddonError('El borde de las caras marcadas no es plano (> 0,02 mm). Usa el plano de corte.')
    # Orientar la normal hacia las caras marcadas y reutilizar el corte por plano.
    marked_center = sum((model.matrix_world @ model.data.polygons[i].center for i in np.nonzero(mask)[0][:500]), Vector()) / min(500, int(mask.sum()))
    if (marked_center - center).dot(normal) < 0:
        normal = -normal
    col = _collection_of(model, context)
    temp = add_cut_plane(context, model)
    temp.matrix_world = Matrix.Translation(center) @ normal.to_track_quat('Z', 'Y').to_matrix().to_4x4()
    try:
        _select_only(context, temp)
        model.select_set(True)
        return split_with_plane(context, kind, radius_mm, length_mm, tolerance_mm, wall_mm, mode, unit)
    except AddonError as exc:
        if 'no corta' in str(exc):
            raise AddonError('Las caras marcadas no encierran volumen: marca toda la parte que quieres separar, '
                             'no sólo una cara plana (para eso usa un inserto).') from None
        raise
    finally:
        remove_objects([temp])


# --------------------------------------------------------------------------- insertos
def _grown_cutter(context, cutter, tolerance):
    """Copia del cortador agrandada `tolerance` (unidades de Blender) hacia fuera."""
    col = _collection_of(cutter, context)
    shape = cutter.get(SHAPE)
    if shape and 'taller_tam' in cutter:
        m = cutter.matrix_world
        loc, rot, sca = m.decompose()
        size = [abs(s) * k + 2 * tolerance for s, k in zip(cutter['taller_tam'], sca)]
        bm = primitive_bmesh(shape, size)
        bm.transform(Matrix.Translation(loc) @ rot.to_matrix().to_4x4())
    else:
        bm = world_bmesh(context, cutter)
        bm.normal_update()
        for v in bm.verts:
            v.co += v.normal * tolerance
    try:
        return new_object(bm, 'Cortador_holgura', col)
    finally:
        bm.free()


def _world_copy(context, obj, name, collection):
    bm = world_bmesh(context, obj)
    try:
        return new_object(bm, name, collection, obj)
    finally:
        bm.free()


def inlay_from_cutter(context, tolerance_mm, unit='SCENE'):
    """Inserto = modelo ∩ cortador. Base = modelo − cortador agrandado por la holgura."""
    model = pick_model(context)
    cutter = find_helper(context, ROLE_CUTTER, model)
    if cutter is None:
        raise AddonError('Añade primero un cortador y húndelo en la zona que quieres sacar.')
    require_solid(context, model)
    require_solid(context, cutter)
    scale = factor(context.scene, unit)
    col = _collection_of(model, context)
    created = []
    try:
        cutter_world = _world_copy(context, cutter, 'Cortador_mundo', col); created.append(cutter_world)
        insert = _world_copy(context, model, model.name + '_Inserto', col); created.append(insert)
        boolean(context, insert, cutter_world, 'INTERSECT')
        if solid_info(insert)[1] <= 0:
            raise AddonError('El cortador no toca el modelo: colócalo sobre la zona.')
        base = _world_copy(context, model, model.name + '_Base', col); created.append(base)
        grown = _grown_cutter(context, cutter, tolerance_mm / scale); created.append(grown)
        boolean(context, base, grown)
        for tmp in (cutter_world, grown):
            created.remove(tmp)
        remove_objects([cutter_world, grown])
        _finish(context, model, [base, insert], [cutter])
        return base, insert
    except Exception:
        remove_objects(created)
        raise


def inlay_marked(context, depth_mm, tolerance_mm, wall_mm, unit='SCENE'):
    """Inserto a partir de caras marcadas (modo Objeto): el parche se engrosa hacia dentro."""
    model = pick_model(context)
    require_solid(context, model)
    mask = marked_mask(model)
    scale = factor(context.scene, unit)
    col = _collection_of(model, context)
    created = []
    try:
        whole = _mesh_bmesh(model)
        try:
            tree = BVHTree.FromBMesh(whole)
            eps = .001 / scale
            for f in whole.faces:
                if mask[f.index]:
                    loc, _n, _i, distance = tree.ray_cast(f.calc_center_median() - f.normal * eps, -f.normal)
                    if loc is None or distance < (depth_mm + tolerance_mm + wall_mm) / scale:
                        raise AddonError('El inserto atravesaría la pieza. Reduce la profundidad.')
            base = new_object(whole, model.name + '_Base', col, model); created.append(base)
        finally:
            whole.free()
        patch = _mesh_bmesh(model)
        try:
            bmesh.ops.delete(patch, geom=[f for f in patch.faces if not mask[f.index]], context='FACES')
            insert = new_object(patch, model.name + '_Inserto', col, model); created.append(insert)
        finally:
            patch.free()
        # Engrosar hacia dentro con bmesh (sin modificadores ni bpy.ops).
        bm = bmesh.new()
        bm.from_mesh(insert.data)
        try:
            bmesh.ops.solidify(bm, geom=bm.faces[:], thickness=-depth_mm / scale)
            bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
            bm.to_mesh(insert.data)
        finally:
            bm.free()
        if not solid_info(insert)[0]:
            raise AddonError('El parche no admite un grosor cerrado válido.')
        grown = insert.copy()
        grown.data = insert.data.copy()
        col.objects.link(grown)
        created.append(grown)
        bm = bmesh.new()
        bm.from_mesh(grown.data)
        try:
            bm.normal_update()
            for v in bm.verts:
                v.co += v.normal * (tolerance_mm / scale)
            bm.to_mesh(grown.data)
        finally:
            bm.free()
        boolean(context, base, grown)
        created.remove(grown)
        remove_objects([grown])
        _finish(context, model, [base, insert])
        return base, insert
    except Exception:
        remove_objects(created)
        raise


# --------------------------------------------------------------------------- registro
def register_classes(classes, prop, settings):
    for cls in classes:
        bpy.utils.register_class(cls)
    setattr(bpy.types.Scene, prop, bpy.props.PointerProperty(type=settings))


def unregister_classes(classes, prop):
    if hasattr(bpy.types.Scene, prop):
        delattr(bpy.types.Scene, prop)
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)


UNIT_ITEMS = [('SCENE', 'Escala de la escena', 'Respeta los metros por unidad de la escena'),
              ('MM', '1 unidad = 1 mm', 'Para STL importados con coordenadas numéricas en milímetros'),
              ('M', '1 unidad = 1 m', 'Coordenadas expresadas en metros')]
SCOPE_ITEMS = [('SELECTED', 'Seleccionadas', 'Solo las mallas seleccionadas'),
               ('VISIBLE', 'Visibles', 'Todas las mallas visibles de la vista actual')]
SHAPE_ITEMS = [('CYLINDER', 'Cilindro', 'Ojos, botones, remaches'),
               ('BOX', 'Caja', 'Placas, logos rectangulares'),
               ('SPHERE', 'Esfera', 'Zonas redondeadas')]
REGION_ITEMS = [('PLANE', 'Plano de corte', 'Un plano que colocas en modo Objeto'),
                ('MARKED', 'Caras marcadas', 'Caras que dejaste seleccionadas en una sesión de Edición')]


# --------------------------------------------------------------------------- «clic y listo»
class ClickPlacer:
    """Mezcla para operadores modales en modo Objeto: un ayudante sigue al ratón sobre el
    modelo y con un clic se ejecuta la acción. Rueda = tamaño/giro, X/Y/Z = orientación,
    Esc o botón derecho = cancelar. El botón central sigue sirviendo para orbitar."""
    hint = ''

    # a implementar: create_helper(context, model), place(context, helper, loc, normal), commit(context, model, helper)
    def wheel(self, context, helper, up):
        pass

    def key(self, context, helper, key):
        return False

    def invoke(self, context, event):
        if context.area is None or context.area.type != 'VIEW_3D':
            self.report({'ERROR'}, 'Usa este botón desde la Vista 3D.')
            return {'CANCELLED'}
        try:
            self.model = pick_model(context)
            require_solid(context, self.model)
            bm = world_bmesh(context, self.model)
            try:
                self.tree = BVHTree.FromBMesh(bm)
            finally:
                bm.free()
            self.helper = self.create_helper(context, self.model)
        except AddonError as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        self.hit = None
        self.helper.hide_set(True)
        context.window_manager.modal_handler_add(self)
        context.area.header_text_set(self.hint)
        return {'RUNNING_MODAL'}

    def _ray(self, context, event):
        from bpy_extras import view3d_utils
        region = next((r for r in context.area.regions if r.type == 'WINDOW'), None)
        rv3d = context.area.spaces.active.region_3d
        if region is None or rv3d is None:
            return None
        x, y = event.mouse_x - region.x, event.mouse_y - region.y
        if not (0 <= x < region.width and 0 <= y < region.height):
            return None
        origin = view3d_utils.region_2d_to_origin_3d(region, rv3d, (x, y))
        direction = view3d_utils.region_2d_to_vector_3d(region, rv3d, (x, y))
        loc, normal, _i, _d = self.tree.ray_cast(origin, direction)
        if loc is None:
            return None
        if normal.dot(direction) > 0:
            normal = -normal
        return loc, normal

    def _end(self, context):
        context.area.header_text_set(None)

    def modal(self, context, event):
        if event.type in {'MIDDLEMOUSE', 'TRACKPADPAN', 'TRACKPADZOOM', 'NDOF_MOTION'} or (event.type.startswith('NUMPAD') and event.value == 'PRESS'):
            return {'PASS_THROUGH'}
        if event.type in {'ESC', 'RIGHTMOUSE'} and event.value == 'PRESS':
            remove_objects([self.helper])
            _select_only(context, self.model)
            self._end(context)
            return {'CANCELLED'}
        if event.type in {'WHEELUPMOUSE', 'WHEELDOWNMOUSE'}:
            if event.ctrl:
                return {'PASS_THROUGH'}          # Ctrl + rueda: zoom normal
            self.wheel(context, self.helper, event.type == 'WHEELUPMOUSE')
            if self.hit:
                self.place(context, self.helper, *self.hit)
            return {'RUNNING_MODAL'}
        if event.value == 'PRESS' and self.key(context, self.helper, event.type):
            if self.hit:
                self.place(context, self.helper, *self.hit)
            return {'RUNNING_MODAL'}
        if event.type == 'MOUSEMOVE':
            self.hit = self._ray(context, event)
            self.helper.hide_set(self.hit is None)
            if self.hit:
                self.place(context, self.helper, *self.hit)
            return {'RUNNING_MODAL'}
        if event.type == 'LEFTMOUSE' and event.value == 'PRESS':
            if not self.hit:
                return {'RUNNING_MODAL'}
            self.helper.hide_set(False)
            self._end(context)
            try:
                message = self.commit(context, self.model, self.helper)
            except AddonError as exc:
                remove_objects([self.helper])
                _select_only(context, self.model)
                self.report({'ERROR'}, str(exc))
                return {'CANCELLED'}
            self.report({'INFO'}, message)
            return {'FINISHED'}
        return {'RUNNING_MODAL'}


AXIS_NAMES = {'Z': 'horizontal', 'X': 'vertical (X)', 'Y': 'vertical (Y)'}


def place_plane(plane, loc, axis):
    plane.location = loc
    plane.rotation_euler = {'X': (0, math.pi / 2, 0), 'Y': (math.pi / 2, 0, 0)}.get(axis, (0, 0, 0))


def place_cutter(cutter, loc, normal):
    """El cortador se centra en el punto y se alinea con la superficie: la mitad queda dentro."""
    cutter.location = loc
    cutter.rotation_euler = normal.to_track_quat('Z', 'Y').to_euler()


def commit_split(context, model, plane, *args):
    _select_only(context, plane)
    model.select_set(True)
    return split_with_plane(context, *args)


def commit_inlay(context, model, cutter, tolerance_mm, unit):
    _select_only(context, cutter)
    model.select_set(True)
    return inlay_from_cutter(context, tolerance_mm, unit)
