import template from '../data/rig-template.json';
export type RigPoint = [number, number, number];
export type RigSettings = { version: string; yaw: number; weightMode: 'distance' | 'heat'; points: Record<string, RigPoint> };
export const RIG_VERSION = template.version;
export const RIG_BONES = template.bones;
export const JOINT_LABELS: Record<string, string> = { hips: '骨盆', spine: '腰部', chest: '胸部', neck: '颈根', head: '头部', headTop: '头骨末端', shoulder: '肩膀', elbow: '肘部', wrist: '手腕', hand: '手指方向', hip: '髋关节', knee: '膝盖', ankle: '脚踝', toe: '脚尖' };
export function jointLabel(key: string) { const [name, side] = key.split('.'); return `${side === 'L' ? '左' : side === 'R' ? '右' : ''}${JOINT_LABELS[name] || name}`; }
export function clipLabel(name: string) { return ({ rig_test_head: '转头 · 变形测试', rig_test_arms: '摆臂 · 变形测试', rig_test_legs: '屈膝 · 变形测试' } as Record<string, string>)[name] || name; }
export function defaultRig(): RigSettings { return { version: RIG_VERSION, yaw: 0, weightMode: 'heat', points: structuredClone(template.points) as unknown as Record<string, RigPoint> }; }
export type RigJob = { id: string; state: 'running' | 'done' | 'failed'; createdAt: string; fileName: string; message: string; report: { bones: number; meshes: number; vertices: number; unweighted: number; weightMode: string; clips: string[]; warnings: string[] } | null; modelUrl: string | null; blendUrl: string | null; reportUrl: string | null };
