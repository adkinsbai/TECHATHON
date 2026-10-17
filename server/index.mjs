import 'dotenv/config';
import http from 'node:http';
import { readFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { Readable } from 'node:stream';
import { lookup } from 'node:dns/promises';
import { isIP } from 'node:net';
import { RodinService, ServiceError } from './rodin.mjs';
import { ReferenceService, confirmedRodinInput } from './references.mjs';
import { RiggingService, findBlender } from './rigging.mjs';
import { TripoService } from './tripo.mjs';
import { ProxyAgent } from 'undici';

const root = fileURLToPath(new URL('../', import.meta.url));
const production = process.argv.includes('--production');
const port = Number(process.env.PORT || 5173);
const vite = production ? null : await (await import('vite')).createServer({ root, server: { middlewareMode: true }, appType: 'spa' });
function publicAddress(ip) {
  if (ip.includes(':')) return !/^(::|fc|fd|fe80|ff)/i.test(ip) && !ip.includes('::ffff:');
  const [a, b] = ip.split('.').map(Number);
  return a !== 0 && a !== 10 && a !== 127 && a < 224 && !(a === 169 && b === 254)
    && !(a === 172 && b >= 16 && b <= 31) && !(a === 192 && b === 168) && !(a === 100 && b >= 64 && b <= 127);
}
async function safeDownload(url, options) {
  let target = new URL(url);
  for (let i = 0; i < 5; i++) {
    if (target.protocol !== 'https:' || target.username || target.password) throw new ServiceError('模型下载地址不受支持。');
    const hostname = target.hostname.replace(/^\[|\]$/g, '');
    const records = isIP(hostname) ? [{ address: hostname }] : await lookup(hostname, { all: true });
    if (!records.length || records.some(r => !publicAddress(r.address))) throw new ServiceError('模型下载地址不受支持。');
    const response = await fetch(target, { ...options, redirect: 'manual' });
    if (![301, 302, 303, 307, 308].includes(response.status)) return response;
    await response.body?.cancel();
    target = new URL(response.headers.get('location'), target);
  }
  throw new ServiceError('模型下载重定向过多。');
}
const service = new RodinService({ key: process.env.RODIN_API_KEY || '', directory: path.join(root, '.local/rodin'), download: safeDownload });
await service.initialize();
const references = new ReferenceService({ key: process.env.OPENAI_API_KEY || '', model: process.env.OPENAI_IMAGE_MODEL || 'gpt-image-2', baseURL: process.env.OPENAI_BASE_URL || 'https://api.openai.com/v1', directory: path.join(root, '.local/references') });
await references.initialize();
const rigging = new RiggingService({ directory: path.join(root, '.local/rigs'), blender: await findBlender(root), script: path.join(root, 'server/blender/rig_character.py') });
await rigging.initialize();
const tripoProxy = process.env.TRIPO_PROXY_URL ? new ProxyAgent(process.env.TRIPO_PROXY_URL) : null;
const tripo = new TripoService({ key: process.env.TRIPO_API_KEY || '', directory: path.join(root, '.local/tripo'), fetcher: (url, options) => fetch(url, { ...options, ...(tripoProxy ? { dispatcher: tripoProxy } : {}) }), download: (url, options) => safeDownload(url, { ...options, ...(tripoProxy ? { dispatcher: tripoProxy } : {}) }) });
await tripo.initialize();
async function readForm(req, host, limit = 27 * 1024 * 1024) {
  const chunks=[]; let size=0;
  for await (const chunk of req) { size+=chunk.length; if(size>limit) throw new ServiceError('上传内容超过大小限制。',413); chunks.push(chunk); }
  try { return await new Request(`http://${host}`,{method:'POST',headers:{'Content-Type':req.headers['content-type']||''},body:Buffer.concat(chunks)}).formData(); }
  catch { throw new ServiceError('上传格式无效，请重新选择参考图。',400); }
}
const json = (res, status, data) => { res.writeHead(status, { 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store' }); res.end(JSON.stringify(data)); };
const mime = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript', '.css': 'text/css', '.svg': 'image/svg+xml', '.glb': 'model/gltf-binary', '.wasm': 'application/wasm', '.png': 'image/png', '.jpg': 'image/jpeg' };

const server = http.createServer(async (req, res) => {
  try {
    const host = req.headers.host || '';
    if (!/^(localhost|127\.0\.0\.1)(:\d+)?$/.test(host)) return json(res, 403, { error: '工作台仅支持本机访问。' });
    const url = new URL(req.url, `http://${host}`);
    if (/(^|\/)(\.env(?:\.[^/]*)?|\.local|\.git)(\/|$)/i.test(decodeURIComponent(url.pathname))) return json(res, 403, { error: '此路径不对浏览器开放。' });
    if (url.pathname.startsWith('/api/')) {
      res.setHeader('X-Content-Type-Options', 'nosniff');
      if (req.headers.origin && ![`http://127.0.0.1:${port}`, `http://localhost:${port}`].includes(req.headers.origin)) return json(res, 403, { error: '来源不受支持。' });
      if (req.method === 'GET' && url.pathname === '/api/config') return json(res, 200, { rodinConfigured: Boolean(service.key), imageConfigured: Boolean(references.key), imageModel: references.model, imageHost: new URL(references.baseURL).hostname, blenderConfigured: Boolean(rigging.blender), tripoConfigured: Boolean(tripo.key), mode: 'local' });
      if (req.method === 'GET' && url.pathname === '/api/auto-rigs') return json(res, 200, { jobs: [...tripo.jobs.values()].sort((a,b) => b.createdAt.localeCompare(a.createdAt)).map(j => tripo.publicJob(j)) });
      if (req.method === 'GET' && url.pathname === '/api/tripo/account') return json(res, 200, await tripo.account());
      if (req.method === 'POST' && url.pathname === '/api/auto-rigs') {
        const form = await readForm(req, host, 151 * 1024 * 1024); const model = form.get('model');
        if (!model || typeof model === 'string') throw new ServiceError('请提交静态 GLB 模型。', 400);
        return json(res, 202, await tripo.create(Buffer.from(await model.arrayBuffer()), model.name));
      }
      const autoRigMatch = url.pathname.match(/^\/api\/auto-rigs\/([a-f0-9-]{36})(?:\/(model|bind|blender))?$/);
      if (autoRigMatch) {
        const [, id, action] = autoRigMatch;
        if (req.method === 'GET' && !action) return json(res, 200, await tripo.get(id));
        if (req.method === 'GET' && action === 'model') { res.writeHead(200, { 'Content-Type': 'model/gltf-binary', 'Content-Disposition': 'attachment; filename="tripo-rigged.glb"' }); return res.end(await tripo.model(id)); }
        if (req.method === 'POST' && action === 'bind') { const form = await readForm(req, host, 16384); return json(res, 202, await tripo.bind(id, String(form.get('rigType') || ''))); }
        if (req.method === 'POST' && action === 'blender') {
          const job = tripo.job(id);
          if (job.blenderJobId) { const previous = rigging.get(job.blenderJobId); if (previous.state !== 'failed') return json(res, 200, previous); }
          const blenderJob = await rigging.createEditable(await tripo.model(id), `tripo-${id.slice(0,8)}.glb`); job.blenderJobId = blenderJob.id; await tripo.persist(); return json(res, 202, blenderJob);
        }
      }
      if (req.method === 'POST' && url.pathname === '/api/rigging/import') {
        const form = await readForm(req, host, 201 * 1024 * 1024); const model = form.get('model');
        if (!model || typeof model === 'string') throw new ServiceError('请提交已有蒙皮的 GLB。', 400);
        return json(res, 202, await rigging.createEditable(Buffer.from(await model.arrayBuffer()), model.name));
      }
      if (req.method === 'GET' && url.pathname === '/api/rigging/script') { res.writeHead(200, { 'Content-Type': 'text/plain; charset=utf-8' }); return res.end(await readFile(rigging.script)); }
      if (req.method === 'GET' && url.pathname === '/api/rigs') return json(res, 200, { jobs: [...rigging.jobs.values()].sort((a, b) => b.createdAt.localeCompare(a.createdAt)).map(j => rigging.publicJob(j)) });
      if (req.method === 'POST' && url.pathname === '/api/rigs') {
        const form = await readForm(req, host, 201 * 1024 * 1024);
        const model = form.get('model');
        if (!model || typeof model === 'string') throw new ServiceError('请提交当前 GLB 模型。', 400);
        let settings; try { settings = JSON.parse(String(form.get('settings'))); } catch { throw new ServiceError('关节配置无效。', 400); }
        return json(res, 202, await rigging.create(Buffer.from(await model.arrayBuffer()), settings, model.name));
      }
      const rigMatch = url.pathname.match(/^\/api\/rigs\/([a-f0-9-]{36})(?:\/(model|blend|report))?$/);
      if (req.method === 'GET' && rigMatch) {
        if (!rigMatch[2]) return json(res, 200, rigging.get(rigMatch[1]));
        const file = await rigging.file(rigMatch[1], rigMatch[2]);
        res.writeHead(200, { 'Content-Type': file.mime, 'Content-Disposition': `attachment; filename="${file.name}"` }); return res.end(file.bytes);
      }
      if (req.method === 'GET' && url.pathname === '/api/references') return json(res,200,{references:[...references.jobs.values()].map(j=>references.publicJob(j)).reverse()});
      if (req.method === 'POST' && ['/api/references/prepare','/api/references/import'].includes(url.pathname)) {
        const form=await readForm(req,host);
        return json(res,202,url.pathname.endsWith('/import')?await references.importImage(form):await references.create(form));
      }
      const referenceMatch=url.pathname.match(/^\/api\/references\/([a-f0-9-]{36})(\/image)?$/);
      if(req.method==='GET' && referenceMatch) {
        if(referenceMatch[2]) { const {bytes,mime}=await references.image(referenceMatch[1]); res.writeHead(200,{'Content-Type':mime,'X-Content-Type-Options':'nosniff','Cache-Control':'private, max-age=3600'}); return res.end(bytes); }
        return json(res,200,references.get(referenceMatch[1]));
      }
      if (req.method === 'GET' && url.pathname === '/api/jobs') return json(res, 200, { jobs: [...service.jobs.values()].map(j => service.publicJob(j)).reverse() });
      if (req.method === 'POST' && url.pathname === '/api/generate') {
        if (!service.key) throw new ServiceError('请先在 .env 配置 RODIN_API_KEY 并重启服务。', 503);
        const form=await readForm(req,host);
        const prepared=await confirmedRodinInput(form,references);
        return json(res,201,await service.create(prepared.input,prepared.provenance));
      }
      const match = url.pathname.match(/^\/api\/jobs\/([a-f0-9-]{36})(\/model)?$/);
      if (req.method === 'GET' && match) {
        if (match[2]) {
          const job = service.jobs.get(match[1]);
          if (!job || job.state !== 'done') throw new ServiceError('模型尚未准备完成。', 404);
          const bytes = await readFile(path.join(service.directory, `${job.id}.glb`));
          res.writeHead(200, { 'Content-Type': 'model/gltf-binary', 'Content-Disposition': 'inline; filename="character.glb"' }); return res.end(bytes);
        }
        return json(res, 200, await service.get(match[1]));
      }
      return json(res, 404, { error: '接口不存在。' });
    }
    if (vite) return vite.middlewares(req, res, () => { res.writeHead(404); res.end(); });
    const relative = decodeURIComponent(url.pathname).replace(/^\/+/, '') || 'index.html';
    const file = path.resolve(root, 'dist', relative);
    if (!file.startsWith(path.resolve(root, 'dist') + path.sep)) { res.writeHead(403); return res.end(); }
    try {
      const bytes = await readFile(file); res.writeHead(200, { 'Content-Type': mime[path.extname(file)] || 'application/octet-stream' }); res.end(bytes);
    } catch {
      if (path.extname(file)) { res.writeHead(404); res.end(); }
      else { res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' }); res.end(await readFile(path.join(root, 'dist/index.html'))); }
    }
  } catch (error) { json(res, error instanceof ServiceError ? error.status : 500, { error: error instanceof ServiceError ? error.message : '本地服务发生错误，请查看终端或稍后重试。' }); }
});
server.listen(port, '127.0.0.1', () => console.log(`\n  MORI 角色工作台 → http://127.0.0.1:${port}\n`));
server.on('error', error => { console.error(error.code === 'EADDRINUSE' ? `端口 ${port} 已被占用，请在 .env 修改 PORT。` : error.message); process.exitCode = 1; });
for (const signal of ['SIGINT', 'SIGTERM']) process.on(signal, () => server.close(async () => { await vite?.close(); process.exit(0); }));
