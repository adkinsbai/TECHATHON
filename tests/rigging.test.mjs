import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, mkdir, writeFile, readFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { EventEmitter } from 'node:events';
import { validateRigSettings, validateRigGLB, RiggingService } from '../server/rigging.mjs';
import template from '../src/data/rig-template.json' with { type: 'json' };

const settings = () => ({ version: template.version, yaw: 0, weightMode: 'distance', points: structuredClone(template.points) });
function glb(document) {
  const json = Buffer.from(JSON.stringify({ asset: { version: '2.0' }, meshes: [{ primitives: [{ attributes: {} }] }], ...document }));
  const length = Math.ceil(json.length / 4) * 4; const b = Buffer.alloc(20 + length, 32);
  b.writeUInt32LE(0x46546c67); b.writeUInt32LE(2, 4); b.writeUInt32LE(b.length, 8); b.writeUInt32LE(length, 12); b.writeUInt32LE(0x4e4f534a, 16); json.copy(b, 20); return b;
}
test('rig settings use server-owned bone hierarchy and explicit skin method', () => {
  const input = { ...settings(), bones: [['malicious']] }; const result = validateRigSettings(input);
  assert.equal(result.bones.length, 19); assert.equal(result.weightMode, 'distance'); assert.deepEqual(result.bones, template.bones);
  assert.throws(() => validateRigSettings({ ...input, weightMode: 'shell' }), /无效/);
});
test('rig settings reject nonfinite, out-of-range, degenerate and inverted torso joints', () => {
  for (const value of [NaN, Infinity, '0', -2]) { const input = settings(); input.points.head[1] = value; assert.throws(() => validateRigSettings(input)); }
  const degenerate = settings(); degenerate.points.headTop = degenerate.points.head; assert.throws(() => validateRigSettings(degenerate), /过近/);
  const inverted = settings(); inverted.points.chest[1] = .2; assert.throws(() => validateRigSettings(inverted), /逐级升高/);
});
test('rig input accepts static embedded GLB and rejects external files, animation and skin loss', () => {
  assert.ok(validateRigGLB(glb({})));
  for (const input of [{ buffers: [{ uri: 'file:///private' }] }, { images: [{ uri: 'https://example.org/image' }] }, { skins: [{}] }, { animations: [{}] }, { meshes: [{ primitives: [{ targets: [{}] }] }] }]) assert.throws(() => validateRigGLB(glb(input)));
  assert.throws(() => validateRigGLB(Buffer.from('bad')));
});
test('missing Blender and concurrent jobs are rejected before processing', async () => {
  const s = new RiggingService({ directory: '.', blender: null }); await assert.rejects(s.create(glb({}), settings()), /Blender/);
  s.blender = 'blender'; s.jobs.set('running', { state: 'running' }); await assert.rejects(s.create(glb({}), settings()), /正在运行/);
});
test('server restart marks interrupted Blender job as failed without re-running', async () => {
  const directory = await mkdtemp(path.join(tmpdir(), 'mori-rig-')); const id = '12345678-1234-1234-1234-123456789abc';
  try {
    await mkdir(path.join(directory, id)); await writeFile(path.join(directory, id, 'job.json'), JSON.stringify({ id, state: 'running', hasBlend: false }));
    const service = new RiggingService({ directory, blender: 'blender', runner: () => assert.fail('must not rerun') }); await service.initialize();
    assert.equal(service.get(id).state, 'failed'); assert.equal(service.get(id).modelUrl, null);
  } finally { await rm(directory, { recursive: true, force: true }); }
});
test('subprocess uses argument array, hides its window and withholds invalid output', async () => {
  const directory = await mkdtemp(path.join(tmpdir(), 'mori-rig-'));
  try {
    let captured;
    const runner = (file, args, options) => { captured = { file, args, options }; const child = new EventEmitter(); child.stdout = new EventEmitter(); child.stderr = new EventEmitter(); setTimeout(() => child.emit('close', 1), 0); return child; };
    const service = new RiggingService({ directory, blender: 'C:/Tools with space/blender.exe', script: 'C:/rig script.py', runner }); await service.initialize();
    const job = await service.create(glb({}), settings(), 'character.glb'); await service.tasks.get(job.id);
    assert.equal(captured.options.windowsHide, true); assert.equal(captured.options.shell, false); assert.ok(captured.args.includes('--disable-autoexec'));
    assert.equal(captured.options.env.RODIN_API_KEY, ''); assert.equal(captured.options.env.OPENAI_API_KEY, ''); assert.equal(captured.options.env.TRIPO_API_KEY, '');
    assert.equal(service.get(job.id).state, 'failed'); await assert.rejects(service.file(job.id, 'model'), /准备好/);
    assert.equal(JSON.parse(await readFile(path.join(directory, job.id, 'job.json'))).state, 'failed');
  } finally { await rm(directory, { recursive: true, force: true }); }
});
