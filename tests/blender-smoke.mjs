// Optional local integration test; no network requests or API credits.
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { mkdir, readFile } from 'node:fs/promises';
import path from 'node:path';
import assert from 'node:assert/strict';
import { RiggingService, findBlender } from '../server/rigging.mjs';
import template from '../src/data/rig-template.json' with { type: 'json' };
const root = process.cwd(); const blender = await findBlender(root);
assert.ok(blender, 'Prepare Blender 4.5 LTS or set BLENDER_PATH before this integration test.');
await mkdir('.local/qa', { recursive: true });
await promisify(execFile)(blender, ['--background', '--factory-startup', '--disable-autoexec', '--python-exit-code', '1', '--python', path.join(root, 'tests/create-biped.py')], { windowsHide: true, timeout: 120000, env: { ...process.env, OPENAI_API_KEY: '', RODIN_API_KEY: '' } });
const service = new RiggingService({ directory: path.join(root, '.local/qa/rigging-smoke'), blender, script: path.join(root, 'server/blender/rig_character.py') }); await service.initialize();
for (const weightMode of ['heat', 'distance']) {
  const job = await service.create(await readFile('.local/qa/static-biped.glb'), { version: template.version, yaw: 90, weightMode, points: template.points }, 'static-biped.glb');
  await service.tasks.get(job.id); const result = service.get(job.id);
  assert.equal(result.state, 'done', JSON.stringify(result)); assert.equal(result.report.bones, 19); assert.equal(result.report.unweighted, 0); assert.equal(result.report.verifiedExport, true); assert.equal(result.report.clips.length, 3);
  assert.ok((await service.file(job.id, 'blend')).bytes.length > 1000);
  console.log(`PASS Blender ${weightMode}: 19 bones, real GLB skin and 3 animation clips; source .blend saved.`);
}
// Existing rigs must retain their original hierarchy and bytes, rather than receive 19 template bones.
await promisify(execFile)(process.execPath, [path.join(root, 'tests/create-fixture.mjs')], { windowsHide: true });
const original = await readFile('.local/qa/rigged-fixture.glb');
const existing = await service.createEditable(original, 'two-bone-existing.glb'); await service.tasks.get(existing.id);
const inspected = service.get(existing.id);
assert.equal(inspected.state, 'done', JSON.stringify(inspected)); assert.equal(inspected.report.bones, 2); assert.equal(inspected.report.unweighted, 0); assert.equal(inspected.report.clips.length, 1);
assert.deepEqual((await service.file(existing.id, 'model')).bytes, original);
console.log('PASS Blender existing rig: original 2 bones, morph, animation and exact GLB bytes preserved; editable .blend created.');
