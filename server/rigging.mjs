import { mkdir, readFile, writeFile, readdir, access } from 'node:fs/promises';
import path from 'node:path';
import { randomUUID } from 'node:crypto';
import { spawn } from 'node:child_process';
import template from '../src/data/rig-template.json' with { type: 'json' };
import { ServiceError } from './rodin.mjs';

export function validateRigSettings(input) {
  if (!input || input.version !== template.version || ![0, 90, 180, 270].includes(input.yaw) || !['distance', 'heat'].includes(input.weightMode)) throw new ServiceError('骨架版本、朝向或蒙皮方式无效。', 400);
  const points = {};
  for (const key of Object.keys(template.points)) {
    const p = input.points?.[key];
    if (!Array.isArray(p) || p.length !== 3 || p.some(n => typeof n !== 'number' || !Number.isFinite(n)) || Math.abs(p[0]) > 1 || p[1] < 0 || p[1] > 1.2 || Math.abs(p[2]) > 1) throw new ServiceError(`关节 ${key} 的坐标无效。`, 400);
    points[key] = p;
  }
  for (const [, head, tail] of template.bones) if (Math.hypot(...points[head].map((n, i) => n - points[tail][i])) < .005) throw new ServiceError('相邻关节过近，请拉开骨骼两端。', 400);
  if (!(points.hips[1] < points.spine[1] && points.spine[1] < points.chest[1] && points.chest[1] < points.neck[1] && points.neck[1] < points.head[1] && points.head[1] < points.headTop[1])) throw new ServiceError('躯干关节应从骨盆到头顶逐级升高。', 400);
  return { version: template.version, yaw: input.yaw, weightMode: input.weightMode, points, bones: template.bones };
}
export function validateRigGLB(bytes) {
  if (bytes.length < 20 || bytes.length > 200 * 1024 * 1024 || bytes.readUInt32LE(0) !== 0x46546c67 || bytes.readUInt32LE(4) !== 2 || bytes.readUInt32LE(8) !== bytes.length || bytes.readUInt32LE(16) !== 0x4e4f534a) throw new ServiceError('请提交不超过 200 MB 的有效 GLB。', 400);
  let doc; try { doc = JSON.parse(bytes.subarray(20, 20 + bytes.readUInt32LE(12)).toString()); } catch { throw new ServiceError('模型结构无效。', 400); }
  if (!doc.meshes?.length) throw new ServiceError('模型没有网格。', 400);
  if (doc.skins?.length || doc.animations?.length || doc.meshes.some(m => m.primitives?.some(p => p.targets?.length))) throw new ServiceError('此模型已有骨架、动画或形变，请在 Blender 中保留并编辑；本流程仅绑定静态模型。', 400);
  if ([...(doc.buffers || []), ...(doc.images || [])].some(r => r.uri && !r.uri.startsWith('data:'))) throw new ServiceError('请使用包含贴图的单文件 GLB。', 400);
  return doc;
}
export async function findBlender(root, configured = process.env.BLENDER_PATH) {
  const candidates = configured ? [configured] : [];
  for (const directory of [path.join(root, '.local/tools'), 'C:/Program Files/Blender Foundation']) {
    for (const name of await readdir(directory).catch(() => [])) if (/blender/i.test(name)) candidates.push(path.join(directory, name, process.platform === 'win32' ? 'blender.exe' : 'blender'));
  }
  for (const file of candidates) { try { await access(file); return file; } catch {} }
  return null;
}
export class RiggingService {
  constructor({ directory, blender, script, runner = spawn }) { Object.assign(this, { directory, blender, script, runner }); this.jobs = new Map(); this.tasks = new Map(); }
  async initialize() {
    await mkdir(this.directory, { recursive: true });
    for (const id of await readdir(this.directory)) if (/^[a-f0-9-]{36}$/.test(id)) {
      try { const job = JSON.parse(await readFile(path.join(this.directory, id, 'job.json'), 'utf8')); if (job.state === 'running') { job.state = 'failed'; job.message = '服务在绑定过程中重启，请重新提交。'; await this.save(job); } this.jobs.set(id, job); } catch {}
    }
  }
  async save(job) { await writeFile(path.join(this.directory, job.id, 'job.json'), JSON.stringify(job, null, 2)); }
  publicJob(job) { return { ...job, modelUrl: job.state === 'done' ? `/api/rigs/${job.id}/model` : null, blendUrl: job.hasBlend ? `/api/rigs/${job.id}/blend` : null, reportUrl: job.report ? `/api/rigs/${job.id}/report` : null }; }
  get(id) { const job = this.jobs.get(id); if (!job) throw new ServiceError('绑定记录不存在。', 404); return this.publicJob(job); }
  async create(bytes, input, fileName = 'character.glb') {
    validateRigGLB(bytes); const settings = validateRigSettings(input);
    return this.start(bytes, settings, fileName, 'bind');
  }
  async createEditable(bytes, fileName = 'tripo-rigged.glb') {
    inspectSkinnedGLB(bytes);
    return this.start(bytes, { operation: 'inspect', version: 'external-rig' }, fileName, 'inspect');
  }
  async start(bytes, settings, fileName, operation) {
    if (!this.blender) throw new ServiceError('尚未找到 Blender，请配置 BLENDER_PATH 并重启服务。', 503);
    if (this.creating || [...this.jobs.values()].some(j => j.state === 'running')) throw new ServiceError('已有绑定任务正在运行，请等待完成。', 409);
    const job = { id: randomUUID(), operation, state: 'running', createdAt: new Date().toISOString(), fileName: String(fileName).slice(0, 120), message: operation === 'inspect' ? 'Blender 正在保留原骨架、检查蒙皮并创建可编辑工程…' : 'Blender 正在创建骨架、计算自动权重并导出…', report: null, hasBlend: false };
    this.creating = true;
    try {
      const folder = path.join(this.directory, job.id); await mkdir(folder);
      await writeFile(path.join(folder, 'input.glb'), bytes); await writeFile(path.join(folder, 'rig.json'), JSON.stringify(settings));
      this.jobs.set(job.id, job); await this.save(job);
      this.tasks.set(job.id, this.run(job).finally(() => this.tasks.delete(job.id)));
      return this.publicJob(job);
    } finally { this.creating = false; }
  }
  async run(job) {
    const folder = path.join(this.directory, job.id); let log = '';
    try {
      await new Promise((resolve, reject) => {
        const child = this.runner(this.blender, ['--background', '--factory-startup', '--disable-autoexec', '--threads', '2', '--python-exit-code', '1', '--python', this.script, '--', folder], { windowsHide: true, shell: false, env: { ...process.env, RODIN_API_KEY: '', OPENAI_API_KEY: '', TRIPO_API_KEY: '' } });
        const timer = setTimeout(() => { child.kill(); reject(new Error('绑定超时，请简化模型后重试。')); }, 10 * 60 * 1000);
        for (const stream of [child.stdout, child.stderr]) stream?.on('data', chunk => { log = (log + chunk.toString()).slice(-150000); });
        child.once('error', error => { clearTimeout(timer); reject(error); });
        child.once('close', code => { clearTimeout(timer); code === 0 ? resolve() : reject(new Error('Blender 绑定未完成，请查看报告或下载工程修正。')); });
      });
      const report = JSON.parse(await readFile(path.join(folder, 'report.json'), 'utf8')); job.report = report;
      if (!report.bones || !report.meshes || report.unweighted || !report.verifiedExport) throw new Error('绑定检查未通过，请下载 Blender 工程修正权重。');
      validateRigOutput(await readFile(path.join(folder, 'character-rigged.glb')), job.operation === 'inspect');
      job.state = 'done'; job.message = job.operation === 'inspect' ? '已保留原骨架与蒙皮，创建 Blender 工程。请检查关节和权重。' : report.weightMode === 'distance' ? '已生成初始距离蒙皮与测试动作。需在 Blender 中检查并修权重。' : '骨热蒙皮与测试动作已生成。请预览关节变形后交付。';
    } catch (error) { job.state = 'failed'; job.message = error.message.startsWith('spawn') ? 'Blender 无法启动，请检查 BLENDER_PATH。' : error.message; }
    try { job.report = JSON.parse(await readFile(path.join(folder, 'report.json'), 'utf8')); } catch {}
    job.hasBlend = await access(path.join(folder, 'character.blend')).then(() => true, () => false);
    await writeFile(path.join(folder, 'blender.log'), log); await this.save(job);
  }
  async file(id, kind) {
    const job = this.get(id); const names = { model: ['character-rigged.glb', 'model/gltf-binary'], blend: ['character.blend', 'application/octet-stream'], report: ['report.json', 'application/json'] };
    if (!names[kind] || !(kind === 'model' ? job.modelUrl : kind === 'blend' ? job.blendUrl : job.reportUrl)) throw new ServiceError('文件尚未准备好。', 404);
    return { bytes: await readFile(path.join(this.directory, id, names[kind][0])), name: names[kind][0], mime: names[kind][1] };
  }
}
export function inspectSkinnedGLB(bytes) {
  let document;
  try {
    if (bytes.length < 20 || bytes.length > 200 * 1024 * 1024 || bytes.readUInt32LE(0) !== 0x46546c67 || bytes.readUInt32LE(4) !== 2 || bytes.readUInt32LE(8) !== bytes.length || bytes.readUInt32LE(16) !== 0x4e4f534a) throw new Error();
    document = JSON.parse(bytes.subarray(20, 20 + bytes.readUInt32LE(12)).toString());
    if (!document.skins?.length || !document.nodes?.some(n => n.skin !== undefined) || [...(document.buffers || []), ...(document.images || [])].some(r => r.uri && !r.uri.startsWith('data:'))) throw new Error();
    for (const node of document.nodes.filter(n => n.skin !== undefined)) {
      if (!document.skins[node.skin]?.joints?.length || !document.meshes?.[node.mesh]?.primitives?.length || document.meshes[node.mesh].primitives.some(p => p.attributes?.JOINTS_0 === undefined || p.attributes?.WEIGHTS_0 === undefined)) throw new Error();
    }
  } catch { throw new ServiceError('模型缺少有效骨架、蒙皮属性，或不是嵌入式 GLB。', 400); }
  return document;
}
export function validateRigOutput(bytes, allowNoAnimation = false) {
  const document = inspectSkinnedGLB(bytes);
  if (!allowNoAnimation && !document.animations?.length) throw new Error('导出文件缺少测试动画。');
  return document;
}
