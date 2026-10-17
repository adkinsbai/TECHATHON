import { mkdir, readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { randomUUID } from 'node:crypto';

const BASE = 'https://api.hyper3d.com/api/v2';
export class ServiceError extends Error {
  constructor(message, status = 502, retryAfter = 0) { super(message); this.status = status; this.retryAfter = retryAfter; }
}

export function validateGeneration(form) {
  const prompt = String(form.get('prompt') || '').trim();
  const images = form.getAll('images').filter(x => typeof x !== 'string' && x.size > 0);
  if (!prompt && !images.length) throw new ServiceError('请输入角色描述或上传参考图。', 400);
  if (prompt.length > 1024) throw new ServiceError('角色描述不能超过 1024 个字符。', 400);
  if (images.length > 5) throw new ServiceError('最多上传 5 张参考图。', 400);
  for (const image of images) {
    if (!['image/png', 'image/jpeg', 'image/webp'].includes(image.type) || image.size > 5 * 1024 * 1024) {
      throw new ServiceError('参考图须为 PNG、JPG 或 WebP，每张不超过 5 MB。', 400);
    }
  }
  const out = new FormData();
  if (prompt) out.set('prompt', prompt);
  for (const image of images) out.append('images', image, image.name);
  out.set('tier', 'Gen-2.5-Medium');
  out.set('mesh_mode', 'Raw');
  out.set('geometry_file_format', 'glb');
  out.set('quality_override', '20000');
  out.set('material', 'PBR');
  out.set('TAPose', form.get('TAPose') === 'true' ? 'true' : 'false');
  return out;
}

export class RodinService {
  constructor({ key = '', directory, fetcher = fetch, download = fetch } = {}) {
    this.key = key; this.directory = directory; this.fetcher = fetcher; this.download = download;
    this.jobs = new Map(); this.locks = new Map(); this.submitting = false;
  }
  async initialize() {
    await mkdir(this.directory, { recursive: true });
    try {
      const saved = JSON.parse(await readFile(path.join(this.directory, 'jobs.json'), 'utf8'));
      for (const job of saved) this.jobs.set(job.id, job);
    } catch (error) { if (error.code !== 'ENOENT') console.warn('任务记录无法读取；将启动空任务列表。'); }
  }
  persist() {
    // Serialize writes so simultaneous jobs cannot leave a partially overwritten file.
    const data = JSON.stringify([...this.jobs.values()], null, 2);
    this.pendingWrite = (this.pendingWrite || Promise.resolve()).catch(() => {}).then(async () => {
      await writeFile(path.join(this.directory, 'jobs.json'), data, { mode: 0o600 });
    });
    return this.pendingWrite;
  }
  publicJob(job) {
    return { id: job.id, state: job.state, createdAt: job.createdAt, prompt: job.prompt,
      input: job.input,
      stage: job.stage, message: job.message, retryAfter: job.retryAfter || 5,
      modelUrl: job.state === 'done' ? `/api/jobs/${job.id}/model` : null };
  }
  async request(endpoint, body) {
    if (!this.key) throw new ServiceError('尚未配置 Rodin API Key，请在项目 .env 中设置并重启服务。', 503);
    let response;
    try {
      response = await this.fetcher(`${BASE}/${endpoint}`, {
        method: 'POST', headers: { Authorization: `Bearer ${this.key}`,
          ...(body instanceof FormData ? {} : { 'Content-Type': 'application/json' }) },
        body: body instanceof FormData ? body : JSON.stringify(body), signal: AbortSignal.timeout(90000)
      });
    } catch {
      throw new ServiceError(endpoint === 'rodin'
        ? '提交结果未知，请先到 Rodin 控制台确认任务，避免重复扣费。'
        : 'Rodin 暂时无法连接，请稍后继续查询。');
    }
    if (!response.ok) {
      const header = response.headers.get('retry-after');
      const parsedDelay = header && /^\d+$/.test(header) ? Number(header) : header ? Math.ceil((Date.parse(header) - Date.now()) / 1000) : 15;
      const retryAfter = Math.max(5, Number.isFinite(parsedDelay) ? parsedDelay : 15);
      const message = response.status === 401 ? 'Rodin 密钥无效或无访问权限。'
        : response.status === 429 ? 'Rodin 请求较多，请稍后再试。'
        : `Rodin 请求失败（HTTP ${response.status}），请检查账户与任务。`;
      throw new ServiceError(message, response.status === 429 ? 429 : 502, retryAfter);
    }
    let data;
    try { data = await response.json(); } catch { throw new ServiceError('Rodin 返回了无法解析的结果。'); }
    if (data.error && data.error !== 'OK') {
      throw new ServiceError(`Rodin 未接受请求：${String(data.error).replace(/[^\w-]/g, '').slice(0, 80)}`);
    }
    return data;
  }
  async create(form, provenance = undefined) {
    const payload = validateGeneration(form);
    if (this.submitting) throw new ServiceError('正在提交上一个任务，请稍候。', 409);
    this.submitting = true;
    try {
      const data = await this.request('rodin', payload);
      if (!data.uuid || !data.jobs?.subscription_key) throw new ServiceError('Rodin 未返回有效任务编号，请检查控制台后再提交。');
      const job = { id: randomUUID(), upstreamId: data.uuid, subscriptionKey: data.jobs.subscription_key,
        prompt: String(payload.get('prompt') || ''),
        input: {
          kind: payload.getAll('images').length ? payload.has('prompt') ? 'mixed' : 'image' : 'text',
          prompt: String(payload.get('prompt') || ''),
          images: payload.getAll('images').map(image => ({ name: image.name, size: image.size, type: image.type })),
          taPose: payload.get('TAPose') === 'true',
          ...(provenance ? { preparation: provenance } : {})
        }, state: 'pending', stage: '已提交，等待生成',
        createdAt: new Date().toISOString(), lastChecked: Date.now(), retryAfter: 5 };
      this.jobs.set(job.id, job); await this.persist(); return this.publicJob(job);
    } finally { this.submitting = false; }
  }
  async get(id) {
    const job = this.jobs.get(id);
    if (!job) throw new ServiceError('未找到任务；请检查任务记录是否仍在本机。', 404);
    if (['done', 'failed'].includes(job.state) || Date.now() - job.lastChecked < job.retryAfter * 1000) return this.publicJob(job);
    if (!this.locks.has(id)) {
      this.locks.set(id, this.refresh(job).finally(() => this.locks.delete(id)));
    }
    await this.locks.get(id); return this.publicJob(job);
  }
  async refresh(job) {
    job.lastChecked = Date.now();
    try {
      const data = await this.request('status', { subscription_key: job.subscriptionKey });
      const states = (data.jobs || []).map(j => j.status);
      if (states.some(s => ['Failed', 'Canceled', 'Cancelled'].includes(s))) {
        job.state = 'failed'; job.stage = '生成失败'; job.message = '请在 Rodin 控制台查看失败原因。';
      } else if (states.length && states.every(s => s === 'Done')) {
        job.stage = '保存模型到本机';
        const result = await this.request('download', { task_uuid: job.upstreamId });
        const file = result.list?.find(f => /\.glb$/i.test(f.name));
        if (!file) throw new ServiceError('任务完成，但未返回 GLB 文件，请在控制台检查导出结果。');
        const response = await this.download(file.url, { signal: AbortSignal.timeout(120000) });
        if (!response.ok) throw new ServiceError('模型下载失败，将在下次查询时重试。');
        if (Number(response.headers.get('content-length')) > 200 * 1024 * 1024) throw new ServiceError('模型超过 200 MB，请降低生成面数后重试。');
        const reader = response.body.getReader(); const chunks = []; let size = 0;
        try {
          while (true) {
            const { value, done } = await reader.read(); if (done) break;
            size += value.byteLength;
            if (size > 200 * 1024 * 1024) throw new ServiceError('模型超过 200 MB，下载已停止。');
            chunks.push(Buffer.from(value));
          }
        } finally { await reader.cancel().catch(() => {}); }
        const bytes = Buffer.concat(chunks);
        if (bytes.toString('ascii', 0, 4) !== 'glTF') throw new ServiceError('下载内容不是有效 GLB 文件。');
        await writeFile(path.join(this.directory, `${job.id}.glb`), bytes);
        job.state = 'done'; job.stage = '生成完成'; job.message = '模型已保存，导入后请检查骨骼与蒙皮。';
      } else {
        job.state = 'running'; job.stage = states.includes('Running') ? '正在生成模型与材质' : 'Rodin 正在处理';
        job.message = undefined;
      }
      job.retryAfter = Math.min((job.retryAfter || 5) + 5, 30);
    } catch (error) {
      job.message = error instanceof ServiceError ? error.message : '查询暂时失败，将继续重试。';
      job.retryAfter = error.retryAfter || 15;
    }
    await this.persist();
  }
}
