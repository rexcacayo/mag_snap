"""Línea de corte para MagSnap: se pincha alrededor del modelo y se corta por ella.

Controles mientras se dibuja:
  clic izquierdo   añadir punto (sobre la superficie)
  clic en el verde cerrar la línea  ·  Intro también cierra
  Retroceso        quitar el último punto
  Esc / clic dcho  cancelar
  rueda / botón central   zoom y girar la vista como siempre
"""
import bpy
import gpu
from bpy_extras import view3d_utils
from gpu_extras.batch import batch_for_shader
from mathutils import Vector
from mathutils.bvhtree import BVHTree

from . import common

_HANDLE = None
_LIVE = {'points': None, 'hover': None}
COLOR_LINE = (1.0, 0.82, 0.1, 1.0)
COLOR_FIRST = (0.35, 1.0, 0.45, 1.0)
COLOR_HOVER = (1.0, 1.0, 1.0, 0.8)
CLOSE_PX = 14


def stored_points(props):
    out = []
    for item in props.line_points.split(';'):
        if item.strip():
            out.append(Vector(tuple(float(v) for v in item.split(','))))
    return out


def _draw():
    scene = getattr(bpy.context, 'scene', None)
    props = getattr(scene, 'magsnap_props', None) if scene else None
    live = _LIVE['points']
    if live is not None:
        pts, closed = list(live), False
    elif props is not None and props.line_points:
        try:
            pts = stored_points(props)
        except ValueError:
            return
        closed = len(pts) >= 3
    else:
        return
    if not pts and _LIVE['hover'] is None:
        return
    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    gpu.state.blend_set('ALPHA')
    gpu.state.depth_test_set('NONE')
    gpu.state.line_width_set(3.0)
    strip = list(pts)
    if live is not None and _LIVE['hover'] is not None and pts:
        strip.append(_LIVE['hover'])
    if closed:
        strip.append(pts[0])
    if len(strip) >= 2:
        b = batch_for_shader(shader, 'LINE_STRIP', {'pos': [tuple(p) for p in strip]})
        shader.uniform_float('color', COLOR_LINE); b.draw(shader)
    if pts:
        gpu.state.point_size_set(9.0)
        b = batch_for_shader(shader, 'POINTS', {'pos': [tuple(p) for p in pts]})
        shader.uniform_float('color', COLOR_LINE); b.draw(shader)
        gpu.state.point_size_set(13.0)
        b = batch_for_shader(shader, 'POINTS', {'pos': [tuple(pts[0])]})
        shader.uniform_float('color', COLOR_FIRST); b.draw(shader)
    if live is not None and _LIVE['hover'] is not None:
        gpu.state.point_size_set(7.0)
        b = batch_for_shader(shader, 'POINTS', {'pos': [tuple(_LIVE['hover'])]})
        shader.uniform_float('color', COLOR_HOVER); b.draw(shader)
    gpu.state.point_size_set(1.0)
    gpu.state.line_width_set(1.0)
    gpu.state.depth_test_set('LESS_EQUAL')
    gpu.state.blend_set('NONE')


def register_draw():
    global _HANDLE
    if _HANDLE is None:
        _HANDLE = bpy.types.SpaceView3D.draw_handler_add(_draw, (), 'WINDOW', 'POST_VIEW')


def unregister_draw():
    global _HANDLE
    if _HANDLE is not None:
        bpy.types.SpaceView3D.draw_handler_remove(_HANDLE, 'WINDOW')
        _HANDLE = None


def _redraw(context):
    for area in (context.screen.areas if context.screen else ()):
        if area.type == 'VIEW_3D':
            area.tag_redraw()


def describe(points, scale):
    try:
        _co, normal, dev = common.fit_plane(points)
    except common.AddonError as exc:
        return str(exc)
    tilt = common.tilt_degrees(normal)
    text = f'{len(points)} puntos · corte ' + ('recto' if tilt < .05 else f'inclinado {tilt:.0f}°')
    if dev * scale > 1.0:
        text += f' · se aparta {dev * scale:.1f} mm del plano medio'
    return text


class OBJECT_OT_magsnap_draw_line(bpy.types.Operator):
    """Pincha alrededor del modelo por donde quieres separarlo. Intro o clic en el punto verde cierra"""
    bl_idname = 'object.magsnap_draw_line'; bl_label = 'Dibujar línea de corte'; bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return common.poll_object_mode(cls, context) and context.area is not None and context.area.type == 'VIEW_3D'

    def invoke(self, context, event):
        try:
            self.model = common.pick_model(context)
            bm = common.world_bmesh(context, self.model)
            try:
                self.tree = BVHTree.FromBMesh(bm)
            finally:
                bm.free()
        except common.AddonError as exc:
            self.report({'ERROR'}, str(exc)); return {'CANCELLED'}
        self.points, self._orbit = [], False
        register_draw()
        _LIVE['points'], _LIVE['hover'] = self.points, None
        context.window.cursor_modal_set('CROSSHAIR')
        context.window_manager.modal_handler_add(self)
        self._header(context)
        return {'RUNNING_MODAL'}

    def _region(self, context):
        region = next((r for r in context.area.regions if r.type == 'WINDOW'), None)
        return region, context.area.spaces.active.region_3d

    def _hit(self, context, event):
        region, rv3d = self._region(context)
        if region is None or rv3d is None:
            return None
        x, y = event.mouse_x - region.x, event.mouse_y - region.y
        if not (0 <= x < region.width and 0 <= y < region.height):
            return None
        origin = view3d_utils.region_2d_to_origin_3d(region, rv3d, (x, y))
        direction = view3d_utils.region_2d_to_vector_3d(region, rv3d, (x, y))
        loc, _n, _i, _d = self.tree.ray_cast(origin, direction)
        return loc

    def _near_first(self, context, event):
        if len(self.points) < 3:
            return False
        region, rv3d = self._region(context)
        p = view3d_utils.location_3d_to_region_2d(region, rv3d, self.points[0])
        if p is None:
            return False
        dx, dy = p.x - (event.mouse_x - region.x), p.y - (event.mouse_y - region.y)
        return dx * dx + dy * dy <= CLOSE_PX * CLOSE_PX

    def _header(self, context):
        n = len(self.points)
        tail = 'clic en el punto verde o Intro = cerrar · ' if n >= 3 else ''
        context.area.header_text_set(f'Línea de corte: {n} puntos · clic = punto · {tail}Retroceso = deshacer · Esc = cancelar · rueda = zoom')

    def _end(self, context):
        _LIVE['points'], _LIVE['hover'] = None, None
        context.area.header_text_set(None)
        context.window.cursor_modal_restore()
        _redraw(context)

    def modal(self, context, event):
        if context.area is None:
            self._end(context); return {'CANCELLED'}
        if event.type == 'MIDDLEMOUSE':
            self._orbit = event.value == 'PRESS'
            return {'PASS_THROUGH'}
        if event.type in {'WHEELUPMOUSE', 'WHEELDOWNMOUSE', 'TRACKPADPAN', 'TRACKPADZOOM', 'NDOF_MOTION'} or (
                event.type.startswith('NUMPAD') and event.type != 'NUMPAD_ENTER'):
            return {'PASS_THROUGH'}
        if event.type in {'MOUSEMOVE', 'INBETWEEN_MOUSEMOVE'}:
            if self._orbit:
                return {'PASS_THROUGH'}
            _LIVE['hover'] = self._hit(context, event)
            context.area.tag_redraw()
            return {'RUNNING_MODAL'}
        if event.value != 'PRESS':
            return {'RUNNING_MODAL'}
        if event.type in {'ESC', 'RIGHTMOUSE'}:
            self._end(context); self.report({'INFO'}, 'Línea cancelada'); return {'CANCELLED'}
        if event.type == 'BACK_SPACE':
            if self.points:
                self.points.pop()
            self._header(context); context.area.tag_redraw()
            return {'RUNNING_MODAL'}
        close = event.type in {'RET', 'NUMPAD_ENTER', 'SPACE'} and len(self.points) >= 3
        if event.type == 'LEFTMOUSE':
            if self._near_first(context, event):
                close = True
            else:
                hit = self._hit(context, event)
                if hit is None:
                    self.report({'WARNING'}, 'Pincha sobre el modelo')
                else:
                    self.points.append(hit.copy())
                    self._header(context); context.area.tag_redraw()
                return {'RUNNING_MODAL'}
        if close:
            p = context.scene.magsnap_props
            p.line_points = ';'.join(f'{v.x:.6f},{v.y:.6f},{v.z:.6f}' for v in self.points)
            p.line_model = self.model.name
            scale = common.factor(context.scene, p.model_unit, self.model)
            p.line_report = describe(self.points, scale)
            self._end(context)
            self.report({'INFO'}, p.line_report)
            return {'FINISHED'}
        return {'RUNNING_MODAL'}


def line_model(context):
    p = context.scene.magsnap_props
    obj = bpy.data.objects.get(p.line_model)
    return obj if obj is not None and obj.type == 'MESH' else None


class OBJECT_OT_magsnap_cut_line(bpy.types.Operator):
    """Separa el modelo por la línea dibujada y pone los conectores elegidos"""
    bl_idname = 'object.magsnap_cut_line'; bl_label = 'Separar por la línea'; bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        if not common.poll_object_mode(cls, context):
            return False
        p = context.scene.magsnap_props
        return bool(p.line_points) and line_model(context) is not None

    def execute(self, context):
        from . import split_args
        p = context.scene.magsnap_props
        model = line_model(context)
        try:
            co, normal, _dev = common.fit_plane(stored_points(p))
            message = common.split_at(context, model, co, normal, *split_args(p))
        except common.AddonError as exc:
            self.report({'ERROR'}, str(exc)); return {'CANCELLED'}
        p.line_points = ''; p.line_report = ''; p.line_model = ''
        _redraw(context)
        self.report({'INFO'}, message + ' Ctrl+Z para probar en otro sitio.')
        return {'FINISHED'}


class OBJECT_OT_magsnap_clear_line(bpy.types.Operator):
    """Borra la línea de corte dibujada"""
    bl_idname = 'object.magsnap_clear_line'; bl_label = 'Borrar línea'; bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return bool(context.scene.magsnap_props.line_points)

    def execute(self, context):
        p = context.scene.magsnap_props
        p.line_points = ''; p.line_report = ''; p.line_model = ''
        _redraw(context)
        return {'FINISHED'}


classes = (OBJECT_OT_magsnap_draw_line, OBJECT_OT_magsnap_cut_line, OBJECT_OT_magsnap_clear_line)
