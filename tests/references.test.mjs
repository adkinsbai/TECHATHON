import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, rm } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { ReferenceService, confirmedRodinInput, imageType } from '../server/references.mjs';

const png=Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRKwAAAAASUVORK5CYII=','base64');
const output=()=>new Response(JSON.stringify({data:[{b64_json:png.toString('base64')}]}),{headers:{'Content-Type':'application/json'}});
async function setup(t,fetcher,key='relay-test-key') {
  const directory=await mkdtemp(path.join(os.tmpdir(),'mori-references-'));
  t.after(()=>rm(directory,{recursive:true,force:true}));
  const service=new ReferenceService({key,model:'gpt-image-2.5-flare',baseURL:'https://relay.example/v1',directory,fetcher});await service.initialize();return service;
}
function form(withImage=true){const input=new FormData();input.set('prompt','保留兔子形象，换成沙滩装。');input.set('TAPose','true');input.set('inputSignature','test-draft');if(withImage)input.append('images',new Blob([png],{type:'image/png'}),'original.png');return input;}

test('image editing forwards both visual reference and semantic instructions to the configured relay only',async t=>{
  let calls=0;
  const service=await setup(t,async(url,request)=>{
    calls++;assert.equal(url,'https://relay.example/v1/images/edits');assert.equal(request.redirect,'error');
    assert.equal(request.headers.Authorization,'Bearer relay-test-key');assert.equal(request.headers['Content-Type'],undefined);
    assert.equal(request.body.get('model'),'gpt-image-2.5-flare');assert.ok(request.body.get('prompt').includes('保留兔子形象，换成沙滩装。'));
    assert.ok(request.body.get('prompt').includes('species'));assert.equal(request.body.getAll('image[]').length,1);
    assert.deepEqual(Buffer.from(await request.body.get('image[]').arrayBuffer()),png);return output();
  });
  const job=await service.create(form());await service.tasks.get(job.id);
  const result=service.get(job.id);assert.equal(result.state,'done');assert.equal(calls,1);assert.equal(result.imageUrl,`/api/references/${job.id}/image`);
  assert.equal(JSON.stringify(result).includes('relay-test-key'),false);
});
test('text-only preparation uses image generation, not the edit endpoint',async t=>{
  const service=await setup(t,async(url,request)=>{assert.equal(url,'https://relay.example/v1/images/generations');assert.ok(JSON.parse(request.body).prompt.includes('保留兔子形象'));return output();});
  const job=await service.create(form(false));await service.tasks.get(job.id);assert.equal(service.get(job.id).state,'done');
});
test('target style changes the upstream image instructions and is recorded, invalid styles never call the provider',async t=>{
  let calls=0;const service=await setup(t,async(_url,request)=>{calls++;assert.ok(request.body.get('prompt').includes('matte clay figurine'));return output();});
  const input=form();input.set('style','clay');const job=await service.create(input);await service.tasks.get(job.id);assert.equal(service.get(job.id).style,'clay');
  input.set('style','__proto__');await assert.rejects(service.create(input),/目标风格/);assert.equal(calls,1);
});
test('Rodin input requires explicit confirmation and uses only the prepared image',async t=>{
  const service=await setup(t,async()=>output());const created=await service.create(form());await service.tasks.get(created.id);
  const request=new FormData();request.set('referenceId',created.id);
  await assert.rejects(confirmedRodinInput(request,service),/确认/);
  request.set('referenceConfirmed','true');request.set('prompt','stale instructions that must not reach Rodin');
  request.append('images',new Blob(['wrong original'],{type:'image/png'}),'wrong.png');
  const result=await confirmedRodinInput(request,service);
  assert.equal(result.input.has('prompt'),false);assert.equal(result.input.getAll('images').length,1);
  assert.deepEqual(Buffer.from(await result.input.get('images').arrayBuffer()),png);
  assert.equal(result.provenance.referenceId,created.id);assert.equal(result.provenance.brief,'保留兔子形象，换成沙滩装。');
});
test('an uncertain image request is not retried and cannot be used for 3D generation',async t=>{
  let calls=0;const service=await setup(t,async()=>{calls++;throw new Error('network');});
  const job=await service.create(form());await service.tasks.get(job.id);assert.equal(calls,1);assert.equal(service.get(job.id).state,'failed');
  assert.match(service.get(job.id).message,/结果未知/);await assert.rejects(service.image(job.id),/尚未/);
});
test('manual finished references work without image credentials and reject non-image bytes',async t=>{
  const service=await setup(t,async()=>{throw new Error('must not call provider');},'');
  const job=await service.importImage(form());assert.equal(job.state,'done');assert.equal(job.source,'manual');assert.deepEqual((await service.image(job.id)).bytes,png);
  assert.throws(()=>imageType(Buffer.from('<svg onload="alert(1)">')),/有效/);
  await assert.rejects(service.create(form()),/OPENAI_API_KEY/);
});
test('finished references persist across restarts',async t=>{
  const service=await setup(t,async()=>output());const job=await service.importImage(form());
  const restored=new ReferenceService({directory:service.directory});await restored.initialize();assert.equal(restored.get(job.id).state,'done');
  assert.deepEqual((await restored.image(job.id)).bytes,png);
});
