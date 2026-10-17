import { randomUUID } from 'node:crypto';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { ServiceError } from './rodin.mjs';
import { validateRigGLB, inspectSkinnedGLB } from './rigging.mjs';

const BASE = 'https://openapi.tripo3d.ai/v3';
export const RIG_TYPES = ['biped', 'quadruped', 'hexapod', 'octopod', 'avian', 'serpentine', 'aquatic', 'others'];
const activeStates = ['uploading', 'submitting-check', 'checking', 'submitting-rig', 'rigging', 'downloading'];
export class TripoService {
  constructor({ key = '', directory, fetcher = fetch, download = fetch }) { Object.assign(this, { key, directory, fetcher, download }); this.jobs = new Map(); this.tasks = new Map(); this.polls = new Map(); }
  async initialize() {
    await mkdir(this.directory, { recursive: true });
    try { for (const job of JSON.parse(await readFile(path.join(this.directory, 'jobs.json'), 'utf8'))) {
      if (['uploading', 'submitting-check', 'submitting-rig'].includes(job.state)) { job.state = 'failed'; job.message = '服务在提交过程中重启，结果未知。请先检查 Tripo 任务记录，勿重复扣费。'; }
      this.jobs.set(job.id, job);
    } } catch (e) { if (e.code !== 'ENOENT') throw new Error('Tripo 记录无法读取，请保留 jobs.json 后检查。'); }
    await this.persist();
  }
  persist() { const data = JSON.stringify([...this.jobs.values()], null, 2); this.writing = (this.writing || Promise.resolve()).catch(() => {}).then(() => writeFile(path.join(this.directory, 'jobs.json'), data, { mode: 0o600 })); return this.writing; }
  publicJob(j) { return { id: j.id, state: j.state, createdAt: j.createdAt, fileName: j.fileName, message: j.message, progress: j.progress || 0, riggable: j.riggable ?? null, recommendedType: j.recommendedType || null, rigType: j.rigType || null, modelVersion: j.modelVersion || null, credits: j.credits || {}, report: j.report || null, retryAfter: Math.max(1, Math.ceil(((j.nextPoll || 0) - Date.now()) / 1000)), modelUrl: j.state === 'done' ? `/api/auto-rigs/${j.id}/model` : null, blenderJobId: j.blenderJobId || null }; }
  job(id) { const j = this.jobs.get(id); if (!j) throw new ServiceError('未找到 Tripo 任务。', 404); return j; }
  async request(endpoint, body, method = 'POST') {
    const headers = { Authorization: `Bearer ${this.key}` }; if (body && !(body instanceof FormData)) headers['Content-Type'] = 'application/json';
    let response;
    try { response = await this.fetcher(BASE + endpoint, { method, headers, ...(body ? { body: body instanceof FormData ? body : JSON.stringify(body) } : {}), redirect: 'error', signal: AbortSignal.timeout(180000) }); }
    catch { throw new ServiceError(method === 'POST' ? 'Tripo 提交结果未知，请先检查服务商任务记录，避免重复提交。' : 'Tripo 查询暂不可用，稍后可继续查询。'); }
    if (!response.ok) { const seconds = Number(response.headers.get('retry-after')); const retryAfter = seconds > 0 ? seconds : Math.max(5, (Date.parse(response.headers.get('retry-after')) - Date.now()) / 1000 || 10); throw new ServiceError(response.status === 401 ? 'Tripo 密钥无效，请检查本机配置。' : response.status === 403 ? 'Tripo 拒绝此操作（HTTP 403），请检查 API 账户权限与额度。' : response.status === 429 ? 'Tripo 请求限流，请稍后继续。' : `Tripo 请求失败（HTTP ${response.status}），请检查账户与任务记录。`, response.status, retryAfter); }
    let data; try { data = await response.json(); } catch { throw new ServiceError(method === 'POST' ? 'Tripo 提交响应无效，结果未知，请先检查任务记录。' : 'Tripo 查询响应无效，请稍后继续查询。'); }
    if (data.code !== 0 || !data.data) throw new ServiceError('Tripo 未接受请求，请检查接口权限、额度和任务记录。');
    return data.data;
  }
  requireKey() { if (!this.key) throw new ServiceError('请在本机 .env 配置 TRIPO_API_KEY 并重启服务。', 503); }
  async account() { this.requireKey(); const account = await this.request('/account/balance', null, 'GET'); if (typeof account.balance !== 'number' || !Number.isFinite(account.balance)) throw new ServiceError('Tripo 未返回可用的 API 余额信息。'); return { balance: account.balance, frozen: typeof account.frozen === 'number' ? account.frozen : null }; }
  taskId(value) { if (typeof value !== 'string' || !/^[\w-]{1,160}$/.test(value)) throw new ServiceError('Tripo 未返回有效任务标识，提交结果未知，请先检查任务记录。'); return value; }
  async create(bytes, fileName) {
    this.requireKey(); if ([...this.jobs.values()].some(j => activeStates.includes(j.state))) throw new ServiceError('已有 Tripo 任务进行中，请等待完成。', 409);
    validateRigGLB(bytes); if (bytes.length > 150 * 1024 * 1024) throw new ServiceError('Tripo 模型不能超过 150 MB。', 400);
    const job = { id: randomUUID(), state: 'uploading', createdAt: new Date().toISOString(), fileName: String(fileName || 'character.glb').slice(0, 120), message: '正在上传模型至 Tripo，随后执行绑骨前检查。' };
    this.jobs.set(job.id, job);
    try { await writeFile(path.join(this.directory, `${job.id}-input.glb`), bytes); await this.persist(); } catch (e) { this.jobs.delete(job.id); throw e; }
    const task = this.prepare(job, bytes).finally(() => this.tasks.delete(job.id)); this.tasks.set(job.id, task); task.catch(() => {}); return this.publicJob(job);
  }
  async prepare(job, bytes) {
    try {
      const form = new FormData(); form.set('file', new Blob([bytes], { type: 'model/gltf-binary' }), 'character.glb'); const uploaded = await this.request('/files', form);
      job.fileToken = this.taskId(uploaded.file_token); job.state = 'submitting-check'; await this.persist();
      const data = await this.request('/animations/rig-check', { input: job.fileToken }); job.checkTask = this.taskId(data.task_id); job.state = 'checking'; job.message = 'Tripo 正在识别可绑骨性和骨架类型。'; job.nextPoll = Date.now() + 5000;
    } catch (e) { job.state = 'failed'; job.message = e.message; }
    await this.persist();
  }
  async bind(id, rigType) {
    this.requireKey(); const job = this.job(id);
    if (job.state !== 'checked' || job.riggable !== true) throw new ServiceError('请先完成并通过 Tripo 绑骨前检查。', 409);
    if (!RIG_TYPES.includes(rigType)) throw new ServiceError('请选择有效的骨架类型。', 400);
    if ([...this.jobs.values()].some(j => activeStates.includes(j.state))) throw new ServiceError('已有 Tripo 任务进行中。', 409);
    job.state = 'submitting-rig'; job.rigType = rigType; job.modelVersion = ['biped', 'others'].includes(rigType) ? 'v3.0-20260909' : 'v2.5-20260210'; job.message = '正在提交 Tripo 自动绑骨…'; await this.persist();
    try {
      const account = await this.account();
      if (account.balance <= 0) throw new ServiceError('Tripo API 可用点数为 0；请补充 API 额度后再确认绑骨。预检查结果已保留。', 402);
      const data = await this.request('/animations/rig', { input: job.fileToken, model: job.modelVersion, rig_type: rigType, ...(rigType === 'biped' ? { spec: 'mixamo' } : {}), out_format: 'glb' });
      job.rigTask = this.taskId(data.task_id); job.state = 'rigging'; job.progress = 0; job.nextPoll = Date.now() + 5000; job.message = 'Tripo 正在预测骨架并生成蒙皮。';
    } catch (e) { job.state = [400, 401, 402, 403, 422, 429].includes(e.status) ? 'checked' : 'failed'; job.message = e.message; }
    await this.persist(); return this.publicJob(job);
  }
  async get(id) {
    const job = this.job(id);
    if (this.key && ['checking', 'rigging', 'downloading'].includes(job.state) && Date.now() >= (job.nextPoll || 0)) {
      if (!this.polls.has(id)) this.polls.set(id, this.poll(job).finally(() => this.polls.delete(id)));
      await this.polls.get(id);
    }
    return this.publicJob(job);
  }
  async poll(job) {
    job.nextPoll = Date.now() + 5000;
    try {
      if (job.state === 'downloading') { await this.cache(job); await this.persist(); return; }
      const phase = job.state; const data = await this.request(`/tasks/${encodeURIComponent(phase === 'checking' ? job.checkTask : job.rigTask)}`, null, 'GET'); job.progress = Number(data.progress) || 0;
      if (['failed', 'cancelled'].includes(data.status)) { job.state = 'failed'; job.message = `Tripo ${phase === 'checking' ? '预检查' : '绑骨'}失败，请检查模型姿态和四肢结构。`; }
      else if (data.status === 'success') {
        job.credits = { ...job.credits, [phase === 'checking' ? 'check' : 'rig']: typeof data.credits_consumed === 'number' ? data.credits_consumed : null };
        if (phase === 'checking') {
          if (typeof data.output?.riggable !== 'boolean') throw new ServiceError('Tripo 预检查缺少可绑骨性结果。');
          job.riggable = data.output.riggable; job.recommendedType = RIG_TYPES.includes(data.output.rig_type) ? data.output.rig_type : null; job.state = 'checked'; job.progress = 100;
          job.message = job.riggable ? '预检查通过。确认骨架类型后，再提交自动绑骨。' : '预检查未通过，请调整四肢、姿态或网格后重新导入。';
        } else {
          if (typeof data.output?.model_url !== 'string') throw new ServiceError('Tripo 结果中缺少模型文件。');
          job.outputUrl = data.output.model_url; job.state = 'downloading'; await this.persist(); await this.cache(job);
        }
      } else if (!['queued', 'running'].includes(data.status)) throw new ServiceError('Tripo 返回未知任务状态，请稍后查询。');
    } catch (e) { if (e instanceof ServiceError && e.status === 400 && job.state === 'downloading') job.state = 'failed'; job.message = e.message; job.nextPoll = Date.now() + Math.max(10, e.retryAfter || 10) * 1000; }
    await this.persist();
  }
  async cache(job) {
    // Download without provider Authorization; production injects the public-HTTPS validator.
    const response = await this.download(job.outputUrl, { signal: AbortSignal.timeout(180000) }); if (!response.ok) throw new ServiceError('Tripo 模型下载失败，可稍后继续查询。');
    const chunks = []; let size = 0; for await (const chunk of response.body) { size += chunk.length; if (size > 200 * 1024 * 1024) throw new ServiceError('Tripo 输出模型超过 200 MB。'); chunks.push(chunk); }
    const bytes = Buffer.concat(chunks); const doc = inspectSkinnedGLB(bytes);
    job.report = { bones: new Set(doc.skins.flatMap(s => s.joints)).size, skinnedMeshes: doc.nodes.filter(n => n.skin !== undefined).length, clips: (doc.animations || []).map(a => a.name || '未命名'), visualReview: 'required' };
    await writeFile(path.join(this.directory, `${job.id}.glb`), bytes); job.state = 'done'; job.progress = 100; job.message = 'Tripo 骨架与蒙皮已缓存。请导入预览，或转为 Blender 工程检查。';
  }
  async model(id) { const job = this.job(id); if (job.state !== 'done') throw new ServiceError('Tripo 绑骨模型尚未完成。', 404); return readFile(path.join(this.directory, `${id}.glb`)); }
}
