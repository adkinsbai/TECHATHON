import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, readFile, rm } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { RodinService, validateGeneration } from '../server/rodin.mjs';

const response = (body, status = 200, headers = {}) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json', ...headers } });
function promptForm() { const form = new FormData(); form.set('prompt', 'A mint rabbit'); return form; }
async function setup(t, fetcher, download) {
  const directory = await mkdtemp(path.join(os.tmpdir(), 'mori-rodin-'));
  t.after(() => rm(directory, { recursive: true, force: true }));
  const service = new RodinService({ key: 'test-key-not-a-secret', directory, fetcher, download }); await service.initialize(); return service;
}
test('rejects invalid inputs before making a billable request', () => {
  assert.throws(() => validateGeneration(new FormData()), /描述/);
  const form = promptForm(); form.set('prompt', 'x'.repeat(1025)); assert.throws(() => validateGeneration(form), /1024/);
  const images = promptForm(); images.append('images', new Blob(['x'], { type: 'text/html' }), 'wrong.png'); assert.throws(() => validateGeneration(images), /参考图/);
});
test('pins generation parameters and never forwards client credentials or unsupported fields', () => {
  const form = promptForm(); form.set('tier', 'expensive-tier'); form.set('api_key', 'client-key');
  const result = validateGeneration(form); assert.equal(result.get('tier'), 'Gen-2.5-Medium'); assert.equal(result.get('quality_override'), '20000'); assert.equal(result.get('api_key'), null);
});
test('forwards reference images and optional guidance together in one provider submission', async t => {
  let calls = 0;
  const service = await setup(t, async (url, request) => {
    calls++;
    assert.ok(url.endsWith('/rodin'));
    const payload = request.body;
    assert.equal(payload.get('prompt'), 'Keep the silhouette, separate the arms from the torso.');
    assert.equal(payload.get('TAPose'), 'true');
    const images = payload.getAll('images');
    assert.equal(images.length, 2);
    assert.equal(images[0].name, 'front.png');
    assert.equal(images[1].name, 'side.png');
    assert.equal(await images[0].text(), 'front-image-bytes');
    assert.equal(await images[1].text(), 'side-image-bytes');
    return response({ uuid: 'hybrid-task', jobs: { subscription_key: 'hybrid-subscription' } }, 201);
  });
  const form = new FormData();
  form.set('prompt', '  Keep the silhouette, separate the arms from the torso.  ');
  form.set('TAPose', 'true');
  form.append('images', new Blob(['front-image-bytes'], { type: 'image/png' }), 'front.png');
  form.append('images', new Blob(['side-image-bytes'], { type: 'image/png' }), 'side.png');
  const job = await service.create(form);
  assert.equal(job.state, 'pending');
  assert.equal(job.prompt, 'Keep the silhouette, separate the arms from the torso.');
  assert.equal(job.input.kind, 'mixed');
  assert.equal(job.input.images.length, 2);
  assert.equal(job.input.images[0].name, 'front.png');
  assert.equal('subscriptionKey' in job, false);
  assert.equal('key' in job.input, false);
  assert.equal(calls, 1);
});
test('HTTP 201 with provider error is not accepted as a job', async t => {
  let calls = 0;
  const service = await setup(t, async () => { calls++; return response({ error: 'NO_SUCH_TASK' }, 201); });
  await assert.rejects(service.create(promptForm()), /NO_SUCH_TASK/); assert.equal(service.jobs.size, 0); assert.equal(calls, 1);
});
test('uncertain generation submission is never retried automatically', async t => {
  let calls = 0; const service = await setup(t, async () => { calls++; throw new Error('network'); });
  await assert.rejects(service.create(promptForm()), /避免重复扣费/); assert.equal(calls, 1);
});
test('uses subscription key for status and waits for every job before downloading', async t => {
  let statusCalls = 0; let downloadCalls = 0;
  const service = await setup(t, async (url, request) => {
    if (url.endsWith('/rodin')) return response({ uuid: 'provider-task', jobs: { subscription_key: 'provider-subscription' } }, 201);
    if (url.endsWith('/status')) {
      assert.equal(JSON.parse(request.body).subscription_key, 'provider-subscription'); statusCalls++;
      return response({ jobs: [{ status: 'Done' }, { status: 'Running' }] });
    }
    downloadCalls++; throw new Error('download must not happen');
  });
  const created = await service.create(promptForm()); const internal = service.jobs.get(created.id); internal.lastChecked = 0;
  const result = await service.get(created.id); assert.equal(result.state, 'running'); assert.equal(statusCalls, 1); assert.equal(downloadCalls, 0);
  assert.equal(JSON.stringify(result).includes('provider-subscription'), false);
});
test('caches completed GLB locally, exposes a local URL, and restores jobs after restart', async t => {
  const service = await setup(t, async (url, request) => {
    if (url.endsWith('/rodin')) return response({ uuid: 'provider-task', jobs: { subscription_key: 'private-subscription' } }, 201);
    if (url.endsWith('/status')) return response({ jobs: [{ status: 'Done' }] });
    assert.equal(JSON.parse(request.body).task_uuid, 'provider-task'); return response({ list: [{ name: 'model.glb', url: 'https://example.invalid/signed-token' }] });
  }, async () => new Response(new Uint8Array([103, 108, 84, 70, 2, 0, 0, 0])));
  const created = await service.create(promptForm()); service.jobs.get(created.id).lastChecked = 0;
  const done = await service.get(created.id); assert.equal(done.state, 'done'); assert.equal(done.modelUrl, `/api/jobs/${done.id}/model`);
  assert.equal(JSON.stringify(done).includes('signed-token'), false); assert.equal(JSON.stringify(done).includes('private-subscription'), false);
  assert.equal((await readFile(path.join(service.directory, `${done.id}.glb`))).toString('ascii', 0, 4), 'glTF');
  const restarted = new RodinService({ directory: service.directory }); await restarted.initialize(); assert.equal((await restarted.get(done.id)).state, 'done');
});
test('failed or cancelled provider jobs never trigger a result download', async t => {
  const service = await setup(t, async url => url.endsWith('/rodin')
    ? response({ uuid: 'provider-task', jobs: { subscription_key: 'subscription' } })
    : response({ jobs: [{ status: 'Failed' }] }));
  const created = await service.create(promptForm()); service.jobs.get(created.id).lastChecked = 0;
  assert.equal((await service.get(created.id)).state, 'failed');
});
test('status rate limits preserve pending job and honor Retry-After', async t => {
  const service = await setup(t, async url => url.endsWith('/rodin')
    ? response({ uuid: 'provider-task', jobs: { subscription_key: 'subscription' } })
    : response({}, 429, { 'Retry-After': '47' }));
  const created = await service.create(promptForm()); service.jobs.get(created.id).lastChecked = 0;
  const result = await service.get(created.id); assert.equal(result.state, 'pending'); assert.equal(result.retryAfter, 47);
});
