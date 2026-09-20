bl_info = {
    "name": "MagSnap 3D (Auto Magnet Splitter & Exporter)",
    "author": "Asistente 3D",
    "version": (1, 0, 0),
    "blender": (3, 0, 0),
    "location": "View3D > Sidebar (N) > MagSnap 3D",
    "description": "Despiece automatico con cavidades para imanes de neodimio y exportacion individual de STLs",
    "category": "Mesh",
}

import bpy
import bmesh
from mathutils import Vector
import os

class MagSnapSettings(bpy.types.PropertyGroup):
    magnet_diameter: bpy.props.FloatProperty(
        name="Diametro Iman (mm)",
        description="Diametro nominal del iman de neodimio",
        default=5.0,
        min=1.0,
        max=30.0,
        unit='LENGTH'
    )
    magnet_height: bpy.props.FloatProperty(
        name="Grosor Iman (mm)",
        description="Altura o espesor del iman",
        default=2.0,
        min=0.5,
        max=15.0,
        unit='LENGTH'
    )
    tolerance: bpy.props.FloatProperty(
        name="Holgura FDM (mm)",
        description="Margen extra para que el iman encaje a ras y admita cianoacrilato",
        default=0.15,
        min=0.05,
        max=0.6,
        unit='LENGTH'
    )
    mode: bpy.props.EnumProperty(
        name="Colocacion",
        items=[
            ('AUTO', "Automatico", "Calcula si cabe 1 central o 2 emparejados segun el area de corte"),
            ('ONE', "1 Iman", "Fuerza un solo iman centrado"),
            ('TWO', "2 Imanes (Antigiro)", "Fuerza 2 imanes separados para evitar que la pieza rote")
        ],
        default='AUTO'
    )
    export_folder: bpy.props.StringProperty(
        name="Carpeta Destino",
        description="Ruta donde se guardaran los STLs sueltos",
        default="//STLs_MagSnap",
        subtype='DIR_PATH'
    )

class MESH_OT_magsnap_split(bpy.types.Operator):
    bl_idname = "mesh.magsnap_split"
    bl_label = "Separar y Cavar Huecos de Imanes"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        props = context.scene.magsnap_props
        base_obj = context.active_object

        if not base_obj or base_obj.mode != 'EDIT':
            self.report({'ERROR'}, "Debes estar en Edit Mode con la pieza seleccionada")
            return {'CANCELLED'}

        # 1. Analisis geometrico del borde de corte
        bm = bmesh.from_edit_mesh(base_obj.data)
        boundary_verts = [
            v for v in bm.verts 
            if v.select and any(not e.other_face(f) or not e.other_face(f).select for f in v.link_faces for e in f.edges)
        ]

        if boundary_verts:
            coords = [base_obj.matrix_world @ v.co for v in boundary_verts]
            center = sum(coords, Vector()) / len(coords)
            xs = [c.x for c in coords]
            ys = [c.y for c in coords]
            zs = [c.z for c in coords]
            span = max(max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs))
        else:
            selected_coords = [base_obj.matrix_world @ v.co for v in bm.verts if v.select]
            if not selected_coords:
                self.report({'ERROR'}, "No hay caras seleccionadas")
                return {'CANCELLED'}
            center = sum(selected_coords, Vector()) / len(selected_coords)
            span = 10.0

        # 2. Separacion de la pieza
        bpy.ops.mesh.separate(type='SELECTED')
        bpy.ops.object.mode_set(mode='OBJECT')

        part_b = [o for o in context.selected_objects if o != base_obj][0]
        part_b.name = f"{base_obj.name}_Pieza"

        # 3. Sellado hermetico de tapas de corte
        for ob in [base_obj, part_b]:
            context.view_layer.objects.active = ob
            bpy.ops.object.mode_set(mode='EDIT')
            bpy.ops.mesh.select_all(action='SELECT')
            bpy.ops.mesh.fill_holes(sides=0)
            bpy.ops.object.mode_set(mode='OBJECT')

        # 4. Calculo de distribucion de imanes
        count = 1
        if props.mode == 'AUTO':
            if span >= (props.magnet_diameter * 2.6):
                count = 2
            else:
                count = 1
        elif props.mode == 'TWO':
            count = 2

        locations = []
        if count == 1:
            locations.append(center)
            self.report({'INFO'}, f"1 Iman central colocado ({props.magnet_diameter}x{props.magnet_height} mm)")
        else:
            offset_dist = props.magnet_diameter * 0.75
            locations.append(center + Vector((offset_dist, 0, 0)))
            locations.append(center - Vector((offset_dist, 0, 0)))
            self.report({'INFO'}, "2 Imanes antigiro colocados")

        # 5. Vaciado booleano de orificios con tolerancia
        r_hole = (props.magnet_diameter / 2.0) + props.tolerance
        d_hole = props.magnet_height + props.tolerance

        for loc in locations:
            bpy.ops.mesh.primitive_cylinder_add(
                radius=r_hole,
                depth=d_hole * 2.0,
                location=loc
            )
            cutter = context.active_object

            # Cavidad en Base
            mod_a = base_obj.modifiers.new(name="Mag_Hole", type='BOOLEAN')
            mod_a.operation = 'DIFFERENCE'
            mod_a.object = cutter
            mod_a.solver = 'FAST'
            context.view_layer.objects.active = base_obj
            bpy.ops.object.modifier_apply(modifier="Mag_Hole")

            # Cavidad en Pieza B
            mod_b = part_b.modifiers.new(name="Mag_Hole", type='BOOLEAN')
            mod_b.operation = 'DIFFERENCE'
            mod_b.object = cutter
            mod_b.solver = 'FAST'
            context.view_layer.objects.active = part_b
            bpy.ops.object.modifier_apply(modifier="Mag_Hole")

            bpy.data.objects.remove(cutter, do_unlink=True)

        return {'FINISHED'}

class WM_OT_magsnap_export_stls(bpy.types.Operator):
    bl_idname = "wm.magsnap_export_stls"
    bl_label = "Exportar Todos los STLs Sueltos"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        props = context.scene.magsnap_props
        target_dir = bpy.path.abspath(props.export_folder)

        if not os.path.exists(target_dir):
            os.makedirs(target_dir, exist_ok=True)

        mesh_objects = [o for o in context.scene.objects if o.type == 'MESH']
        if not mesh_objects:
            self.report({'ERROR'}, "No hay mallas en la escena")
            return {'CANCELLED'}

        bpy.ops.object.select_all(action='DESELECT')
        count = 0

        for obj in mesh_objects:
            obj.select_set(True)
            context.view_layer.objects.active = obj

            # Normalizar escala y rotacion antes de exportar
            bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)

            file_path = os.path.join(target_dir, f"{obj.name}.stl")

            if hasattr(bpy.ops.wm, "stl_export"):
                bpy.ops.wm.stl_export(filepath=file_path, export_selected_objects=True)
            elif hasattr(bpy.ops.export_mesh, "stl"):
                bpy.ops.export_mesh.stl(filepath=file_path, use_selection=True)

            obj.select_set(False)
            count += 1

        self.report({'INFO'}, f"Exportacion exitosa: {count} archivos .stl generados")
        return {'FINISHED'}

class VIEW3D_PT_magsnap_panel(bpy.types.Panel):
    bl_label = "MagSnap 3D"
    bl_idname = "VIEW3D_PT_magsnap_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'MagSnap 3D'

    def draw(self, context):
        layout = self.layout
        props = context.scene.magsnap_props

        box1 = layout.box()
        box1.label(text="1. Ajustes del Iman:", icon='SNAP_FACE')
        box1.prop(props, "magnet_diameter")
        box1.prop(props, "magnet_height")
        box1.prop(props, "tolerance")
        box1.prop(props, "mode", text="Modo")
        box1.operator("mesh.magsnap_split", icon='MOD_BOOLEAN')

        layout.separator()

        box2 = layout.box()
        box2.label(text="2. Exportacion por Piezas:", icon='EXPORT')
        box2.prop(props, "export_folder")
        box2.operator("wm.magsnap_export_stls", icon='FILE_FOLDER')

classes = (
    MagSnapSettings,
    MESH_OT_magsnap_split,
    WM_OT_magsnap_export_stls,
    VIEW3D_PT_magsnap_panel,
)

def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.magsnap_props = bpy.props.PointerProperty(type=MagSnapSettings)

def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    del bpy.types.Scene.magsnap_props

if __name__ == "__main__":
    register()