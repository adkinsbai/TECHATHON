export type ActionName = 'idle' | 'greet' | 'enjoy_head_pat' | 'hug' | 'react_to_shake' | 'listen';
export type Region = 'head' | 'body' | 'left_hand' | 'right_hand';
export type Interaction = { type: 'touch' | 'motion' | 'speech'; region: Region; gesture: string; intensity: number; source: 'simulator' | 'physical' | 'chat'; timestamp: string };
export type Appearance = { body: string; accent: string; eyes: string; scale: number };
export type AssetInfo = {
  source: 'demo' | 'import' | 'rodin'; fileName: string; meshes: number; triangles: number;
  bones: { name: string; parent: string | null }[]; skinnedMeshes: number;
  clips: { name: string; duration: number }[]; morphTargets: string[];
  materials: string[]; regions: Region[]; size: number;
};
export type MaterialInfo = { id: string; name: string; color: string };
export type Mapping = Record<ActionName, string>;
export type CharacterProject = { inputVersion: 2; name: string; description: string; referenceStyle?: 'preserve' | 'plush' | 'clay' | 'toon'; personality: string; appearance: Appearance; mapping: Mapping; rigVersion: string; notes: string; materialColors: Record<string, string> };
export type EventRecord = { event: Interaction; action: ActionName; result: string; played: boolean };
export type GenerationInput = { kind: 'text' | 'image' | 'mixed'; prompt: string; images: { name: string; size: number; type: string }[]; taPose: boolean; preparation?: { referenceId: string; brief: string; imageSource: string } };
export type ReferenceJob = { id: string; state: 'pending' | 'running' | 'done' | 'failed'; prompt: string; style?: 'preserve' | 'plush' | 'clay' | 'toon'; inputSignature: string; source: 'openai' | 'manual'; model: string | null; createdAt: string; message: string; imageUrl: string | null };
export type RodinJob = { id: string; state: 'pending' | 'running' | 'done' | 'failed'; createdAt: string; prompt: string; input?: GenerationInput; stage: string; message?: string; retryAfter: number; modelUrl: string | null };
export const ACTIONS: { id: ActionName; label: string; short: string; duration: number; loop: boolean; description: string }[] = [
  { id: 'idle', label: '呼吸待机', short: '待机', duration: 3, loop: true, description: '轻轻呼吸，偶尔眨眼' },
  { id: 'greet', label: '挥手打招呼', short: '打招呼', duration: 2.4, loop: false, description: '向你挥挥手，身体轻晃' },
  { id: 'enjoy_head_pat', label: '享受摸头', short: '摸摸头', duration: 2.8, loop: false, description: '歪头靠近，眯起眼睛' },
  { id: 'hug', label: '温暖拥抱', short: '抱一抱', duration: 3, loop: false, description: '张开双手，回应你的拥抱' },
  { id: 'react_to_shake', label: '晕乎乎', short: '摇一摇', duration: 2.6, loop: false, description: '跟着轻晃，慢慢恢复平衡' },
  { id: 'listen', label: '认真倾听', short: '听你说', duration: 3.2, loop: false, description: '微微前倾，认真听你说话' }
];
export const DEFAULT_PROJECT: CharacterProject = {
  inputVersion: 2, name: '小森', description: '',
  personality: '温柔 · 好奇 · 有一点害羞', appearance: { body: '#91bcb1', accent: '#efdeb5', eyes: '#263a36', scale: 1 },
  mapping: { idle: '', greet: '', enjoy_head_pat: '', hug: '', react_to_shake: '', listen: '' },
  rigVersion: 'mori-demo-v1', notes: '', materialColors: {}
};
