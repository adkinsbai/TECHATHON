"""MORI static biped rig. Run using Blender 4.5 LTS --background --python this_file -- job_folder.
Coordinates in rig.json: height-relative, +Y up, +Z forward, +X character left.
This creates a starting deform rig, not a production animation or automatic anatomical fit.
"""
import bpy
import bmesh
import json
import math
import sys
import shutil
from pathlib import Path
from mathutils import Vector, Matrix


def run(folder):
    settings = json.loads((folder / 'rig.json').read_text(encoding='utf-8'))
    report = dict(bones=0, meshes=0, vertices=0, unweighted=0, clips=[], warnings=[
        '关节由用户定位；自动权重仍需人工检查，尤其是衣服、耳朵和手持道具。',
        '测试动画只用于检查变形，不代表已完成趣味互动动作；此版本没有手指、面部、耳尾专用骨。'
    ], weightMode=settings['weightMode'], verifiedExport=False, rigVersion=settings['version'], coordinates='GLB: +Y up, +Z forward; Blender: +Z up, -Y forward')
    try:
        bpy.ops.object.select_all(action='SELECT')
        bpy.ops.object.delete(use_global=False)
        bpy.ops.import_scene.gltf(filepath=str(folder / 'input.glb'))
        meshes = [o for o in bpy.context.scene.objects if o.type == 'MESH']
        if not meshes or any(o.data.shape_keys for o in meshes):
            raise RuntimeError('需要不含形变的静态网格。')
        # Bake imported world transforms, rotate about glTF Y, then normalize to 2.6m.
        turn = Matrix.Rotation(math.radians(settings['yaw']), 4, 'Z')
        transformed = {o: [turn @ (o.matrix_world @ v.co) for v in o.data.vertices] for o in meshes}
        vertices = [v for points in transformed.values() for v in points]
        minimum = Vector(tuple(min(v[i] for v in vertices) for i in range(3)))
        maximum = Vector(tuple(max(v[i] for v in vertices) for i in range(3)))
        height = maximum.z - minimum.z
        if height < 0.00001:
            raise RuntimeError('模型没有有效高度。')
        center = Vector(((minimum.x + maximum.x) / 2, (minimum.y + maximum.y) / 2, minimum.z))
        for obj in meshes:
            if obj.data.users > 1:
                obj.data = obj.data.copy()
            obj.parent = None
            obj.matrix_world = Matrix.Identity(4)
            for vertex, point in zip(obj.data.vertices, transformed[obj]):
                vertex.co = (point - center) * (2.6 / height)
            obj.data.update()
        # A single object makes disconnected eyes/clothes participate in one heat solve;
        # Blender preserves material slots and UVs when joining.
        bpy.ops.object.select_all(action='DESELECT')
        for obj in meshes:
            obj.select_set(True)
        bpy.context.view_layer.objects.active = meshes[0]
        if len(meshes) > 1:
            bpy.ops.object.join()
        mesh = bpy.context.object
        mesh.name = 'CharacterMesh'
        mesh.vertex_groups.clear()
        if settings['weightMode'] == 'heat':
            # GLB splits vertices at UV/normal seams. Weld coincident positions for
            # the heat solver; loop UVs/material assignments remain on the faces.
            before = len(mesh.data.vertices)
            geometry = bmesh.new()
            geometry.from_mesh(mesh.data)
            bmesh.ops.remove_doubles(geometry, verts=list(geometry.verts), dist=0.000026)
            geometry.to_mesh(mesh.data)
            geometry.free()
            mesh.data.update()
            report['warnings'].append(f'骨热前焊接重合顶点：{before} → {len(mesh.data.vertices)}；请检查接触面和材质接缝。')
        for modifier in list(mesh.modifiers):
            if modifier.type == 'ARMATURE':
                mesh.modifiers.remove(modifier)
        bpy.ops.object.select_all(action='DESELECT')
        armature = bpy.data.armatures.new('MORI_Biped')
        rig = bpy.data.objects.new('MORI_Rig', armature)
        bpy.context.collection.objects.link(rig)
        rig.show_in_front = True
        rig['rigVersion'] = settings['version']
        rig['reviewStatus'] = 'automatic_weights_require_visual_review'
        rig.select_set(True)
        bpy.context.view_layer.objects.active = rig
        bpy.ops.object.mode_set(mode='EDIT')

        def point(key):
            x, y, z = settings['points'][key]
            return Vector((x * 2.6, -z * 2.6, y * 2.6))

        for name, start, end, parent in settings['bones']:
            bone = armature.edit_bones.new(name)
            bone.head = point(start)
            bone.tail = point(end)
            if parent:
                bone.parent = armature.edit_bones[parent]
            bone.use_connect = False
        bpy.ops.object.mode_set(mode='OBJECT')
        mesh.select_set(True)
        if settings['weightMode'] == 'heat':
            bpy.ops.object.parent_set(type='ARMATURE_AUTO')
        else:
            bpy.ops.object.parent_set(type='ARMATURE_NAME')
            # Explicit distance mode: smooth inverse-distance weights to the four closest
            # bone segments. This is a real editable skin, but cannot infer anatomy,
            # clothing or props, so the report always requires weight-paint review.
            segments = [(bone.name, bone.head_local.copy(), bone.tail_local.copy()) for bone in armature.bones]
            groups = {name: mesh.vertex_groups.get(name) or mesh.vertex_groups.new(name=name) for name, _, _ in segments}
            for vertex in mesh.data.vertices:
                distances = []
                for name, start, end in segments:
                    direction = end - start
                    t = max(0, min(1, (vertex.co - start).dot(direction) / direction.length_squared))
                    distance = (vertex.co - (start + direction * t)).length
                    distances.append((distance, name))
                nearest = sorted(distances)[:4]
                weights = [(name, 1 / max(distance, 0.015) ** 4) for distance, name in nearest]
                total = sum(weight for _, weight in weights)
                for name, weight in weights:
                    groups[name].add([vertex.index], weight / total, 'REPLACE')
            report['warnings'].insert(0, '使用平滑距离初始蒙皮：按骨段距离分配权重，不识别人体或衣物语义；跨肢体影响、肩髋和道具必须人工修正。')
        report['bones'] = len(armature.bones)
        report['meshes'] = 1
        report['vertices'] = len(mesh.data.vertices)
        deform_indices = {g.index for g in mesh.vertex_groups if g.name in armature.bones}
        for vertex in mesh.data.vertices:
            if sum(g.weight for g in vertex.groups if g.group in deform_indices) < 0.00001:
                report['unweighted'] += 1
        # Keep no more than four normalized influences per vertex for desktop GLB players.
        bpy.context.view_layer.objects.active = mesh
        bpy.ops.object.vertex_group_limit_total(group_select_mode='ALL', limit=4)
        bpy.ops.object.vertex_group_normalize_all(group_select_mode='ALL', lock_active=False)
        scene = bpy.context.scene
        scene.render.fps = 24
        scene.frame_start = 1
        scene.frame_end = 49
        rig.animation_data_create()
        tests = {
            'rig_test_head': [('head', (0.15, 0, 0.13))],
            'rig_test_arms': [('upper_arm.L', (0, 0.22, -0.18)), ('forearm.L', (0.30, 0, 0)), ('upper_arm.R', (0, -0.22, 0.18))],
            'rig_test_legs': [('thigh.L', (0.16, 0, 0)), ('shin.L', (-0.25, 0, 0)), ('thigh.R', (-0.10, 0, 0))]
        }
        for name, rotations in tests.items():
            action = bpy.data.actions.new(name)
            rig.animation_data.action = action
            for bone in rig.pose.bones:
                bone.rotation_mode = 'XYZ'
                bone.rotation_euler = (0, 0, 0)
            for frame, factor in [(1, 0), (13, 1), (25, 0), (37, -0.5), (49, 0)]:
                for bone_name, rotation in rotations:
                    bone = rig.pose.bones[bone_name]
                    bone.rotation_euler = tuple(n * factor for n in rotation)
                    bone.keyframe_insert(data_path='rotation_euler', frame=frame, group=bone_name)
            # Each track includes rest keys for every joint to avoid retaining a previous test's pose.
            for bone in rig.pose.bones:
                if bone.name not in {r[0] for r in rotations}:
                    for frame in (1, 49):
                        bone.rotation_euler = (0, 0, 0)
                        bone.keyframe_insert(data_path='rotation_euler', frame=frame, group=bone.name)
            track = rig.animation_data.nla_tracks.new()
            track.name = name
            track.strips.new(name, 1, action)
            rig.animation_data.action = None
            report['clips'].append(name)
        scene.frame_set(1)
        # Exclude imported empty nodes/cameras/lights from the editing project and output.
        for obj in list(scene.objects):
            if obj not in (mesh, rig):
                bpy.data.objects.remove(obj, do_unlink=True)
        bpy.ops.object.select_all(action='DESELECT')
        rig.select_set(True)
        mesh.select_set(True)
        bpy.context.view_layer.objects.active = rig
        bpy.ops.wm.save_as_mainfile(filepath=str(folder / 'character.blend'))
        if report['unweighted']:
            raise RuntimeError(f"有 {report['unweighted']} 个顶点未绑定；请在 Blender 中修权重。")
        bpy.ops.export_scene.gltf(filepath=str(folder / 'character-rigged.glb'), export_format='GLB',
            use_selection=True, export_animations=True, export_animation_mode='NLA_TRACKS',
            export_skins=True, export_influence_nb=4, export_extras=True)
        # Reimport the file to verify real skin data and animations survived export.
        bpy.ops.object.select_all(action='SELECT')
        bpy.ops.object.delete(use_global=False)
        bpy.ops.import_scene.gltf(filepath=str(folder / 'character-rigged.glb'))
        # glTF importer also creates an unskinned Icosphere widget for bone display.
        # Inspect our exported character, excluding that Blender-only helper object.
        imported_meshes = [o for o in bpy.context.scene.objects if o.type == 'MESH' and o.name == 'CharacterMesh']
        imported_rigs = [o for o in bpy.context.scene.objects if o.type == 'ARMATURE']
        report['verifiedExport'] = bool(imported_rigs and imported_meshes and all(
            any(m.type == 'ARMATURE' for m in o.modifiers) for o in imported_meshes))
        if not report['verifiedExport']:
            raise RuntimeError('GLB 导出后的骨架检查未通过。')
    except Exception as error:
        report['warnings'].append(str(error))
        raise
    finally:
        (folder / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')


def inspect_existing(folder):
    """Keep the provider's skeleton and weights; never run the template binder."""
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)
    bpy.ops.import_scene.gltf(filepath=str(folder / 'input.glb'))
    rigs = [o for o in bpy.context.scene.objects if o.type == 'ARMATURE']
    meshes = [o for o in bpy.context.scene.objects if o.type == 'MESH' and any(m.type == 'ARMATURE' and m.object in rigs for m in o.modifiers)]
    report = dict(bones=sum(len(r.data.bones) for r in rigs), meshes=len(meshes), vertices=sum(len(m.data.vertices) for m in meshes), unweighted=0, clips=[], weightMode='external-preserved', verifiedExport=False, warnings=['保留导入骨架、权重、材质和已有动作；没有重绑，也没有补造测试动画。', '请在 Blender 姿态模式检查关节、衣物与道具的变形。'])
    try:
        for mesh in meshes:
            names = {b.name for modifier in mesh.modifiers if modifier.type == 'ARMATURE' and modifier.object for b in modifier.object.data.bones}
            indices = {g.index for g in mesh.vertex_groups if g.name in names}
            report['unweighted'] += sum(sum(g.weight for g in v.groups if g.group in indices) < 0.00001 for v in mesh.data.vertices)
        document = json.loads((folder / 'input.glb').read_bytes()[20:20 + int.from_bytes((folder / 'input.glb').read_bytes()[12:16], 'little')])
        report['clips'] = [a.get('name', 'unnamed') for a in document.get('animations', [])]
        bpy.ops.file.pack_all()
        bpy.context.scene.frame_set(1)
        bpy.ops.wm.save_as_mainfile(filepath=str(folder / 'character.blend'))
        shutil.copyfile(folder / 'input.glb', folder / 'character-rigged.glb')
        report['verifiedExport'] = bool(rigs and meshes and report['bones'])
        if not report['verifiedExport']:
            raise RuntimeError('没有检测到有效的骨架与蒙皮。')
    finally:
        (folder / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    folder = Path(sys.argv[sys.argv.index('--') + 1]).resolve()
    settings = json.loads((folder / 'rig.json').read_text(encoding='utf-8'))
    (inspect_existing if settings.get('operation') == 'inspect' else run)(folder)
