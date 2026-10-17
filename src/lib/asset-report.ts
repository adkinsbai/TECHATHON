import type { AssetInfo, CharacterProject } from '../types';
import { readReferenceStyle } from './reference-style';
export function buildAssetReport(project: CharacterProject, asset: AssetInfo) {
  return { schemaVersion: 'mori-asset-lab-1', exportedAt: new Date().toISOString(),
    asset: { file: 'character.glb', source: asset.source, originalFileName: asset.fileName, triangles: asset.triangles, meshes: asset.meshes, bytes: asset.size },
    rig: { version: project.rigVersion, type: asset.skinnedMeshes ? 'skeletal' : 'static', bones: asset.bones, skinnedMeshes: asset.skinnedMeshes, visualReview: 'required' },
    animationClips: asset.clips, morphTargets: asset.morphTargets, materials: asset.materials,
    coordinates: { up: '+Y', handedness: 'right', normalizedHeight: 2.6 * (asset.source === 'demo' ? project.appearance.scale : 1), forward: 'requires-visual-check' },
    editorDraft: { name: project.name, description: project.description, referenceStyle: readReferenceStyle(project.referenceStyle), note: '当前编辑草稿，不代表已证明此模型由该描述或风格生成。' },
    limitations: [asset.source === 'demo' ? '静态占位示例，非生成结果。' : '数量来自真实模型数据，视觉质量仍需检查。', '零未绑定顶点不代表权重正确。', '当前仅处理资产生成与骨骼调试。'] };
}
