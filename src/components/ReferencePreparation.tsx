import { useEffect, useRef, useState } from 'react';
import { ArrowRight, Check, ChevronDown, ImagePlus, Info, LoaderCircle, Settings2, Sparkles, Upload } from 'lucide-react';
import type { ReferenceJob } from '../types';
import { buildGenerationForm, referenceSignature } from '../lib/generation-input';
import { REFERENCE_STYLES, readReferenceStyle } from '../lib/reference-style';
import type { ReferenceStyle } from '../lib/reference-style';

type Props = { prompt: string; images: File[]; taPose: boolean; style: ReferenceStyle; onReady: (reference: ReferenceJob | null) => void; onPreview: (reference: ReferenceJob) => void; notify: (message: string) => void };
export default function ReferencePreparation({ prompt, images, taPose, style, onReady, onPreview, notify }: Props) {
  const [configured,setConfigured]=useState(false); const [host,setHost]=useState(''); const [model,setModel]=useState('');
  const [jobs,setJobs]=useState<ReferenceJob[]>([]); const [active,setActive]=useState<string|null>(null);
  const [selected,setSelected]=useState<ReferenceJob|null>(null); const [accepted,setAccepted]=useState('');
  const [submitting,setSubmitting]=useState(false); const [setup,setSetup]=useState(false); const [history,setHistory]=useState(false);
  const fileInput=useRef<HTMLInputElement>(null);
  const signature=referenceSignature(prompt,images,taPose,style);
  const handlers=useRef({onReady,onPreview,notify}); handlers.current={onReady,onPreview,notify};
  const currentSignature=useRef(signature); currentSignature.current=signature;
  const ready=selected?.state==='done' && (selected.inputSignature===signature || accepted===signature);
  useEffect(()=>{ handlers.current.onReady(ready && selected ? {...selected,inputSignature:signature} : null); },[ready,selected,signature]);
  useEffect(()=>{
    fetch('/api/config').then(r=>r.json()).then(c=>{setConfigured(Boolean(c.imageConfigured));setHost(c.imageHost||'');setModel(c.imageModel||'');}).catch(()=>{});
    fetch('/api/references').then(r=>r.json()).then(data=>{
      const list:ReferenceJob[]=data.references||[];setJobs(list);
      const running=list.find(j=>['pending','running'].includes(j.state)); if(running) setActive(running.id);
      const previous=list.find(j=>j.state==='done' && j.inputSignature===currentSignature.current);
      if(previous) {setSelected(previous);handlers.current.onPreview(previous);}
    }).catch(()=>{});
  },[]);
  useEffect(()=>{
    if(!active)return; let cancelled=false; let timer:ReturnType<typeof setTimeout>; const started=Date.now();
    const poll=async()=>{
      try {
        const response=await fetch(`/api/references/${active}`); const job:ReferenceJob & {error?:string}=await response.json();
        if(!response.ok)throw new Error(job.error||'参考图查询失败。'); if(cancelled)return;
        setJobs(previous=>[job,...previous.filter(j=>j.id!==job.id)]);
        if(job.state==='done'){setSelected(job);setAccepted('');handlers.current.onPreview(job);setActive(null);handlers.current.notify('参考图已完成。请先确认外观，再生成 3D。');return;}
        if(job.state==='failed'){setActive(null);handlers.current.notify(job.message);return;}
        if(Date.now()-started>12*60*1000){setActive(null);handlers.current.notify('参考图查询已暂停，可从记录继续查看；不要重复提交相同任务。');return;}
        timer=setTimeout(poll,2500);
      }catch(error){if(!cancelled){setActive(null);handlers.current.notify((error as Error).message);}}
    };
    timer=setTimeout(poll,1200);return()=>{cancelled=true;clearTimeout(timer);};
  },[active]);
  async function prepare(){
    if(active||submitting)return;
    let form:FormData;try{form=buildGenerationForm(prompt,images,taPose,style);}catch(error){notify((error as Error).message);return;}
    if(!configured){setSetup(true);return;}
    form.set('inputSignature',signature);setSubmitting(true);
    try{
      const response=await fetch('/api/references/prepare',{method:'POST',body:form});const job=await response.json();
      if(!response.ok)throw new Error(job.error||'参考图提交失败。');
      setJobs(previous=>[job,...previous]);setActive(job.id);setAccepted('');notify('已提交图像处理。完成后会先展示参考图。');
    }catch(error){notify((error as Error).message);}finally{setSubmitting(false);}
  }
  async function importFinal(file?:File){
    if(!file)return;if(!['image/png','image/jpeg','image/webp'].includes(file.type)||file.size>5*1024*1024){notify('请选择不超过 5 MB 的 PNG、JPG 或 WebP。');return;}
    const form=new FormData();form.append('images',file);if(prompt.trim())form.set('prompt',prompt.trim());form.set('style',style);form.set('inputSignature',signature);setSubmitting(true);
    try{
      const response=await fetch('/api/references/import',{method:'POST',body:form});const job=await response.json();
      if(!response.ok)throw new Error(job.error||'参考图导入失败。');setSelected(job);setAccepted('');setJobs(previous=>[job,...previous]);onPreview(job);notify('完成图已导入。确认外观后即可生成 3D。');
    }catch(error){notify((error as Error).message);}finally{setSubmitting(false);}
  }
  const current=jobs.find(j=>j.id===active);
  return <section className="reference-preparation">
    <div className="preparation-heading"><span>02</span><strong>风格迁移与参考图</strong></div>
    <button className="button primary full-width" onClick={prepare} disabled={submitting||Boolean(active)||(!prompt.trim()&&!images.length)}>{submitting||active?<LoaderCircle size={15} className="spin"/>:<Sparkles size={15}/>}{submitting?'正在提交…':active?'参考图处理中…':images.length?'按目标风格处理参考图':'按目标风格生成参考图'}<ArrowRight size={14}/></button>
    <div className="generation-footnote"><span className={configured?'connection ready':'connection'}/><span>{configured?`图像服务已连接 · ${host}`:'配置图像服务后开启生成'}<small>{configured?model:''}</small></span><button aria-label="图像服务配置说明" onClick={()=>setSetup(!setup)}><Settings2 size={13}/></button></div>
    {setup&&<div className="reference-setup"><strong>图像服务配置</strong><p>在项目 .env 中填写以下配置，重启服务。兼容中转站需同时设置它的 /v1 地址。</p><pre>OPENAI_API_KEY=你的生图密钥{'\n'}OPENAI_BASE_URL=https://你的服务/v1{'\n'}OPENAI_IMAGE_MODEL=可用图像模型</pre><p>图像服务与 Rodin 分别计费；密钥只由本机后端读取。</p></div>}
    {current&&<p className="preparation-status"><LoaderCircle size={11} className="spin"/>{current.message}</p>}
    <button className="import-final-reference" onClick={()=>fileInput.current?.click()} disabled={submitting||Boolean(active)}><Upload size={12}/>导入已处理好的参考图</button>
    <input hidden ref={fileInput} type="file" accept="image/png,image/jpeg,image/webp" onChange={e=>{importFinal(e.target.files?.[0]);e.target.value='';}}/>
    {selected?.state==='done'&&<div className={`prepared-reference ${ready?'ready':''}`}><button className="prepared-thumbnail" onClick={()=>onPreview(selected)}><img src={selected.imageUrl!} alt="待确认的最终角色参考图"/><ImagePlus size={13}/></button><div><strong>{ready?'参考图已就绪':'参考图来自其他输入'}</strong><p>{ready?`本图记录：${REFERENCE_STYLES[readReferenceStyle(selected.style)].label}。请确认轮廓与质感。`:'输入、风格或姿态已变更，请重新处理，或明确使用这张完成图。'}</p><button onClick={()=>onPreview(selected)}>查看大图<ArrowRight size={10}/></button></div>{!ready&&<button className="button outline full-width use-completed" onClick={()=>{setAccepted(signature);onPreview(selected);}}>以这张完成图为准<Check size={12}/></button>}</div>}
    {jobs.length>0&&<div className="reference-history"><button onClick={()=>setHistory(!history)}>参考图记录 · {jobs.length}<ChevronDown size={11}/></button>{history&&<div>{jobs.slice(0,8).map(job=><div key={job.id}><span>{job.state==='done'?'参考图已完成':job.state==='failed'?'处理失败':'正在处理'}<small>{new Date(job.createdAt).toLocaleString('zh-CN')}</small>{job.state==='failed'&&<small>{job.message}</small>}</span>{job.state==='done'?<button onClick={()=>{setSelected(job);setAccepted('');onPreview(job);}}>查看</button>:['pending','running'].includes(job.state)?<button onClick={()=>setActive(job.id)}>查询</button>:null}</div>)}</div>}</div>}
    <p className="preparation-note"><Info size={11}/>这一步仅生成二维图片，不会自动调用 Rodin。</p>
  </section>;
}
