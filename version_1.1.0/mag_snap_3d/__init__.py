bl_info = {'name':'MagSnap 3D (Magnet Splitter & Exporter)', 'author':'Asistente 3D', 'version':(1,1,0), 'blender':(4,2,0), 'location':'Vista 3D > N > MagSnap 3D', 'description':'Separa sólidos con alojamientos orientados para imanes y exporta en mm', 'category':'Mesh'}
import bpy
from . import common

class MagSnapSettings(bpy.types.PropertyGroup):
    model_unit: bpy.props.EnumProperty(name='Unidades de entrada',items=common.UNIT_ITEMS,default='SCENE')
    magnet_diameter: bpy.props.FloatProperty(name='Diámetro del imán (mm)',default=5,min=.5,max=60)
    magnet_height: bpy.props.FloatProperty(name='Grosor del imán (mm)',default=2,min=.2,max=30)
    tolerance: bpy.props.FloatProperty(name='Holgura radial/profundidad (mm)',default=.15,min=.01,max=2)
    minimum_wall: bpy.props.FloatProperty(name='Pared mínima (mm)',default=1,min=.1,max=20)
    mode: bpy.props.EnumProperty(name='Colocación',items=[('AUTO','Automática','Dos imanes si caben; uno en caso contrario'),('ONE','Un imán','Un alojamiento interior'),('TWO','Dos imanes','Dos alojamientos; cancela si no caben')],default='AUTO')
    export_folder: bpy.props.StringProperty(name='Carpeta de salida',default='//STLs_MagSnap',subtype='DIR_PATH')
    scope: bpy.props.EnumProperty(name='Exportar',items=common.SCOPE_ITEMS,default='SELECTED')

class MESH_OT_magsnap_split(bpy.types.Operator):
    bl_idname='mesh.magsnap_split'; bl_label='Separar y crear alojamientos'; bl_options={'REGISTER','UNDO'}
    @classmethod
    def poll(cls,context): return context.mode=='EDIT_MESH' and context.active_object is not None
    def execute(self,context):
        p=context.scene.magsnap_props
        try: count=common.split_connectors(context,'MAGNET',p.magnet_diameter/2,p.magnet_height,p.tolerance,p.minimum_wall,p.mode,p.model_unit)
        except Exception as exc:
            self.report({'ERROR'},str(exc)); return {'CANCELLED'}
        self.report({'INFO'},f'{count} alojamientos por pieza. Original conservado y oculto.'); return {'FINISHED'}

class WM_OT_magsnap_export_stls(bpy.types.Operator):
    bl_idname='wm.magsnap_export_stls'; bl_label='Exportar piezas a STL'
    @classmethod
    def poll(cls,context): return context.mode=='OBJECT'
    def execute(self,context):
        p=context.scene.magsnap_props
        try: files=common.export_meshes(context,p.export_folder,p.scope,p.model_unit)
        except Exception as exc:
            self.report({'ERROR'},str(exc)); return {'CANCELLED'}
        self.report({'INFO'},f'{len(files)} STL exportados en mm. Originales sin modificar.'); return {'FINISHED'}

class VIEW3D_PT_magsnap_panel(bpy.types.Panel):
    bl_label='MagSnap 3D'; bl_idname='VIEW3D_PT_magsnap_panel'; bl_space_type='VIEW_3D'; bl_region_type='UI'; bl_category='MagSnap 3D'
    def draw(self,context):
        layout=self.layout; p=context.scene.magsnap_props
        layout.prop(p,'model_unit'); box=layout.box(); box.label(text='Caras seleccionadas, borde de corte plano')
        for field in ['magnet_diameter','magnet_height','tolerance','minimum_wall','mode']: box.prop(p,field)
        box.operator('mesh.magsnap_split',icon='MOD_BOOLEAN')
        layout.label(text='El original se conserva oculto.')
        box=layout.box(); box.prop(p,'scope'); box.prop(p,'export_folder'); box.operator('wm.magsnap_export_stls',icon='EXPORT')

classes=(MagSnapSettings,MESH_OT_magsnap_split,WM_OT_magsnap_export_stls,VIEW3D_PT_magsnap_panel)
def register(): common.register_classes(classes,'magsnap_props',MagSnapSettings)
def unregister(): common.unregister_classes(classes,'magsnap_props')
