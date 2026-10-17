import { useEffect, useRef, useState } from 'react';
import { ArrowRight, Download, ExternalLink, Info, LoaderCircle, Move3D, RotateCcw, Settings2 } from 'lucide-react';
import type { CharacterEngine } from '../engine/CharacterEngine';
import type { AssetInfo } from '../types';
import type { RigJob } from '../lib/rig';

const rigTypes: Record<string, string> = { biped: '双足人形', quadruped: '四足动物', hexapod: '六足', octopod: '八足', avian: '鸟类 / 有翼', serpentine: '蛇形', aquatic: '水生', others: '其他骨架' };
type AutoJob = { id: string; state: string; fileName: string; createdAt: string; message: string; progress: number; riggable: boolean | null; recommendedType: string | null; rigType: string | null; modelVersion: string | null; modelUrl: string | null; blenderJobId: string | null; report: { bones: number; skinnedMeshes: number; clips: string[] } | null; credits: { check?: number | null; rig?: number | null } };
type Props = { asset: AssetInfo; engine: CharacterEngine | null; busy: boolean; notify: (message: string) => void; onImport: (bytes: ArrayBuffer, name: string, version?: string) => Promise<void> };
const activeStates = ['uploading', 'submitting-check', 'checking', 'submitting-rig', 'rigging', 'downloading'];
async function data(response: Response) { const body = await response.json(); if (!response.ok) throw new Error(body.error || '本地服务请求失败。'); return body; }

export default function AutoRigPanel({ asset, engine, busy, notify, onImport }: Props) {
  const [configured, setConfigured] = useState(false); const [blender, setBlender] = useState(false); const [setup, setSetup] = useState(false);
  const [balance, setBalance] = useState<number | null>(null);
  const [jobs, setJobs] = useState<AutoJob[]>([]); const [blendJobs, setBlendJobs] = useState<(RigJob & { operation?: string })[]>([]);
  const [choices, setChoices] = useState<Record<string, string>>({}); const [working, setWorking] = useState(''); const [error, setError] = useState('');
  const refreshRef = useRef<() => Promise<void>>(async () => {}); const pollStart = useRef(Date.now());
  useEffect(() => {
    let stopped = false; let timer: ReturnType<typeof setTimeout>;
    fetch('/api/config').then(data).then(async c => { if (!stopped) { setConfigured(Boolean(c.tripoConfigured)); setBlender(Boolean(c.blenderConfigured)); } if (c.tripoConfigured) { const account=await fetch('/api/tripo/account').then(data);if(!stopped)setBalance(account.balance); } }).catch(e => {if(!stopped)setError(e.message);});
    const refresh = async () => {
      try {
        const [auto, local] = await Promise.all([fetch('/api/auto-rigs').then(data), fetch('/api/rigs').then(data)]);
        const list: AutoJob[] = auto.jobs || [];
        const updated = Date.now() - pollStart.current < 20 * 60 * 1000 ? await Promise.all(list.map(j => activeStates.includes(j.state) ? fetch(`/api/auto-rigs/${j.id}`).then(data) : j)) : list;
        if (!stopped) { setJobs(updated); setBlendJobs(local.jobs || []); }
      } catch (e) { if (!stopped) setError((e as Error).message); }
    };
    refreshRef.current = refresh; const poll = async () => { await refresh(); if (!stopped) timer = setTimeout(poll, 3000); }; poll();
    return () => { stopped = true; clearTimeout(timer); };
  }, []);
  const eligible = !asset.bones.length && !asset.clips.length && !asset.morphTargets.length;
  const active = jobs.some(j => activeStates.includes(j.state)); const localActive = blendJobs.some(j => j.state === 'running');
  async function perform(label: string, action: () => Promise<void>) { if (working) return; setWorking(label); setError(''); try { await action(); } catch (e) { setError((e as Error).message); } finally { setWorking(''); } }
  const refresh = () => { pollStart.current = Date.now(); return refreshRef.current(); };
  async function check() { await perform('check', async () => {
    if (!engine) throw new Error('模型尚未就绪。'); const bytes = await engine.exportModel(); if (bytes.byteLength > 150 * 1024 * 1024) throw new Error('Tripo 模型最多 150 MB。');
    const form = new FormData(); form.set('model', new Blob([bytes], { type: 'model/gltf-binary' }), asset.fileName);
    const job = await fetch('/api/auto-rigs', { method: 'POST', body: form }).then(data); setJobs(p => [job, ...p]); notify('已提交 Tripo 预检查，尚未提交绑骨。'); await refresh();
  }); }
  async function bind(job: AutoJob) { await perform(job.id, async () => {
    const form = new FormData(); form.set('rigType', choices[job.id] || job.recommendedType || 'biped');
    const updated = await fetch(`/api/auto-rigs/${job.id}/bind`, { method: 'POST', body: form }).then(data); setJobs(p => p.map(j => j.id === job.id ? updated : j)); await refresh();
  }); }
  async function load(job: AutoJob) { await perform(`load-${job.id}`, async () => {
    const response = await fetch(job.modelUrl!); if (!response.ok) throw new Error('骨骼模型读取失败。'); await onImport(await response.arrayBuffer(), `tripo-${job.id.slice(0, 8)}.glb`, `tripo-${job.rigType}-${job.modelVersion}`);
  }); }
  async function convert(job?: AutoJob) { await perform('blender', async () => {
    let result;
    if (job) result = await fetch(`/api/auto-rigs/${job.id}/blender`, { method: 'POST' }).then(data);
    else { if (!engine) throw new Error('模型尚未就绪。'); const form = new FormData(); form.set('model', new Blob([await engine.exportModel()], { type: 'model/gltf-binary' }), asset.fileName); result = await fetch('/api/rigging/import', { method: 'POST', body: form }).then(data); }
    setBlendJobs(p => [result, ...p.filter(j => j.id !== result.id)]); notify('Blender 正在保留原骨架、权重和已有动画，创建可编辑工程。'); await refresh();
  }); }
  return <>
    <div className="panel-heading"><span><Move3D size={16} />Tripo + Blender</span><span className="tag">自动绑骨</span></div>
    <div className="panel-body auto-rig-panel">
      <p className="section-description">Tripo 预测关节与蒙皮，Blender 做检查和修正。</p>
      <div className="auto-connections"><span><i className={`connection ${configured ? 'ready' : ''}`} />Tripo {configured ? '已配置' : '未配置'}</span><span><i className={`connection ${blender ? 'ready' : ''}`} />Blender {blender ? '就绪' : '未检测到'}</span><button aria-label="Tripo 配置说明" onClick={() => setSetup(v => !v)}><Settings2 size={13} /></button></div>
      {configured && <div className={`tripo-balance ${balance === 0 ? 'empty' : ''}`}><span>API 可用点数：{balance ?? '未读取'}</span><button onClick={async()=>{try{setBalance((await fetch('/api/tripo/account').then(data)).balance);setError('');}catch(e){setError((e as Error).message);}}}>刷新余额</button>{balance === 0 && <p>当前无法提交绑骨。已有预检查结果会保留，补充 API 额度后可继续。</p>}</div>}
      {setup && <div className="reference-setup"><strong>Tripo 本机配置</strong><p>在项目 .env 设置 TRIPO_API_KEY 并重启服务。使用 Tripo 独立密钥；模型上传至 Tripo，预检查与绑骨按其账户规则计费。密钥只由本机后端读取。</p><a href="https://developers.tripo3d.ai/en/docs/animations-rig" target="_blank" rel="noreferrer">官方接口说明<ExternalLink size={11} /></a></div>}
      <div className="rig-step"><span>01</span><strong>识别模型可绑骨性</strong></div>
      {eligible ? <><p className="rig-note">上传当前静态 GLB，先检查是否可绑定、适合哪种骨架。通过后，再单独确认绑骨。</p><button className="button primary full-width" onClick={check} disabled={!configured || active || Boolean(working) || busy}>{working === 'check' || active ? <LoaderCircle className="spin" size={15} /> : <Move3D size={15} />}{active ? 'Tripo 任务进行中…' : '上传当前模型并预检查'}</button></> : <div className="capability-callout"><Info size={15} /><span>当前模型已有骨架、动画或形变。若要测试 Tripo，请先从形象生成记录导入原始静态 GLB。</span></div>}
      <div className="rig-step"><span>02</span><strong>确认骨架，自动绑定</strong></div><p className="rig-note">双足角色使用 Mixamo 骨骼命名；四足等类型使用 Tripo 命名。支持某种骨架不代表每个模型都能正确绑定。</p>
      {error && <p className="rig-error" role="alert">{error}</p>}
      <div className="auto-history-heading"><span>Tripo 任务</span><button onClick={refresh}><RotateCcw size={11} />刷新记录</button></div>
      {!jobs.length && <p className="rig-note">暂无预检查或绑骨任务。</p>}
      <div className="rig-history auto-history">{jobs.slice(0, 6).map(job => <article key={job.id}><strong>{job.state === 'done' ? '绑骨完成 · 待检查' : job.state === 'checked' ? job.riggable ? '预检查通过' : '预检查未通过' : job.state === 'failed' ? '任务未完成' : '处理中'}</strong><small>{job.fileName} · {new Date(job.createdAt).toLocaleString('zh-CN')}</small><p>{job.message}</p>{['checking', 'rigging'].includes(job.state) && <progress max="100" value={job.progress} aria-label="Tripo 任务进度" />}
        {job.state === 'checked' && job.riggable && <><label className="field-label" htmlFor={`rig-type-${job.id}`}>骨架类型</label><select id={`rig-type-${job.id}`} className="text-input" value={choices[job.id] || job.recommendedType || 'biped'} onChange={e => setChoices(p => ({ ...p, [job.id]: e.target.value }))}>{Object.entries(rigTypes).map(([key, value]) => <option key={key} value={key}>{value}{key === job.recommendedType ? ' · 推荐' : ''}</option>)}</select><button className="button primary full-width" disabled={Boolean(working) || active || balance === 0} onClick={() => bind(job)}>确认类型，提交 Tripo 绑骨<ArrowRight size={13} /></button><p className="rig-note">此操作使用 Tripo 账户额度。</p></>}
        {job.report && <p>{job.report.bones} 根骨骼 · {job.report.skinnedMeshes} 个蒙皮网格 · {job.report.clips.length} 段动画</p>}
        {job.modelVersion && <small>{rigTypes[job.rigType || ''] || job.rigType} · {job.modelVersion}</small>}
        {Object.keys(job.credits).length > 0 && <small>服务商报告点数：预检查 {job.credits.check ?? '未返回'} / 绑骨 {job.credits.rig ?? '未返回'}</small>}
        {job.modelUrl && <div className="rig-result-actions"><button disabled={Boolean(working) || busy} onClick={() => load(job)}>导入骨骼模型<ArrowRight size={12} /></button><a href={job.modelUrl} download>下载 GLB</a><button disabled={!blender || localActive || Boolean(working)} onClick={() => convert(job)}>生成 Blender 工程</button></div>}
        {job.blenderJobId && blendJobs.find(b => b.id === job.blenderJobId)?.blendUrl && <a className="blend-download" href={blendJobs.find(b => b.id === job.blenderJobId)!.blendUrl!} download><Download size={12} />下载此结果的 .blend</a>}
      </article>)}</div>
      <div className="rig-step"><span>03</span><strong>Blender 检查与修正</strong></div><p className="rig-note">保留已生成的骨架和权重，打包纹理生成 .blend；不会再套用手工模板。已有蒙皮 GLB 也可以使用。</p><button className="button outline full-width" disabled={!asset.skinnedMeshes || !blender || localActive || Boolean(working) || busy} onClick={() => convert()}>{working === 'blender' || localActive ? <LoaderCircle className="spin" size={14} /> : <Download size={14} />}将当前蒙皮模型转为 .blend</button>
      {blendJobs.filter(j => j.operation === 'inspect').slice(0, 3).map(job => <div className="blend-inspection-result" key={job.id}><strong>{job.state === 'done' ? 'Blender 工程已就绪' : job.state === 'failed' ? '检查未通过' : '正在创建工程'}</strong><small>{job.fileName}</small><p>{job.message}</p>{job.report && <p>{job.report.bones} 根骨骼 · {job.report.unweighted} 个未绑定顶点</p>}{job.blendUrl && <a href={job.blendUrl} download><Download size={12} />下载 Blender 工程</a>}{job.reportUrl && <a href={job.reportUrl} download>检查报告</a>}</div>)}
      <p className="rig-note rig-bottom-note">绑骨不一定附带动画。没有动画片段时，可先下载工程，在 Blender 姿态模式检查。</p>
    </div>
  </>;
}
