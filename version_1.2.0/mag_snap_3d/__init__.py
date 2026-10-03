bl_info = {'name': 'MagSnap 3D (Magnet Splitter & Exporter)', 'author': 'Ricardo Lugaresi', 'version': (1, 2, 0),
           'blender': (4, 2, 0), 'location': 'Vista 3D > N > MagSnap 3D',
           'description': 'Separa sólidos con alojamientos para imanes y exporta en mm. Todo en modo Objeto', 'category': 'Object'}
import math
import bpy
from . import common


class MagSnapSettings(bpy.types.PropertyGroup):
    model_unit: bpy.props.EnumProperty(name='Unidades de entrada', items=common.UNIT_ITEMS, default='SCENE')
    region: bpy.props.EnumProperty(name='Separar por', items=common.REGION_ITEMS, default='PLANE')
    plane_axis: bpy.props.EnumProperty(name='Orientación inicial', items=[('Z', 'Horizontal', 'Corte a lo alto (normal Z)'), ('X', 'Vertical X', 'Normal X'), ('Y', 'Vertical Y', 'Normal Y')], default='Z')
    magnet_diameter: bpy.props.FloatProperty(name='Diámetro del imán (mm)', default=5, min=.5, max=60)
    magnet_height: bpy.props.FloatProperty(name='Grosor del imán (mm)', default=2, min=.2, max=30)
    tolerance: bpy.props.FloatProperty(name='Holgura radial/profundidad (mm)', default=.15, min=.01, max=2)
    minimum_wall: bpy.props.FloatProperty(name='Pared mínima (mm)', default=1, min=.1, max=20)
    mode: bpy.props.EnumProperty(name='Colocación', items=[('AUTO', 'Automática', 'Dos imanes si caben; uno en caso contrario'), ('ONE', 'Un imán', 'Un alojamiento'), ('TWO', 'Dos imanes', 'Dos alojamientos; cancela si no caben')], default='AUTO')
    export_folder: bpy.props.StringProperty(name='Carpeta de salida', default='//STLs_MagSnap', subtype='DIR_PATH')
    scope: bpy.props.EnumProperty(name='Exportar', items=common.SCOPE_ITEMS, default='SELECTED')
    show_advanced: bpy.props.BoolProperty(name='Colocar a mano / caras marcadas', default=False)


class OBJECT_OT_magsnap_add_plane(bpy.types.Operator):
    """Añade un plano de corte en el centro del modelo. Muévelo y gíralo en modo Objeto"""
    bl_idname = 'object.magsnap_add_plane'; bl_label = 'Añadir plano de corte'; bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return common.poll_object_mode(cls, context)

    def execute(self, context):
        try:
            common.add_cut_plane(context, common.pick_model(context), context.scene.magsnap_props.plane_axis)
        except common.AddonError as exc:
            self.report({'ERROR'}, str(exc)); return {'CANCELLED'}
        self.report({'INFO'}, 'Plano añadido: colócalo (G / R) y pulsa «Separar».'); return {'FINISHED'}


class OBJECT_OT_magsnap_split(bpy.types.Operator):
    """Separa el modelo en dos piezas y abre alojamientos enfrentados para imanes"""
    bl_idname = 'object.magsnap_split'; bl_label = 'Separar y crear alojamientos'; bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return common.poll_object_mode(cls, context)

    def execute(self, context):
        p = context.scene.magsnap_props
        fn = common.split_with_plane if p.region == 'PLANE' else common.split_marked
        try:
            count = fn(context, 'MAGNET', p.magnet_diameter / 2, p.magnet_height, p.tolerance, p.minimum_wall, p.mode, p.model_unit)
        except common.AddonError as exc:
            self.report({'ERROR'}, str(exc)); return {'CANCELLED'}
        self.report({'INFO'}, f'{count} alojamiento(s) por pieza. Original conservado y oculto.'); return {'FINISHED'}


class OBJECT_OT_magsnap_click(common.ClickPlacer, bpy.types.Operator):
    """Clic en el modelo donde quieres separar: se corta ahí y se ponen los imanes"""
    bl_idname = 'object.magsnap_click'; bl_label = 'Clic en el modelo para separar'; bl_options = {'REGISTER', 'UNDO'}
    hint = 'Clic: separar aquí · X / Y / Z: orientación del corte · Rueda: girar 5° · Esc: cancelar'

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
        p = context.scene.magsnap_props
        n = common.commit_split(context, model, helper, 'MAGNET', p.magnet_diameter / 2, p.magnet_height, p.tolerance, p.minimum_wall, p.mode, p.model_unit)
        return f'Separado con {n} imán(es) por cara. Ctrl+Z si quieres probar en otro sitio.'


class OBJECT_OT_magsnap_export_stls(bpy.types.Operator):
    """Exporta las piezas a STL en milímetros sin tocar los originales"""
    bl_idname = 'object.magsnap_export_stls'; bl_label = 'Exportar piezas a STL'

    @classmethod
    def poll(cls, context):
        return common.poll_object_mode(cls, context)

    def execute(self, context):
        p = context.scene.magsnap_props
        try:
            files = common.export_meshes(context, p.export_folder, p.scope, p.model_unit)
        except (common.AddonError, OSError) as exc:
            self.report({'ERROR'}, str(exc)); return {'CANCELLED'}
        self.report({'INFO'}, f'{len(files)} STL exportados en mm.'); return {'FINISHED'}


class VIEW3D_PT_magsnap_panel(bpy.types.Panel):
    bl_label = 'MagSnap 3D'; bl_idname = 'VIEW3D_PT_magsnap_panel'; bl_space_type = 'VIEW_3D'; bl_region_type = 'UI'; bl_category = 'MagSnap 3D'

    def draw(self, context):
        layout = self.layout; p = context.scene.magsnap_props
        common.draw_mode_warning(layout, context)
        layout.prop(p, 'model_unit')
        box = layout.box(); box.label(text='Imanes', icon='SNAP_ON')
        for field in ('magnet_diameter', 'magnet_height', 'tolerance', 'minimum_wall', 'mode'):
            box.prop(p, field)
        col = layout.column(); col.scale_y = 1.6
        col.operator('object.magsnap_click', icon='RESTRICT_SELECT_OFF')
        layout.label(text='Elige el modelo, pulsa y haz clic donde cortar.')
        layout.label(text='X / Y / Z cambia la orientación; rueda la inclina.')
        adv = layout.box(); adv.prop(p, 'show_advanced', icon='TRIA_DOWN' if p.show_advanced else 'TRIA_RIGHT', emboss=False)
        if p.show_advanced:
            adv.prop(p, 'region', expand=True)
            if p.region == 'PLANE':
                row = adv.row(align=True); row.prop(p, 'plane_axis', text=''); row.operator('object.magsnap_add_plane', icon='MESH_PLANE')
                adv.label(text='Coloca el plano a mano (G / R) y separa:')
            else:
                adv.label(text='Usa las caras que dejaste seleccionadas.')
            adv.operator('object.magsnap_split', icon='MOD_BOOLEAN')
        box = layout.box(); box.label(text='Exportar', icon='EXPORT')
        box.prop(p, 'scope'); box.prop(p, 'export_folder'); box.operator('object.magsnap_export_stls', icon='EXPORT')
        layout.label(text='El original se conserva oculto.', icon='INFO')


classes = (MagSnapSettings, OBJECT_OT_magsnap_click, OBJECT_OT_magsnap_add_plane, OBJECT_OT_magsnap_split, OBJECT_OT_magsnap_export_stls, VIEW3D_PT_magsnap_panel)


def register():
    common.register_classes(classes, 'magsnap_props', MagSnapSettings)


def unregister():
    common.unregister_classes(classes, 'magsnap_props')
