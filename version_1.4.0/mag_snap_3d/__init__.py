bl_info = {'name': 'MagSnap 3D (Magnet Splitter & Exporter)', 'author': 'Ricardo Lugaresi', 'version': (1, 4, 0),
           'blender': (4, 2, 0), 'location': 'Vista 3D > N > MagSnap 3D',
           'description': 'Separa sólidos por una línea dibujada, con imanes, espigas o eje de giro, y exporta en mm. Todo en modo Objeto', 'category': 'Object'}
import math
import bpy
from . import common, line_cut

CONNECTOR_ITEMS = [('MAGNET', 'Imán', 'Alojamiento enfrentado en las dos caras para un imán'),
                   ('DOWEL', 'Espiga', 'Agujero en las dos caras y una espiga suelta para imprimir'),
                   ('PIVOT', 'Giro', 'Eje a presión: la pieza de arriba gira sobre la de abajo (cabeza, torreta, rueda)'),
                   ('NONE', 'Ninguno', 'Solo separar, sin conectores')]
COUNT_ITEMS = [('AUTO', 'Automático', 'Dos por zona si caben (no deja girar la pieza); si no, uno'),
               ('ONE', 'Uno', 'Uno por zona, en la parte más gruesa'),
               ('TWO', 'Dos', 'Dos por zona; cancela si no caben')]


class MagSnapSettings(bpy.types.PropertyGroup):
    model_unit: bpy.props.EnumProperty(name='Unidades', items=common.UNIT_ITEMS, default='AUTO')
    plane_axis: bpy.props.EnumProperty(name='Orientación', items=[('Z', 'Horizontal', 'Corte a lo alto (normal Z)'), ('X', 'Vertical X', 'Normal X'), ('Y', 'Vertical Y', 'Normal Y')], default='Z')
    connector: bpy.props.EnumProperty(name='Conector', items=CONNECTOR_ITEMS, default='MAGNET')
    magnet_diameter: bpy.props.FloatProperty(name='Diámetro', description='Diámetro del imán en mm', default=5, min=.5, max=60, precision=1)
    magnet_height: bpy.props.FloatProperty(name='Grosor', description='Grosor del imán en mm', default=2, min=.2, max=30, precision=1)
    dowel_diameter: bpy.props.FloatProperty(name='Diámetro', description='Diámetro de la espiga en mm', default=4, min=1, max=40, precision=1)
    dowel_length: bpy.props.FloatProperty(name='Largo', description='Largo total de la espiga en mm (la mitad entra en cada pieza)', default=16, min=2, max=200, precision=1)
    pivot_diameter: bpy.props.FloatProperty(name='Diámetro', description='Diámetro del eje de giro en mm', default=5, min=1.5, max=40, precision=1)
    pivot_length: bpy.props.FloatProperty(name='Largo', description='Lo que el eje entra en la pieza de arriba, en mm', default=6, min=2, max=60, precision=1)
    line_points: bpy.props.StringProperty(name='Puntos de la línea', default='')
    line_report: bpy.props.StringProperty(name='Línea de corte', default='')
    line_model: bpy.props.StringProperty(name='Modelo de la línea', default='')
    mode: bpy.props.EnumProperty(name='Cantidad', items=COUNT_ITEMS, default='AUTO')
    tolerance: bpy.props.FloatProperty(name='Holgura', description='Holgura radial y de profundidad del alojamiento, en mm', default=.15, min=.01, max=2, precision=2)
    minimum_wall: bpy.props.FloatProperty(name='Pared mínima', description='Material mínimo alrededor y al fondo del alojamiento, en mm', default=1, min=.1, max=20, precision=1)
    show_fine: bpy.props.BoolProperty(name='Ajustes finos', default=False)
    export_folder: bpy.props.StringProperty(name='Carpeta', default='//STLs_MagSnap', subtype='DIR_PATH')
    scope: bpy.props.EnumProperty(name='Exportar', items=common.SCOPE_ITEMS, default='SELECTED')


def connector_args(p):
    """(tipo, radio, largo) del conector elegido, en mm."""
    if p.connector == 'DOWEL':
        return 'DOWEL', p.dowel_diameter / 2, p.dowel_length
    if p.connector == 'NONE':
        return 'NONE', 0.0, 0.0
    if p.connector == 'PIVOT':
        return 'PIVOT', p.pivot_diameter / 2, p.pivot_length
    return 'MAGNET', p.magnet_diameter / 2, p.magnet_height


def split_args(p):
    kind, radius, length = connector_args(p)
    return kind, radius, length, p.tolerance, p.minimum_wall, p.mode, p.model_unit


class OBJECT_OT_magsnap_add_plane(bpy.types.Operator):
    """Añade un plano de corte en el centro del modelo. Muévelo y gíralo (G / R) en modo Objeto"""
    bl_idname = 'object.magsnap_add_plane'; bl_label = 'Plano manual'; bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return common.poll_object_mode(cls, context)

    def execute(self, context):
        try:
            common.add_cut_plane(context, common.pick_model(context), context.scene.magsnap_props.plane_axis)
        except common.AddonError as exc:
            self.report({'ERROR'}, str(exc)); return {'CANCELLED'}
        self.report({'INFO'}, 'Plano añadido: colócalo (G / R) y pulsa «Separar por el plano».'); return {'FINISHED'}


class OBJECT_OT_magsnap_split(bpy.types.Operator):
    """Separa el modelo por el plano de corte y pone los conectores elegidos"""
    bl_idname = 'object.magsnap_split'; bl_label = 'Separar por el plano'; bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return common.poll_object_mode(cls, context)

    def execute(self, context):
        try:
            message = common.split_with_plane(context, *split_args(context.scene.magsnap_props))
        except common.AddonError as exc:
            self.report({'ERROR'}, str(exc)); return {'CANCELLED'}
        self.report({'INFO'}, message); return {'FINISHED'}


class OBJECT_OT_magsnap_click(common.ClickPlacer, bpy.types.Operator):
    """Pasa el ratón por el modelo y haz clic donde quieras separar: se corta ahí y se ponen los conectores"""
    bl_idname = 'object.magsnap_click'; bl_label = 'Clic en el modelo para separar'; bl_options = {'REGISTER', 'UNDO'}
    hint = 'Clic: separar aquí · X / Y / Z: orientación del corte · Shift + rueda: girar 5° · Esc: cancelar'

    @classmethod
    def poll(cls, context):
        return common.poll_object_mode(cls, context)

    def create_helper(self, context, model):
        self.axis = context.scene.magsnap_props.plane_axis
        self.tilt = 0.0
        return common.add_cut_plane(context, model, self.axis)

    def key(self, context, helper, key):
        if key in {'X', 'Y', 'Z'}:
            self.axis = key; self.tilt = 0.0; return True
        return False

    def wheel(self, context, helper, up):
        self.tilt += math.radians(5 if up else -5)

    def place(self, context, helper, loc, normal):
        common.place_plane(helper, loc, self.axis)
        helper.rotation_euler.rotate_axis('X', self.tilt)

    def commit(self, context, model, helper):
        message = common.commit_split(context, model, helper, *split_args(context.scene.magsnap_props))
        return message + ' Ctrl+Z para probar en otro sitio.'


class OBJECT_OT_magsnap_export_stls(bpy.types.Operator):
    """Exporta las piezas a STL en milímetros sin tocar los originales"""
    bl_idname = 'object.magsnap_export_stls'; bl_label = 'Exportar a STL'

    @classmethod
    def poll(cls, context):
        return common.poll_object_mode(cls, context)

    def execute(self, context):
        p = context.scene.magsnap_props
        try:
            files = common.export_meshes(context, p.export_folder, p.scope, p.model_unit)
        except (common.AddonError, OSError) as exc:
            self.report({'ERROR'}, str(exc)); return {'CANCELLED'}
        where = files[0].parent if files else common.export_folder(p.export_folder)
        self.report({'INFO'}, f'{len(files)} STL exportados en mm en {where}'); return {'FINISHED'}


def _current_model(context):
    try:
        return common.pick_model(context)
    except common.AddonError:
        return None


class VIEW3D_PT_magsnap_panel(bpy.types.Panel):
    bl_label = 'MagSnap 3D'; bl_idname = 'VIEW3D_PT_magsnap_panel'; bl_space_type = 'VIEW_3D'; bl_region_type = 'UI'; bl_category = 'MagSnap 3D'

    def draw(self, context):
        layout = self.layout; p = context.scene.magsnap_props
        layout.use_property_split = True; layout.use_property_decorate = False
        if common.draw_mode_warning(layout, context):
            return

        # 1 · Modelo
        box = layout.box()
        box.label(text='1 · Modelo', icon='MESH_DATA')
        model = _current_model(context)
        if model is None:
            row = box.row(); row.alert = True
            row.label(text='Selecciona el modelo a separar', icon='ERROR')
        else:
            code, mm = common.resolve_unit(context.scene, p.model_unit, model)
            d = [x * mm for x in model.dimensions]
            box.label(text=model.name, icon='OBJECT_DATA')
            box.label(text=f'{d[0]:.0f} × {d[1]:.0f} × {d[2]:.0f} mm')
            box.prop(p, 'model_unit')
            if p.model_unit == 'AUTO':
                box.label(text=f'Detectado: 1 unidad = 1 {common.UNIT_NAMES[code]}', icon='CHECKMARK')

        # 2 · Conector
        box = layout.box()
        box.label(text='2 · Conector', icon='SNAP_ON')
        row = box.row(); row.use_property_split = False
        row.prop(p, 'connector', expand=True)
        if p.connector != 'NONE':
            col = box.column(align=True)
            col.label(text='Medidas en mm')
            if p.connector == 'MAGNET':
                col.prop(p, 'magnet_diameter'); col.prop(p, 'magnet_height')
            elif p.connector == 'PIVOT':
                col.prop(p, 'pivot_diameter'); col.prop(p, 'pivot_length')
            else:
                col.prop(p, 'dowel_diameter'); col.prop(p, 'dowel_length')
            if p.connector == 'PIVOT':
                tip = box.column(align=True); tip.scale_y = .8
                tip.label(text='Sale de la pieza de abajo y encaja a presión', icon='INFO')
                tip.label(text='en la de arriba, que gira sobre él.')
            else:
                box.prop(p, 'mode')
            fine = box.column()
            fine.prop(p, 'show_fine', icon='TRIA_DOWN' if p.show_fine else 'TRIA_RIGHT', emboss=False)
            if p.show_fine:
                fine.prop(p, 'tolerance'); fine.prop(p, 'minimum_wall')

        # 3 · Cortar
        box = layout.box()
        box.label(text='3 · Cortar', icon='GREASEPENCIL')
        if not p.line_points:
            tip = box.column(align=True); tip.scale_y = .8
            tip.label(text='Pincha alrededor de la pieza por')
            tip.label(text='donde quieres separarla. Intro cierra.')
            col = box.column(); col.scale_y = 1.6
            col.operator('object.magsnap_draw_line', text='Dibujar línea', icon='GREASEPENCIL')
        else:
            if p.line_report:
                box.label(text=p.line_report, icon='INFO')
            row = box.row(align=True); row.use_property_split = False
            row.operator('object.magsnap_draw_line', text='Volver a dibujar', icon='GREASEPENCIL')
            row.operator('object.magsnap_clear_line', text='', icon='X')
            col = box.column(); col.scale_y = 1.6
            col.operator('object.magsnap_cut_line', icon='MOD_BOOLEAN')

        # 4 · Exportar
        box = layout.box()
        box.label(text='4 · Exportar STL', icon='EXPORT')
        row = box.row(); row.use_property_split = False
        row.prop(p, 'scope', expand=True)
        box.prop(p, 'export_folder')
        if p.export_folder.startswith('//') and not bpy.data.filepath:
            note = box.column(align=True); note.scale_y = .8
            note.label(text='.blend sin guardar: irá a', icon='INFO')
            note.label(text=common.export_folder(p.export_folder))
        box.operator('object.magsnap_export_stls', icon='EXPORT')


classes = (MagSnapSettings, *line_cut.classes, OBJECT_OT_magsnap_click, OBJECT_OT_magsnap_add_plane, OBJECT_OT_magsnap_split,
           OBJECT_OT_magsnap_export_stls, VIEW3D_PT_magsnap_panel)


def register():
    common.register_classes(classes, 'magsnap_props', MagSnapSettings)
    line_cut.register_draw()


def unregister():
    line_cut.unregister_draw()
    common.unregister_classes(classes, 'magsnap_props')
