import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { TripoService } from '../server/tripo.mjs';

function glb(skinned = false) {
  const doc = { asset: { version: '2.0' }, meshes: [{ primitives: [{ attributes: skinned ? { POSITION: 0, JOINTS_0: 1, WEIGHTS_0: 2 } : { POSITION: 0 } }] }], nodes: skinned ? [{ mesh: 0, skin: 0 }, { name: 'root' }] : [{ mesh: 0 }], ...(skinned ? { skins: [{ joints: [1] }] } : {}) };
  const json = Buffer.from(JSON.stringify(doc)); const len = Math.ceil(json.length / 4) * 4; const b = Buffer.alloc(20 + len, 32); b.writeUInt32LE(0x46546c67); b.writeUInt32LE(2, 4); b.writeUInt32LE(b.length, 8); b.writeUInt32LE(len, 12); b.writeUInt32LE(0x4e4f534a, 16); json.copy(b, 20); return b;
}
const response = data => new Response(JSON.stringify({ code: 0, data }));
async function setup(t, fetcher, download = async () => new Response(glb(true)), key = 'test-tripo-key') {
  const directory = await mkdtemp(path.join(tmpdir(), 'mori-tripo-')); t.after(() => rm(directory, { recursive: true, force: true }));
  const service = new TripoService({ key, directory, fetcher, download }); await service.initialize(); return service;
}
function provider(calls, type = 'biped') { return async (url, options) => {
  calls.push({ url, options }); assert.equal(options.headers.Authorization, 'Bearer test-tripo-key'); assert.equal(options.redirect, 'error');
  if (url.endsWith('/account/balance')) return response({ balance: 100, frozen: 0 });
  if (url.endsWith('/files')) { assert.ok(options.body.get('file')); return response({ file_token: 'private-file-token' }); }
  if (url.endsWith('/rig-check')) { assert.deepEqual(JSON.parse(options.body), { input: 'private-file-token' }); return response({ task_id: 'private-check-task' }); }
  if (url.endsWith('/private-check-task')) return response({ status: 'success', progress: 100, output: { riggable: true, rig_type: type }, credits_consumed: 0 });
  if (url.endsWith('/animations/rig')) return response({ task_id: 'private-rig-task' });
  return response({ status: 'success', output: { model_url: 'https://cdn.example/rig.glb?signed=private' }, credits_consumed: 30 });
}; }
async function checked(service) { const j = await service.create(glb(), 'rodin-character.glb'); await service.tasks.get(j.id); service.job(j.id).nextPoll = 0; await service.get(j.id); return j; }

test('Tripo checks external Rodin GLB, waits for explicit rig request, caches real skin without inventing animations', async t => {
  const calls = []; let downloads = 0; const s = await setup(t, provider(calls), async (_url, options) => { downloads++; assert.equal(options.headers, undefined); return new Response(glb(true)); });
  const j = await checked(s); assert.equal(s.job(j.id).state, 'checked'); assert.equal(calls.filter(c => c.url.endsWith('/animations/rig')).length, 0);
  await s.bind(j.id, 'biped'); const request = JSON.parse(calls.find(c => c.url.endsWith('/animations/rig')).options.body); assert.equal(request.model, 'v3.0-20260909'); assert.equal(request.spec, 'mixamo');
  await assert.rejects(s.bind(j.id, 'biped'), /检查/); s.job(j.id).nextPoll = 0;
  const done = await s.get(j.id); assert.equal(done.state, 'done'); assert.equal(done.report.bones, 1); assert.deepEqual(done.report.clips, []); assert.equal(downloads, 1);
  for (const secret of ['private-file-token', 'private-check-task', 'private-rig-task', 'test-tripo-key', '?signed=private']) assert.equal(JSON.stringify(done).includes(secret), false);
  assert.deepEqual(await s.model(j.id), glb(true));
});
test('quadruped uses the creature model and omits humanoid-only skeleton naming', async t => {
  const calls = []; const s = await setup(t, provider(calls, 'quadruped')); const j = await checked(s); await s.bind(j.id, 'quadruped');
  const request = JSON.parse(calls.find(c => c.url.endsWith('/animations/rig')).options.body); assert.equal(request.model, 'v2.5-20260210'); assert.equal(request.spec, undefined);
});
test('no key, existing skin and unapproved rig types are rejected before paid rigging', async t => {
  let calls = 0; const s = await setup(t, async () => { calls++; throw new Error(); }, undefined, '');
  await assert.rejects(s.create(glb(), 'test.glb'), /TRIPO_API_KEY/); s.key = 'test-tripo-key'; await assert.rejects(s.create(glb(true), 'test.glb'), /骨架/); assert.equal(calls, 0);
  s.jobs.set('example', { id: 'example', state: 'checked', riggable: true }); await assert.rejects(s.bind('example', 'shell'), /骨架类型/); assert.equal(calls, 0);
});
test('unknown upload submission is never automatically retried', async t => {
  let calls = 0; const s = await setup(t, async () => { calls++; throw new Error('network'); }); const j = await s.create(glb(), 'test.glb'); await s.tasks.get(j.id);
  assert.equal(calls, 1); assert.equal(s.job(j.id).state, 'failed'); assert.match(s.job(j.id).message, /未知/); await s.get(j.id); assert.equal(calls, 1);
});
test('zero API balance preserves the checked model and never submits a paid rig task', async t => {
  const calls=[]; const main=provider(calls); const s=await setup(t,(url,options)=>url.endsWith('/account/balance')?response({balance:0,frozen:0}):main(url,options));
  const j=await checked(s);const result=await s.bind(j.id,'biped');assert.equal(result.state,'checked');assert.match(result.message,/点数为 0/);assert.equal(calls.filter(c=>c.url.endsWith('/animations/rig')).length,0);assert.ok(s.job(j.id).fileToken);
});
test('poll limits retain the task and respect Retry-After', async t => {
  const calls = []; const main = provider(calls); const s = await setup(t, (url, options) => url.includes('/tasks/') ? new Response('{}', { status: 429, headers: { 'retry-after': '40' } }) : main(url, options));
  const j = await s.create(glb(), 'test.glb'); await s.tasks.get(j.id); s.job(j.id).nextPoll = 0; const start = Date.now(); const result = await s.get(j.id);
  assert.equal(result.state, 'checking'); assert.ok(s.job(j.id).nextPoll - start >= 39000);
});
test('riggable=false cannot be forced into a paid rigging request', async t => {
  const calls = []; const main = provider(calls); const s = await setup(t, (url, options) => url.includes('/tasks/') ? response({ status: 'success', output: { riggable: false, rig_type: 'biped' } }) : main(url, options));
  const j = await checked(s); await assert.rejects(s.bind(j.id, 'biped'), /检查/); assert.equal(calls.filter(c => c.url.endsWith('/animations/rig')).length, 0);
});
test('restart resumes queryable tasks without re-upload or duplicate rig request', async t => {
  const calls = []; const s = await setup(t, provider(calls)); const j = await checked(s); await s.bind(j.id, 'biped');
  const restored = new TripoService({ key: 'test-tripo-key', directory: s.directory, fetcher: provider(calls), download: async () => new Response(glb(true)) }); await restored.initialize(); restored.job(j.id).nextPoll = 0;
  assert.equal((await restored.get(j.id)).state, 'done'); assert.equal(calls.filter(c => c.url.endsWith('/animations/rig')).length, 1);
});
test('provider success without actual GLB skin is withheld from the browser', async t => {
  const calls = []; const s = await setup(t, provider(calls), async () => new Response(glb())); const j = await checked(s); await s.bind(j.id, 'biped'); s.job(j.id).nextPoll = 0;
  const result = await s.get(j.id); assert.equal(result.state, 'failed'); assert.equal(result.modelUrl, null);
});
