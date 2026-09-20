"""Shared, bundled helpers. Blender 4.2+; all public distances are millimetres."""
import bpy
import bmesh
import math
import os
import re
import struct
from pathlib import Path
from mathutils import Vector
from mathutils.bvhtree import BVHTree

class AddonError(ValueError):
    pass

def factor(scene, unit='SCENE'):
    return {'MM': 1.0, 'M': 1000.0}.get(unit, scene.unit_settings.scale_length * 1000.0)

def safe_name(name):
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', str(name)).strip(' .')[:100] or 'Pieza'
    if re.match(r'^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)', name, re.I):
        name = '_' + name
    return name

def unique_name(name, used):
    base = safe_name(name); candidate = base; i = 2
    while candidate.casefold() in used:
        candidate = f'{base}_{i:03d}'; i += 1
    used.add(candidate.casefold())
    return candidate

def export_meshes(context, path, scope='SELECTED', unit='SCENE', by_color=False):
    if not path.strip(): raise AddonError('Selecciona una carpeta de salida.')
    if path.startswith('//') and not bpy.data.filepath:
        raise AddonError('Guarda el .blend o elige una carpeta absoluta de salida.')
    if context.mode != 'OBJECT': raise AddonError('Exporta desde el modo Objeto.')
    candidates = context.selected_objects if scope == 'SELECTED' else context.visible_objects
    objects = sorted((o for o in candidates if o.type == 'MESH'), key=lambda o:o.name)
    if not objects: raise AddonError('No hay mallas seleccionadas/visibles para exportar.')
    dest = Path(bpy.path.abspath(path)).resolve()
    if dest.exists() and not dest.is_dir(): raise AddonError('La ruta de salida no es una carpeta.')
    scale = factor(context.scene, unit)
    graph = context.evaluated_depsgraph_get()
    color_dirs = {}; used_dirs = set(); planned=[]
    # Preflight and collect evaluated triangles without changing any source object.
    for obj in objects:
        folder = dest
        if by_color:
            slots = {p.material_index for p in obj.data.polygons}
            materials = {obj.data.materials[i].name if i < len(obj.data.materials) and obj.data.materials[i] else 'Sin_Color' for i in slots}
            if len(materials)>1:
                raise AddonError(f'{obj.name}: tiene varios materiales. Sepáralo por material antes de exportar por color.')
            color = next(iter(materials), 'Sin_Color')
            if color not in color_dirs: color_dirs[color]=unique_name(color, used_dirs)
            folder=dest/color_dirs[color]
        evaluated=obj.evaluated_get(graph); me=evaluated.to_mesh()
        try:
            me.calc_loop_triangles(); triangles=[]
            flip=obj.matrix_world.determinant()<0
            for t in me.loop_triangles:
                vs=[obj.matrix_world @ me.vertices[i].co * scale for i in t.vertices]
                if flip: vs[1],vs[2]=vs[2],vs[1]
                normal=(vs[1]-vs[0]).cross(vs[2]-vs[0])
                if normal.length < 1e-12: continue
                normal.normalize()
                triangles.append((normal,vs))
            if not triangles: raise AddonError(f'{obj.name}: la malla no tiene triángulos válidos.')
            planned.append((folder,obj.name,triangles))
        finally: evaluated.to_mesh_clear()
    created=[]
    try:
        for folder,name,triangles in planned:
            folder.mkdir(parents=True,exist_ok=True)
            used={p.stem.casefold() for p in folder.iterdir()}
            filename=unique_name(name,used)+'.stl'
            target=folder/filename
            # Exclusive creation: existing exports are never silently overwritten.
            with target.open('xb') as handle:
                created.append(target)
                handle.write(b'Blender addon - coordinates in millimeters'.ljust(80,b'\0'))
                handle.write(struct.pack('<I',len(triangles)))
                for normal,vs in triangles:
                    handle.write(struct.pack('<12fH',*normal,*vs[0],*vs[1],*vs[2],0))
    except Exception:
        for file in created:
            if file.is_file(): file.unlink()
        raise
    return created

def active_patch(context):
    obj=context.active_object
    if not obj or obj.type!='MESH' or obj.mode!='EDIT':
        raise AddonError('Selecciona caras de una malla en modo Edición.')
    if len(context.objects_in_mode_unique_data)!=1:
        raise AddonError('Edita una sola malla a la vez para separar o crear insertos.')
    if any(m.show_viewport for m in obj.modifiers):
        raise AddonError('La malla tiene modificadores activos. Aplica los necesarios en una copia antes de separar.')
    obj.update_from_editmode()
    bm=bmesh.from_edit_mesh(obj.data)
    if not bm.faces or any(not e.is_manifold for e in bm.edges):
        raise AddonError('La malla original debe estar cerrada y ser manifold.')
    mask=[f.select for f in bm.faces]
    if not any(mask) or all(mask):
        raise AddonError('Selecciona una parte de las caras; no toda la malla.')
    # Face indices used below must match the object mesh after leaving edit mode.
    bpy.ops.object.mode_set(mode='OBJECT')
    mask=[p.select for p in obj.data.polygons]
    return obj,mask

def source_bmesh(obj):
    bm=bmesh.new(); bm.from_mesh(obj.data)
    bmesh.ops.transform(bm,matrix=obj.matrix_world,verts=list(bm.verts))
    bmesh.ops.recalc_face_normals(bm,faces=list(bm.faces))
    return bm

def boundary_loop(bm, selected=None):
    edges=[e for e in bm.edges if (e.is_boundary if selected is None else sum(f in selected for f in e.link_faces)==1)]
    if not edges: raise AddonError('No se ha encontrado un borde de separación.')
    adjacent={}
    for e in edges:
        for v in e.verts: adjacent.setdefault(v,[]).append(e)
    if any(len(es)!=2 for es in adjacent.values()):
        raise AddonError('El borde debe formar un único contorno cerrado, sin cruces.')
    start=edges[0].verts[0]; current=start; last=None; ordered=[]
    while True:
        ordered.append(current)
        edge=next(e for e in adjacent[current] if e is not last)
        current=edge.other_vert(current); last=edge
        if current is start: break
        if len(ordered)>len(edges): raise AddonError('Contorno no válido.')
    if len(ordered)!=len(edges):
        raise AddonError('Selecciona una región con un único borde; hay varios contornos.')
    return ordered

def frame(points, mm_factor):
    center=sum(points,Vector())/len(points)
    normal=Vector()
    for a,b in zip(points,points[1:]+points[:1]): normal+=(a-center).cross(b-center)
    if normal.length<1e-14: raise AddonError('El contorno de corte no tiene área.')
    normal.normalize()
    if max(abs((p-center).dot(normal)) for p in points)*mm_factor > .02:
        raise AddonError('El borde de separación no es plano (desviación > 0,02 mm). Crea un corte plano primero.')
    u=max((p-center for p in points),key=lambda v:v.length).normalized()
    u=(u-normal*u.dot(normal)).normalized(); v=normal.cross(u).normalized()
    polygon=[((p-center).dot(u),(p-center).dot(v)) for p in points]
    return center,u,v,normal,polygon

def distance_segment(p,a,b):
    p,a,b=Vector(p),Vector(a),Vector(b); d=b-a
    t=max(0,min(1,(p-a).dot(d)/d.length_squared)) if d.length_squared else 0
    return (p-(a+t*d)).length

def clearance(point, polygon):
    x,y=point; inside=False
    for a,b in zip(polygon,polygon[1:]+polygon[:1]):
        if (a[1]>y)!=(b[1]>y) and x < (b[0]-a[0])*(y-a[1])/(b[1]-a[1])+a[0]: inside=not inside
    if not inside: return -1
    return min(distance_segment(point,a,b) for a,b in zip(polygon,polygon[1:]+polygon[:1]))

def connector_points(polygon,radius,wall,count):
    xmin=min(p[0] for p in polygon); xmax=max(p[0] for p in polygon)
    ymin=min(p[1] for p in polygon); ymax=max(p[1] for p in polygon)
    candidates=[(0,0)]+[(xmin+(xmax-xmin)*i/30,ymin+(ymax-ymin)*j/30) for i in range(1,30) for j in range(1,30)]
    candidates=[(clearance(p,polygon),p) for p in candidates]
    candidates=sorted((c,p) for c,p in candidates if c>=radius+wall)
    if not candidates: raise AddonError('No cabe el alojamiento con la pared mínima indicada.')
    best=candidates[-1][1]
    if count==1: return [best]
    # Limit candidates while preserving the spatial spread of the feasible region.
    pts=[p for c,p in candidates]
    step=max(1,len(pts)//140); pts=pts[::step]
    pair=max(((Vector(a)-Vector(b)).length,a,b) for i,a in enumerate(pts) for b in pts[i+1:]) if len(pts)>1 else None
    if pair is None or pair[0] < 2*radius+wall:
        raise AddonError('No caben dos imanes con la separación y pared mínimas indicadas.')
    return [pair[1],pair[2]]

def new_from_bmesh(bm,name,collection,source=None):
    data=bpy.data.meshes.new(name); bm.to_mesh(data); data.update()
    obj=bpy.data.objects.new(name,data); collection.objects.link(obj)
    if source:
        for m in source.data.materials: data.materials.append(m)
    return obj

def remove_created(objects):
    for obj in reversed(objects):
        if obj.name in bpy.data.objects:
            data=obj.data; bpy.data.objects.remove(obj,do_unlink=True)
            if data and data.users==0: bpy.data.meshes.remove(data)

def solid_info(obj):
    bm=bmesh.new(); bm.from_mesh(obj.data)
    try:
        closed=bool(bm.faces) and all(e.is_manifold for e in bm.edges)
        volume=abs(bm.calc_volume(signed=True)) if closed else 0
        return closed,volume
    finally: bm.free()

def cylinder(name,center,axis,radius,depth,collection):
    axis=Vector(axis).normalized(); q=axis.to_track_quat('Z','Y'); verts=[]; n=64
    for z in [-depth/2,depth/2]:
        for i in range(n):
            a=2*math.pi*i/n
            verts.append(Vector(center)+q@Vector((radius*math.cos(a),radius*math.sin(a),z)))
    faces=[tuple(reversed(range(n))),tuple(range(n,2*n))]
    faces.extend((i,(i+1)%n,(i+1)%n+n,i+n) for i in range(n))
    data=bpy.data.meshes.new(name); data.from_pydata(verts,[],faces); data.update()
    obj=bpy.data.objects.new(name,data); collection.objects.link(obj)
    return obj

def apply_modifier(context,obj,mod):
    context.view_layer.objects.active=obj
    with context.temp_override(object=obj,active_object=obj,selected_objects=[obj],selected_editable_objects=[obj]):
        response=bpy.ops.object.modifier_apply(modifier=mod.name)
    if 'FINISHED' not in response: raise AddonError('No se pudo aplicar el modificador.')

def subtract(context,obj,cutter):
    before=solid_info(obj)[1]
    mod=obj.modifiers.new('Alojamiento','BOOLEAN'); mod.operation='DIFFERENCE'; mod.solver='EXACT'; mod.object=cutter
    apply_modifier(context,obj,mod)
    closed,after=solid_info(obj)
    if not closed or after<=0 or before-after <= max(before*1e-10,1e-18):
        raise AddonError('El alojamiento no produjo un sólido cerrado válido. El original se conserva.')

def depth_check(obj,point,direction,radius,depth,wall,mm_factor):
    bm=bmesh.new(); bm.from_mesh(obj.data)
    tree=BVHTree.FromBMesh(bm); q=direction.to_track_quat('Z','Y'); eps=.001/mm_factor
    offsets=[Vector()]+[q@Vector((radius*math.cos(i*math.pi/4),radius*math.sin(i*math.pi/4),0)) for i in range(8)]
    try:
        for off in offsets:
            loc,normal,index,distance=tree.ray_cast(point+off+direction*eps,direction)
            if loc is None or distance+eps < depth+wall:
                raise AddonError('La pieza no tiene suficiente espesor para el alojamiento y la pared mínima.')
    finally: bm.free()

def finish(context,source,objects):
    source.hide_set(True); source.hide_render=True
    for o in context.selected_objects: o.select_set(False)
    for o in objects: o.select_set(True)
    context.view_layer.objects.active=objects[0]
    source['addon_original_conservado']=True
    for obj in objects: obj['addon_source']=source.name

def restore_edit(context,source):
    context.view_layer.objects.active=source
    source.hide_set(False); source.select_set(True)
    if source.mode!='EDIT': bpy.ops.object.mode_set(mode='EDIT')

def split_connectors(context,kind,radius_mm,length_mm,tolerance_mm,wall_mm,mode='ONE',unit='SCENE'):
    source=None; created=[]; parts=[]
    scale=factor(context.scene,unit)
    radius=(radius_mm+tolerance_mm)/scale
    half_depth=(length_mm/2+tolerance_mm)/scale if kind=='DOWEL' else (length_mm+tolerance_mm)/scale
    wall=wall_mm/scale
    try:
        source,mask=active_patch(context); col=source.users_collection[0]
        bm=source_bmesh(source)
        try:
            bm.faces.ensure_lookup_table(); selected={f for f in bm.faces if mask[f.index]}
            loop=boundary_loop(bm,selected)
            center,u,v,n,polygon=frame([p.co.copy() for p in loop],scale)
        finally: bm.free()
        count=2 if mode in {'TWO','AUTO'} and kind=='MAGNET' else 1
        try: points=connector_points(polygon,radius,wall,count)
        except AddonError:
            if mode!='AUTO': raise
            points=connector_points(polygon,radius,wall,1)
        for keep_selected,label in [(False,'Base'),(True,'Pieza')]:
            bm=source_bmesh(source)
            try:
                bm.faces.ensure_lookup_table()
                bmesh.ops.delete(bm,geom=[f for f in bm.faces if bool(mask[f.index])!=keep_selected],context='FACES')
                edges=[e for e in bm.edges if e.is_boundary]
                cap=bmesh.ops.holes_fill(bm,edges=edges,sides=0)['faces']
                bmesh.ops.recalc_face_normals(bm,faces=list(bm.faces)); bm.normal_update()
                inward=-max(cap,key=lambda f:f.calc_area()).normal.copy()
                obj=new_from_bmesh(bm,source.name+'_'+label,col,source)
                created.append(obj); parts.append((obj,inward))
                if not solid_info(obj)[0]: raise AddonError('El corte no produce dos sólidos cerrados.')
            finally: bm.free()
        if parts[0][1].dot(parts[1][1])>-.99:
            raise AddonError('Las caras del corte no quedan enfrentadas.')
        for index,xy in enumerate(points,1):
            point=center+u*xy[0]+v*xy[1]
            for obj,direction in parts: depth_check(obj,point,direction,radius,half_depth,wall,scale)
            cutter=cylinder('Cortador temporal',point,n,radius,half_depth*2,col); created.append(cutter)
            for obj,direction in parts: subtract(context,obj,cutter)
            created.remove(cutter); remove_created([cutter])
        outputs=[p[0] for p in parts]
        if kind=='DOWEL':
            verts=[source.matrix_world@p.co for p in source.data.vertices]
            center_dowel=Vector((max(p.x for p in verts)+radius_mm*4/scale, min(p.y for p in verts),radius_mm/scale))
            dowel=cylinder(source.name+'_Espiga',center_dowel,Vector((0,1,0)),radius_mm/scale,length_mm/scale,col)
            created.append(dowel); outputs.append(dowel)
        finish(context,source,outputs)
        return len(points)
    except Exception:
        remove_created(created)
        if source: restore_edit(context,source)
        raise

def create_inlay(context,depth_mm,tolerance_mm,wall_mm,unit='SCENE'):
    source=None; created=[]; scale=factor(context.scene,unit)
    try:
        source,mask=active_patch(context); col=source.users_collection[0]
        whole=source_bmesh(source)
        try:
            whole.faces.ensure_lookup_table()
            tree=BVHTree.FromBMesh(whole); eps=.001/scale
            for f in whole.faces:
                if mask[f.index]:
                    loc,normal,idx,distance=tree.ray_cast(f.calc_center_median()-f.normal*eps,-f.normal)
                    if loc is None or distance < (depth_mm+tolerance_mm+wall_mm)/scale:
                        raise AddonError('El inserto atravesaría la pieza. Reduce la profundidad.')
            base=new_from_bmesh(whole,source.name+'_Base',col,source); created.append(base)
        finally: whole.free()
        patch=source_bmesh(source)
        try:
            patch.faces.ensure_lookup_table()
            bmesh.ops.delete(patch,geom=[f for f in patch.faces if not mask[f.index]],context='FACES')
            boundary_loop(patch)
            insert=new_from_bmesh(patch,source.name+'_Inserto',col,source); created.append(insert)
        finally: patch.free()
        solid=insert.modifiers.new('Grosor interior','SOLIDIFY'); solid.thickness=depth_mm/scale; solid.offset=-1; solid.use_even_offset=True
        apply_modifier(context,insert,solid)
        if not solid_info(insert)[0]: raise AddonError('El parche no admite un grosor cerrado válido.')
        cutter=insert.copy(); cutter.data=insert.data.copy(); col.objects.link(cutter); created.append(cutter)
        # Offset the solid's surface along its normals: reliable for regular
        # patches; clearance around sharp/concave corners remains approximate.
        disp=cutter.modifiers.new('Holgura normal','DISPLACE'); disp.strength=tolerance_mm/scale; disp.mid_level=0; disp.direction='NORMAL'
        apply_modifier(context,cutter,disp)
        subtract(context,base,cutter)
        created.remove(cutter); remove_created([cutter])
        finish(context,source,[base,insert])
    except Exception:
        remove_created(created)
        if source: restore_edit(context,source)
        raise

def register_classes(classes, prop, settings):
    for cls in classes: bpy.utils.register_class(cls)
    setattr(bpy.types.Scene,prop,bpy.props.PointerProperty(type=settings))

def unregister_classes(classes, prop):
    if hasattr(bpy.types.Scene,prop): delattr(bpy.types.Scene,prop)
    for cls in reversed(classes): bpy.utils.unregister_class(cls)

UNIT_ITEMS=[('SCENE','Escala de la escena','Respeta los metros por unidad de la escena'),('MM','1 unidad = 1 mm','Para STL importados con coordenadas numéricas en milímetros'),('M','1 unidad = 1 m','Coordenadas expresadas en metros')]
SCOPE_ITEMS=[('SELECTED','Seleccionadas','Solo las mallas seleccionadas'),('VISIBLE','Visibles','Todas las mallas visibles de la vista actual')]
