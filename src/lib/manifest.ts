import { ACTIONS } from '../types';
import type { AssetInfo, CharacterProject, EventRecord } from '../types';

export function buildManifest(project: CharacterProject, asset: AssetInfo, events: EventRecord[]) {
  return {
    schemaVersion: '1.0.0', exportedAt: new Date().toISOString(),
    character: { name: project.name, description: project.description, personality: project.personality },
    asset: { file: 'character.glb', originalFileName: asset.fileName, source: asset.source,
      meshes: asset.meshes, triangles: asset.triangles, bytes: asset.size },
    // All models are exported after normalization, so this describes the exported asset, not the source.
    coordinates: { handedness: 'right', up: '+Y', forward: '+Z', units: 'meter', normalizedHeight: 2.6 * (asset.source === 'demo' ? project.appearance.scale : 1), origin: 'ground-center', sourceOrientationVerified: asset.source === 'demo' },
    rig: { version: project.rigVersion, type: asset.source === 'demo' ? 'procedural-node-hierarchy' : asset.skinnedMeshes > 0 ? 'skeletal' : 'static',
      bones: asset.bones, skinnedMeshes: asset.skinnedMeshes, restPose: asset.source === 'demo' ? 'custom' : 'unverified' },
    capabilities: { morphTargets: asset.morphTargets, materialSlots: asset.materials, interactionRegions: asset.regions,
      automaticRigging: false, animationRetargeting: false },
    appearance: asset.source === 'demo' ? project.appearance : { materialColors: project.materialColors },
    actions: ACTIONS.map(action => ({ id: action.id, label: action.label, loop: action.loop,
      clip: asset.source === 'demo' ? null : asset.clips.find(c => c.name === project.mapping[action.id])?.name || null,
      proceduralDemo: asset.source === 'demo', available: asset.source === 'demo' || asset.clips.some(c => c.name === project.mapping[action.id]),
      durationSeconds: asset.source === 'demo' ? action.duration : asset.clips.find(c => c.name === project.mapping[action.id])?.duration ?? null })),
    animationClips: asset.clips, interactionExamples: events.slice(0, 8).map(e => e.event),
    limitations: asset.source === 'demo'
      ? ['示范角色使用节点程序动画，不含蒙皮骨架；动作实现见 src/engine/demo.ts。', '导出的 GLB 只包含静态外观与节点层级，不含程序动画。']
      : ['导入不会自动绑定骨骼或重定向动作。', '请在 Blender 中确认默认姿态、朝向、蒙皮变形与运动限制。'],
    notes: project.notes
  };
}
