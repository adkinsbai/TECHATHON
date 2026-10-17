import bpy, json
from pathlib import Path
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete(use_global=False)
cfg=json.loads(Path('src/data/rig-template.json').read_text())
points=cfg['points']
keys=list(points)
verts=[(points[k][0]*2.6,-points[k][2]*2.6,points[k][1]*2.6) for k in keys]
edges=[(keys.index(a),keys.index(b)) for _,a,b,_ in cfg['bones']]
edges.extend([(keys.index('hips'),keys.index('hip.L')),(keys.index('hips'),keys.index('hip.R'))])
mesh=bpy.data.meshes.new('TestBiped')
mesh.from_pydata(verts,edges,[])
obj=bpy.data.objects.new('TestBiped',mesh)
bpy.context.collection.objects.link(obj)
bpy.context.view_layer.objects.active=obj
obj.select_set(True)
mod=obj.modifiers.new('Skin','SKIN')
for k,v in zip(keys,mesh.skin_vertices[0].data):
    r=.06 if '.' in k else .14
    v.radius=(r,r)
mesh.skin_vertices[0].data[keys.index('hips')].use_root=True
bpy.ops.object.modifier_apply(modifier=mod.name)
sub=obj.modifiers.new('Smooth','SUBSURF')
sub.levels=2
bpy.ops.object.modifier_apply(modifier=sub.name)
bpy.ops.export_scene.gltf(filepath=str(Path('.local/qa/static-biped.glb').resolve()),export_format='GLB',use_selection=True)
