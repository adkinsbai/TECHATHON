import { mkdir, readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { randomUUID } from 'node:crypto';
import { ServiceError, validateGeneration } from './rodin.mjs';
import styles from '../src/data/reference-styles.json' with { type: 'json' };
function referenceStyle(form) {
  const style = String(form.get('style') || 'preserve');
  if (!Object.hasOwn(styles, style)) throw new ServiceError('请选择有效的目标风格。', 400);
  return style;
}

export function referencePrompt(brief, hasImages, taPose, style = 'preserve') {
  return [
    'Create a single full-body character reference image for subsequent image-to-3D reconstruction.',
    hasImages
      ? 'Edit the supplied reference image(s). Preserve the main character\'s species, identity, face, body proportions and distinctive silhouette unless the user explicitly requests a change. Never turn an animal into a human just because human clothing is requested. Apply the requested changes to outfit, colors, accessories and style visibly in the image.'
      : 'Design the character described by the user. Do not assume an unspecified name refers to a particular known character; follow the explicit visual description.',
    'TARGET VISUAL STYLE:', (styles[style] || styles.preserve).instruction,
    'USER REQUIREMENTS (apply faithfully):', brief || 'Preserve the supplied character and prepare a clean, complete modeling reference.',
    'Show one character, complete from head to feet including ears and tail. Use a plain light neutral background, clear readable silhouette, and even studio lighting. No text, labels, watermark, scenery, pedestal, or multi-view collage. Preserve props explicitly requested by the user.',
    taPose ? 'If compatible with the user\'s requested pose and props, use a relaxed A-pose with separated arms and legs to help later rigging.' : ''
  ].filter(Boolean).join('\n\n');
}

export function imageType(bytes) {
  if (bytes.length >= 8 && bytes.subarray(0, 8).equals(Buffer.from([137,80,78,71,13,10,26,10]))) return 'image/png';
  if (bytes.length >= 3 && bytes[0] === 255 && bytes[1] === 216 && bytes[2] === 255) return 'image/jpeg';
  if (bytes.length >= 12 && bytes.toString('ascii',0,4) === 'RIFF' && bytes.toString('ascii',8,12) === 'WEBP') return 'image/webp';
  throw new ServiceError('参考图内容不是有效的 PNG、JPG 或 WebP。', 400);
}

export class ReferenceService {
  constructor({ key = '', model = 'gpt-image-2', baseURL = 'https://api.openai.com/v1', directory, fetcher = fetch } = {}) {
    const target=new URL(baseURL);
    if(target.protocol!=='https:' || target.username || target.password || target.search || target.hash) throw new Error('图像服务地址必须是无凭证的 HTTPS API 地址。');
    this.key = key; this.model = model; this.baseURL=target.href.replace(/\/$/,''); this.directory = directory; this.fetcher = fetcher;
    this.jobs = new Map(); this.tasks = new Map(); this.active = false;
  }
  async initialize() {
    await mkdir(this.directory, { recursive: true });
    try {
      for (const job of JSON.parse(await readFile(path.join(this.directory,'references.json'),'utf8'))) {
        if (['pending','running'].includes(job.state)) { job.state = 'failed'; job.message = '服务曾重启，生成结果未知。请先检查图像服务记录，避免重复提交。'; }
        this.jobs.set(job.id, job);
      }
    } catch (error) { if (error.code !== 'ENOENT') console.warn('参考图记录无法读取，已启动空列表。'); }
    await this.persist();
  }
  persist() {
    const data = JSON.stringify([...this.jobs.values()],null,2);
    this.pendingWrite = (this.pendingWrite || Promise.resolve()).catch(() => {}).then(() => writeFile(path.join(this.directory,'references.json'),data,{mode:0o600}));
    return this.pendingWrite;
  }
  publicJob(job) {
    return { id:job.id, state:job.state, prompt:job.prompt, inputSignature:job.inputSignature, source:job.source,
      createdAt:job.createdAt, message:job.message, model:job.model, style:job.style || 'preserve', imageUrl:job.state === 'done' ? `/api/references/${job.id}/image` : null };
  }
  get(id) { const job=this.jobs.get(id); if(!job) throw new ServiceError('未找到参考图记录。',404); return this.publicJob(job); }
  async create(form) {
    const input = validateGeneration(form); const style = referenceStyle(form);
    if (!this.key) throw new ServiceError('请先在 .env 配置 OPENAI_API_KEY 并重启服务。',503);
    if (this.active) throw new ServiceError('正在处理一张参考图，请等待完成后再提交。',409);
    const prompt=String(input.get('prompt')||''); const images=input.getAll('images');
    for (const image of images) imageType(Buffer.from(await image.arrayBuffer()));
    if (this.active) throw new ServiceError('正在处理一张参考图，请等待完成后再提交。',409);
    const job={ id:randomUUID(),state:'pending',prompt,style,inputSignature:String(form.get('inputSignature')||''),source:'openai',model:this.model,
      createdAt:new Date().toISOString(),message:'等待图像生成；完成后请先确认外观。',taPose:input.get('TAPose')==='true' };
    this.active=true; this.jobs.set(job.id,job);
    try { await this.persist(); }
    catch(error) { this.active=false; this.jobs.delete(job.id); throw error; }
    const task=this.run(job,images).finally(()=>{ this.active=false; this.tasks.delete(job.id); });
    this.tasks.set(job.id,task); task.catch(()=>{});
    return this.publicJob(job);
  }
  async run(job, images) {
    try {
      job.state='running'; job.message=images.length ? '正在根据文字编辑参考图…' : '正在根据文字设计角色参考图…'; await this.persist();
      const prompt=referencePrompt(job.prompt,images.length>0,job.taPose,job.style);
      const parameters={model:this.model,prompt,size:'1024x1024',quality:'medium',output_format:'jpeg',output_compression:90,n:1};
      let body=JSON.stringify(parameters); let headers={Authorization:`Bearer ${this.key}`,'Content-Type':'application/json'};
      if(images.length) {
        body=new FormData(); for(const [name,value] of Object.entries(parameters)) body.set(name,String(value));
        for(const image of images) body.append('image[]',image,image.name);
        headers={Authorization:`Bearer ${this.key}`};
      }
      let response;
      try { response=await this.fetcher(`${this.baseURL}/images/${images.length?'edits':'generations'}`,{method:'POST',headers,body,signal:AbortSignal.timeout(600000),redirect:'error'}); }
      catch { throw new ServiceError('图像请求结果未知，请先检查图像服务的任务或用量记录，避免重复生成。'); }
      if(!response.ok) {
        throw new ServiceError(response.status===401?'图像服务密钥无效，请检查本地配置。':response.status===403?'当前账户无权使用此图像模型，请检查模型权限。':response.status===429?'图像服务额度不足或触发限流，请检查账户后再试。':`图像服务请求失败（HTTP ${response.status}），请检查模型与账户状态。`);
      }
      const data=await response.json(); const encoded=data.data?.[0]?.b64_json;
      if(!encoded || encoded.length>8*1024*1024) throw new ServiceError('图像服务未返回可用图片，或图片超过大小限制。');
      const bytes=Buffer.from(encoded,'base64'); const mime=imageType(bytes);
      if(bytes.length>5*1024*1024) throw new ServiceError('生成参考图超过 5 MB，请压缩后作为完成图导入。');
      await writeFile(path.join(this.directory,`${job.id}.image`),bytes);
      job.mime=mime; job.size=bytes.length; job.state='done'; job.message='参考图已完成，请确认形象后再生成 3D。';
    } catch(error) { job.state='failed'; job.message=error instanceof ServiceError?error.message:'图像处理失败，请检查服务后再试。'; }
    await this.persist();
  }
  async importImage(form) {
    const input=validateGeneration(form); const style=referenceStyle(form); const images=input.getAll('images');
    if(images.length!==1) throw new ServiceError('请导入一张已经处理好的最终参考图。',400);
    const bytes=Buffer.from(await images[0].arrayBuffer()); const mime=imageType(bytes);
    const job={id:randomUUID(),state:'done',prompt:String(input.get('prompt')||''),style,inputSignature:String(form.get('inputSignature')||''),source:'manual',model:null,
      createdAt:new Date().toISOString(),message:'已导入完成图，请确认外观。',mime,size:bytes.length};
    await writeFile(path.join(this.directory,`${job.id}.image`),bytes); this.jobs.set(job.id,job); await this.persist(); return this.publicJob(job);
  }
  async image(id) {
    const job=this.jobs.get(id); if(!job || job.state!=='done') throw new ServiceError('参考图尚未准备完成。',409);
    return {bytes:await readFile(path.join(this.directory,`${id}.image`)),mime:job.mime};
  }
}

export async function confirmedRodinInput(form, references) {
  const id=String(form.get('referenceId')||'');
  if(form.get('referenceConfirmed')!=='true' || !id) throw new ServiceError('请先生成或导入参考图，确认外观后再生成 3D。',400);
  const reference=references.get(id);
  const {bytes,mime}=await references.image(id);
  const input=new FormData();
  input.append('images',new Blob([bytes],{type:mime}),`reference-${id}.${mime==='image/png'?'png':mime==='image/webp'?'webp':'jpg'}`);
  input.set('TAPose',form.get('TAPose')==='true'?'true':'false');
  // The confirmed image already contains the semantic edits. Never send the original image(s)
  // or the outfit-editing prompt to Rodin again.
  return { input, provenance:{ referenceId:id, brief:reference.prompt, imageSource:reference.source } };
}
