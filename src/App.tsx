import { useEffect, useRef, useState } from 'react';
import type { ChangeEvent, ReactNode } from 'react';
import { ArrowDownToLine, ArrowRight, Box, Braces, CheckCheck, ChevronDown, ChevronRight, CircleHelp, Clock3, Download, ExternalLink, FileBox, ImagePlus, Info, Layers3, LoaderCircle, Move3D, Pause, Play, RotateCcw, ScanLine, Settings2, Sparkles, Upload, WandSparkles, X } from 'lucide-react';
import JSZip from 'jszip';
import { CharacterEngine } from './engine/CharacterEngine';
import { DEFAULT_PROJECT } from './types';
import type { AssetInfo, CharacterProject, RodinJob, ReferenceJob } from './types';
import { loadSavedAsset, saveAsset } from './lib/storage';
import { migrateGenerationPrompt, referenceSignature } from './lib/generation-input';
import { REFERENCE_STYLES, readReferenceStyle } from './lib/reference-style';
import { buildAssetReport } from './lib/asset-report';
import ReferencePreparation from './components/ReferencePreparation';
import RiggingPanel from './components/RiggingPanel';
import AutoRigPanel from './components/AutoRigPanel';
import { clipLabel, RIG_VERSION } from './lib/rig';

type View = 'design' | 'rig';
const storageKey = 'mori-project-v1';
function readProject(): CharacterProject {
  try {
    const saved = JSON.parse(localStorage.getItem(storageKey) || 'null'); const { referencePrompt: _legacyPrompt, ...rest } = saved || {};
    return { ...DEFAULT_PROJECT, ...rest, inputVersion: 2, description: migrateGenerationPrompt(saved), referenceStyle: readReferenceStyle(saved?.referenceStyle), appearance: { ...DEFAULT_PROJECT.appearance, ...saved?.appearance }, mapping: { ...DEFAULT_PROJECT.mapping, ...saved?.mapping }, materialColors: saved?.materialColors || {} };
  } catch { return structuredClone(DEFAULT_PROJECT); }
}
function saveFile(bytes: BlobPart, name: string, type = 'application/json') { const url = URL.createObjectURL(new Blob([bytes], { type })); const link = document.createElement('a'); link.href = url; link.download = name; link.click(); setTimeout(() => URL.revokeObjectURL(url), 5000); }
function Tag({ children }: { children: ReactNode }) { return <span className="tag">{children}</span>; }
function PanelHeading({ icon: Icon, title, aside }: { icon: typeof Box; title: string; aside?: ReactNode }) { return <div className="panel-heading"><span><Icon size={16} />{title}</span>{aside}</div>; }

export default function App() {
  const [project, setProject] = useState<CharacterProject>(readProject); const projectRef = useRef(project); projectRef.current = project;
  const [manualTools, setManualTools] = useState(false); const [view, setView] = useState<View>('design'); const stageRef = useRef<HTMLDivElement>(null); const engine = useRef<CharacterEngine | null>(null);
  const [asset, setAsset] = useState<AssetInfo | null>(null); const [busy, setBusy] = useState(''); const [engineError, setEngineError] = useState('');
  const [paused, setPaused] = useState(true); const [wireframe, setWireframe] = useState(false); const [skeleton, setSkeleton] = useState(false); const [selectedClip, setSelectedClip] = useState('');
  const [toast, setToast] = useState(''); const [saved, setSaved] = useState(true); const toastTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const [modal, setModal] = useState<'help' | 'rodin' | 'report' | null>(null); const modalRef = useRef<HTMLElement>(null);
  const [images, setImages] = useState<{ file: File; url: string }[]>([]); const imageRef = useRef(images); imageRef.current = images;
  const [taPose, setTaPose] = useState(true); const [configured, setConfigured] = useState(false); const [submitting, setSubmitting] = useState(false);
  const [jobs, setJobs] = useState<RodinJob[]>([]); const [jobId, setJobId] = useState<string | null>(null); const [showJobs, setShowJobs] = useState(false); const [inputJob, setInputJob] = useState<RodinJob | null>(null);
  const [preparedReference, setPreparedReference] = useState<ReferenceJob | null>(null); const [referencePreview, setReferencePreview] = useState<ReferenceJob | null>(null);
  const fileInput = useRef<HTMLInputElement>(null); const referenceInput = useRef<HTMLInputElement>(null);
  const style = readReferenceStyle(project.referenceStyle); const signature = referenceSignature(project.description, images.map(i => i.file), taPose, style);
  const preparedCurrent = Boolean(preparedReference && preparedReference.inputSignature === signature); const isDemo = asset?.source === 'demo';
  const currentJob = jobs.find(j => j.id === jobId); const report = asset ? buildAssetReport(project, asset) : null;
  const notify = (message: string) => { setToast(message); clearTimeout(toastTimer.current); toastTimer.current = setTimeout(() => setToast(''), 5000); };
  const patch = (value: Partial<CharacterProject>) => setProject(p => ({ ...p, ...value }));

  useEffect(() => {
    if (!stageRef.current) return; let active = true; let instance: CharacterEngine;
    try {
      instance = new CharacterEngine(stageRef.current, projectRef.current.appearance); engine.current = instance; instance.resetPose(); setAsset(instance.info);
      loadSavedAsset().then(async savedAsset => {
        if (!savedAsset || !active) return; setBusy('恢复上次的模型…');
        try { const info = await instance.loadCharacter(savedAsset.bytes, savedAsset.name, savedAsset.source); if (!active) return; for (const [id, color] of Object.entries(projectRef.current.materialColors)) instance.setMaterial(id, color); instance.resetPose(); setAsset(info); setSelectedClip(info.clips[0]?.name || ''); }
        catch { if (active) notify('上次的模型未能恢复，已显示静态示例。'); } finally { if (active) setBusy(''); }
      }).catch(() => {});
    } catch { setEngineError('3D 预览无法启动，请开启浏览器硬件加速。'); }
    return () => { active = false; instance?.dispose(); engine.current = null; clearTimeout(toastTimer.current); };
  }, []);
  useEffect(() => { setSaved(false); const timer = setTimeout(() => { try { localStorage.setItem(storageKey, JSON.stringify(project)); setSaved(true); } catch { notify('草稿未能保存，请导出模型与调试资料。'); } }, 600); return () => clearTimeout(timer); }, [project]);
  useEffect(() => {
    fetch('/api/config').then(r => r.json()).then(c => setConfigured(Boolean(c.rodinConfigured))).catch(() => {});
    fetch('/api/jobs').then(r => r.json()).then(data => { const list: RodinJob[] = data.jobs || []; setJobs(list); setJobId(list.find(j => ['pending', 'running'].includes(j.state))?.id || null); }).catch(() => {});
    return () => imageRef.current.forEach(image => URL.revokeObjectURL(image.url));
  }, []);
  useEffect(() => { if (view === 'rig') { setReferencePreview(null); engine.current?.resetPose(); setPaused(true); engine.current?.setFront(); } }, [view]);
  useEffect(() => {
    if (!modal && !inputJob) return; const previous = document.activeElement as HTMLElement | null; const overflow = document.body.style.overflow; document.body.style.overflow = 'hidden';
    const keydown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') { setModal(null); setInputJob(null); return; } if (event.key !== 'Tab') return;
      const elements = modalRef.current?.querySelectorAll<HTMLElement>('button:not(:disabled),a[href],input,select,textarea,[tabindex="0"]'); if (!elements?.length) return;
      if (event.shiftKey && document.activeElement === elements[0]) { event.preventDefault(); elements[elements.length - 1].focus(); } else if (!event.shiftKey && document.activeElement === elements[elements.length - 1]) { event.preventDefault(); elements[0].focus(); }
    }; document.addEventListener('keydown', keydown); return () => { document.body.style.overflow = overflow; document.removeEventListener('keydown', keydown); previous?.focus(); };
  }, [modal, inputJob]);
  useEffect(() => {
    if (!jobId) return; let stopped = false; let timer: ReturnType<typeof setTimeout>; const start = Date.now();
    const poll = async () => { try {
      const response = await fetch(`/api/jobs/${jobId}`); const job = await response.json(); if (!response.ok) throw new Error(job.error || '查询失败。'); if (stopped) return; setJobs(p => [job, ...p.filter(j => j.id !== job.id)]);
      if (['done', 'failed'].includes(job.state)) { setJobId(null); notify(job.state === 'done' ? '3D 模型已完成，可从记录导入。' : '生成失败，请查看记录。'); return; }
      if (Date.now() - start > 20 * 60 * 1000) { setJobId(null); notify('已暂停查询，可从记录继续查看。'); return; } timer = setTimeout(poll, Math.max(5, job.retryAfter || 10) * 1000);
    } catch (error) { if (!stopped) { setJobId(null); notify((error as Error).message); } } };
    timer = setTimeout(poll, 5000); return () => { stopped = true; clearTimeout(timer); };
  }, [jobId]);

  function showReference(reference: ReferenceJob) { setReferencePreview(reference); requestAnimationFrame(() => document.querySelector('.preview-card')?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })); }
  async function importBytes(bytes: ArrayBuffer, name: string, source: 'import' | 'rodin') {
    if (!engine.current) return; setBusy('正在解析模型…');
    try {
      const info = await engine.current.loadCharacter(bytes, name, source); engine.current.resetPose(); setAsset(info); setReferencePreview(null); setSelectedClip(info.clips[0]?.name || ''); setPaused(true); setWireframe(false); setSkeleton(false);
      patch({ mapping: { ...DEFAULT_PROJECT.mapping }, rigVersion: '待确认', materialColors: {} }); try { await saveAsset({ bytes, name, source }); } catch { notify('模型已加载，浏览器保存失败；请先导出。'); }
      notify(`已载入：${info.bones.length} 根骨骼，${info.skinnedMeshes} 个蒙皮网格。`); return info;
    } catch (error) { notify((error as Error).message || '模型导入失败。'); } finally { setBusy(''); }
  }
  async function importFile(file?: File) { if (!file) return; if (!/\.glb$/i.test(file.name) || file.size > 200 * 1024 * 1024) { notify('请导入不超过 200 MB、包含贴图的单文件 GLB。'); return; } await importBytes(await file.arrayBuffer(), file.name, 'import'); }
  function chooseImages(event: ChangeEvent<HTMLInputElement>) {
    const files = Array.from(event.target.files || []); event.target.value = ''; const valid = files.filter(f => ['image/png', 'image/jpeg', 'image/webp'].includes(f.type) && f.size <= 5 * 1024 * 1024);
    if (valid.length !== files.length) notify('参考图支持 PNG、JPG、WebP，每张不超过 5 MB。'); if (images.length + valid.length > 5) notify('最多保留 5 张参考图。'); setImages(p => [...p, ...valid.slice(0, 5 - p.length).map(file => ({ file, url: URL.createObjectURL(file) }))]);
  }
  async function generate() {
    if (submitting || jobId) return; if (!preparedCurrent || !preparedReference) { notify('请先处理并确认参考图。'); return; } if (!configured) { setModal('rodin'); return; }
    const form = new FormData(); form.set('referenceId', preparedReference.id); form.set('referenceConfirmed', 'true'); form.set('TAPose', String(taPose)); setSubmitting(true);
    try { const response = await fetch('/api/generate', { method: 'POST', body: form }); const data = await response.json(); if (!response.ok) throw new Error(data.error || '提交失败。'); setJobs(p => [data, ...p]); setJobId(data.id); setShowJobs(true); notify('已提交 Rodin，完成后请导入检查模型。'); }
    catch (error) { notify((error as Error).message); } finally { setSubmitting(false); }
  }
  async function loadJob(job: RodinJob) { if (!job.modelUrl || busy) return; setBusy('正在读取模型…'); try { const response = await fetch(job.modelUrl); if (!response.ok) throw new Error('模型读取失败。'); await importBytes(await response.arrayBuffer(), `rodin-${job.id.slice(0, 8)}.glb`, 'rodin'); } catch (error) { notify((error as Error).message); setBusy(''); } }
  async function exportAsset(archive: boolean) {
    if (!engine.current || !asset || busy) return; setBusy('正在导出…');
    try { const bytes = await engine.current.exportModel(); const name = project.name || 'character';
      if (!archive) saveFile(bytes, `${name}.glb`, 'model/gltf-binary');
      else { const zip = new JSZip(); zip.file('character.glb', bytes); zip.file('asset-report.json', JSON.stringify(buildAssetReport(project, asset), null, 2)); zip.file('preview.png', engine.current.screenshot().split(',')[1], { base64: true }); zip.file('rig-debug.md', `# 模型与骨骼调试\n\n源模型：${asset.fileName}\n骨架版本：${project.rigVersion}\n骨骼：${asset.bones.length}；蒙皮网格：${asset.skinnedMeshes}\n\n动画片段：\n${asset.clips.map(c => `- ${c.name} (${c.duration.toFixed(2)}s)`).join('\n') || '无'}\n\n检查肩髋、肘膝、头颈、穿模与道具；零未绑定顶点不代表权重正确。\n此包只包含资产与检查数据。Blender 工程请在骨骼调试记录中单独下载。\n`); saveFile(await zip.generateAsync({ type: 'arraybuffer' }), `${name}-模型调试包.zip`, 'application/zip'); }
      notify(archive ? '模型调试包已导出。' : 'GLB 已导出。');
    } catch (error) { notify((error as Error).message || '导出失败。'); } finally { setBusy(''); }
  }
  function screenshot() { if (!engine.current) return; const bytes = Uint8Array.from(atob(engine.current.screenshot().split(',')[1]), c => c.charCodeAt(0)); saveFile(bytes, `${project.name}-模型预览.png`, 'image/png'); }
  function resetPose() { engine.current?.resetPose(); setPaused(true); }
  async function loadRigged(bytes: ArrayBuffer, name: string, version = RIG_VERSION) { const info = await importBytes(bytes, name, 'import'); if (info) { patch({ rigVersion: version }); engine.current?.showSkeleton(true); setSkeleton(true); } }
  const closeModal = () => { setModal(null); setInputJob(null); };

  return <div className="app-shell focused-workbench">
    <aside className="sidebar"><a className="brand" href="#" onClick={e => { e.preventDefault(); setView('design'); }} aria-label="MORI 工作台首页"><span className="brand-mark"><span>m</span><i /><i /></span><span>MORI<span className="brand-caption">CHARACTER ASSET LAB</span></span></a><div className="workspace-label">模型实验室 <span>LOCAL</span></div>
      <nav aria-label="工作台导航">{([{ id: 'design', icon: Box, title: '形象生成', note: '文字 / 图片到 3D' }, { id: 'rig', icon: Move3D, title: '骨骼调试', note: 'Tripo + Blender' }] as const).map(item => <button key={item.id} aria-label={item.title} title={item.title} className={`nav-item ${view === item.id ? 'active' : ''}`} onClick={() => setView(item.id)}><item.icon size={19} /><span>{item.title}<small>{item.note}</small></span>{view === item.id && <span className="active-dot" />}</button>)}</nav>
      <div className="sidebar-divider" /><div className="sidebar-section-heading">当前模型 <span>01</span></div><div className="character-mini"><span className="mini-avatar"><FileBox size={20} /></span><span>{project.name || '未命名'}<small>{isDemo ? '静态示例 · 等待导入' : asset?.fileName || '正在读取'}</small></span></div><div className="sidebar-bottom"><div className="team-note"><span className="tiny-stars">✧</span><p>先把形象与骨架，<br />做成可靠的资产。</p></div><button className="plain-button help-button" onClick={() => setModal('help')}><CircleHelp size={17} />当前流程说明<ArrowRight size={14} /></button><div className="local-indicator"><span />本地模型实验室 <span className="version">v0.2</span></div></div>
    </aside>
    <main className="workspace"><header className="topbar"><div className="breadcrumb">模型实验室<ChevronRight size={13} /><strong>{view === 'design' ? '形象生成' : '骨骼调试'}</strong></div><div className="topbar-actions"><span className="save-status"><CheckCheck size={14} />{saved ? '草稿已保存' : '正在保存…'}</span><button className="icon-button" aria-label="当前流程说明" onClick={() => setModal('help')}><CircleHelp size={18} /></button></div></header>
      <div className="page-content"><section className="page-intro"><div><div className="eyebrow">CHARACTER GENERATION & RIG LAB</div><h1>{view === 'design' ? '从一个形象，到 3D。' : '让骨架，贴合形象。'}<span className="heading-star">✳</span></h1><p>{view === 'design' ? '输入文字或图片，确认目标风格，再生成可检查的三维模型。' : 'Tripo 自动识别与绑骨，Blender 检查与修正。'}</p></div><button className="button dark export-top" onClick={() => exportAsset(false)} disabled={Boolean(busy) || !asset}><ArrowDownToLine size={16} />导出 GLB</button></section>
        <div className="workflow-strip">{[{ number: '01', label: '文字 / 图片' }, { number: '02', label: '风格迁移' }, { number: '03', label: '3D 模型' }, { number: '04', label: '骨骼调试' }].map((step, i) => <div className="workflow-step" key={step.number}><button onClick={() => setView(i === 3 ? 'rig' : 'design')} className={(view === 'rig' ? i === 3 : i < 3) ? 'current' : ''}><span>{step.number}</span>{step.label}</button>{i < 3 && <div className="workflow-line" />}</div>)}</div>
        <div className={`workbench-grid view-${view}`}>
          <section className="creation-panel card">{view === 'design' ? <><PanelHeading icon={WandSparkles} title="输入与目标风格" aside={<Tag>01 → 03</Tag>} /><div className="panel-body">
            <label className="field-label" htmlFor="character-name">模型名称</label><input className="text-input name-input" id="character-name" value={project.name} maxLength={40} onChange={e => patch({ name: e.target.value })} placeholder="为模型命名" /><p className="input-introduction">至少提供文字或参考图，也可以一起输入。</p>
            <label className="field-label" htmlFor="description">形象描述<span>可选</span></label><div className="prompt-wrap"><textarea id="description" maxLength={1024} value={project.description} onChange={e => patch({ description: e.target.value })} placeholder="描述角色种类、体型、颜色与想保留的特征…" /><span className={`character-count ${project.description.trim().length > 1024 ? 'over-limit' : ''}`}>{project.description.trim().length} / 1024</span></div>
            <label className="field-label">参考图片<span>可选 · {images.length} / 5</span></label><button className="reference-drop unified-reference-drop" onClick={() => referenceInput.current?.click()}><ImagePlus size={22} /><strong>{images.length ? '继续添加参考图' : '添加角色参考图'}</strong><span>PNG / JPG / WebP · 每张最多 5 MB</span></button>{images.length > 0 && <div className="reference-images">{images.map((image, i) => <div key={image.url}><img src={image.url} alt={`参考图 ${i + 1}：${image.file.name}`} /><button aria-label={`移除参考图 ${i + 1}`} onClick={() => { URL.revokeObjectURL(image.url); setImages(p => p.filter((_, index) => i !== index)); }}><X size={11} /></button></div>)}</div>}<p className="fine-print">多图应为同一角色；绑骨参考图应四肢清楚、道具较少。</p>
            <label className="field-label" htmlFor="target-style">目标风格<span>先在二维图上确认</span></label><select className="text-input" id="target-style" value={style} onChange={e => patch({ referenceStyle: readReferenceStyle(e.target.value) })}>{Object.entries(REFERENCE_STYLES).map(([key, value]) => <option key={key} value={key}>{value.label}</option>)}</select><p className="style-description">{REFERENCE_STYLES[style].description}</p><label className="checkbox-label"><input type="checkbox" checked={taPose} onChange={e => setTaPose(e.target.checked)} /><span>优先生成便于绑骨的 T / A 姿态</span></label><p className="fine-print">姿态条件不包含骨架识别或蒙皮。</p>
            <ReferencePreparation prompt={project.description} images={images.map(i => i.file)} taPose={taPose} style={style} onReady={setPreparedReference} onPreview={showReference} notify={notify} />
            <div className="preparation-heading rodin-step-heading"><span>03</span><strong>确认风格图，生成模型</strong></div><button className="button primary generate-button" onClick={generate} disabled={submitting || Boolean(jobId) || !preparedCurrent}>{submitting || jobId ? <LoaderCircle size={15} className="spin" /> : <Sparkles size={15} />}{submitting ? '正在提交…' : jobId ? '3D 模型生成中…' : '确认参考图，生成 3D'}<ArrowRight size={14} /></button><div className="generation-footnote"><span className={configured ? 'connection ready' : 'connection'} /><span>{configured ? 'Rodin 已连接 · 生成使用账户额度' : '需配置 Rodin'}</span><button aria-label="Rodin 配置说明" onClick={() => setModal('rodin')}><Settings2 size={13} /></button></div>
            {jobs.length > 0 && <div className="job-summary"><button onClick={() => setShowJobs(v => !v)}><Clock3 size={13} />{currentJob?.stage || `${jobs.length} 条模型生成记录`}<ChevronDown size={13} /></button>{showJobs && <div className="job-list">{jobs.map(job => <div className="job-item" key={job.id}><span><strong>{job.stage}</strong><small>{new Date(job.createdAt).toLocaleString('zh-CN')}</small>{job.message && <small>{job.message}</small>}<button className="job-input-link" onClick={() => setInputJob(job)}>查看输入</button></span>{job.state === 'done' ? <button disabled={Boolean(busy)} onClick={() => loadJob(job)}>导入</button> : job.state !== 'failed' ? <button disabled={Boolean(jobId)} onClick={() => setJobId(job.id)}>查询</button> : <Tag>失败</Tag>}</div>)}</div>}</div>}
            <div className="or-divider"><span />使用已有模型<span /></div><button className="button outline full-width" onClick={() => fileInput.current?.click()} disabled={Boolean(busy)}><Upload size={14} />导入 GLB 模型</button>
          </div></> : asset && <><AutoRigPanel asset={asset} engine={engine.current} busy={Boolean(busy)} notify={notify} onImport={loadRigged} /><details className="manual-rig-tools" open={manualTools} onToggle={e => setManualTools(e.currentTarget.open)}><summary>备用：手动模板与 Blender 蒙皮</summary>{manualTools && <RiggingPanel key={`${asset.fileName}-${asset.size}`} asset={asset} engine={engine.current} busy={Boolean(busy)} notify={notify} onImport={loadRigged} />}</details></>}</section>
          <section className="preview-column">
            <div className={`preview-card card ${referencePreview ? 'previewing-reference' : ''}`} onDragOver={e => e.preventDefault()} onDrop={e => { e.preventDefault(); if (!busy) importFile(e.dataTransfer.files[0]); }}>
              <div className="preview-topline"><div className="preview-label">{referencePreview ? <ImagePlus size={14} /> : <Box size={14} />}<span>{referencePreview ? '风格图预览 · 确认后生成 3D' : '3D 模型预览'}</span></div>{referencePreview ? <button className="reference-view-toggle" onClick={() => setReferencePreview(null)}>查看当前 3D<ArrowRight size={12} /></button> : <Tag>{isDemo ? '静态示例 · 非生成结果' : '当前模型'}</Tag>}</div><div className="stage" ref={stageRef} />
              {referencePreview?.imageUrl && <div className="reference-image-overlay"><img src={referencePreview.imageUrl} alt="供确认的风格迁移参考图" /><div><span>STYLE REFERENCE BEFORE 3D</span><p>先确认轮廓、质感与四肢，再提交 Rodin。</p><a href={referencePreview.imageUrl} target="_blank" rel="noreferrer">查看原图<ExternalLink size={11} /></a></div></div>}
              <div className="stage-grain" /><div className="stage-side-tools"><button className="icon-button" aria-label="重置视角" onClick={() => engine.current?.resetView()}><RotateCcw size={16} /></button><button className="icon-button" aria-label="正面视角" onClick={() => engine.current?.setFront()}><ScanLine size={16} /></button><button className="icon-button" aria-label="保存模型预览图" onClick={screenshot}><ArrowDownToLine size={16} /></button></div><div className="stage-name"><span className="status-dot" /><strong>{project.name || '未命名模型'}</strong><span>{isDemo ? '请生成或导入自己的模型' : asset?.fileName}</span></div><div className="stage-toolbar"><div className="view-toggles"><button className={wireframe ? 'on' : ''} onClick={() => { setWireframe(v => !v); engine.current?.setWireframe(!wireframe); }}><Layers3 size={13} />线框</button><button className={skeleton ? 'on' : ''} disabled={!asset?.bones.length} onClick={() => { setSkeleton(v => !v); engine.current?.showSkeleton(!skeleton); }}><Move3D size={13} />骨骼</button></div><span>拖动旋转 · 滚轮缩放</span></div>{(busy || engineError) && <div className="stage-overlay">{busy ? <><LoaderCircle size={24} className="spin" /><span>{busy}</span></> : <p>{engineError}</p>}</div>}
            </div>
            <section className="card model-inspection"><PanelHeading icon={FileBox} title="模型检查" aside={<button className="icon-button" aria-label="查看模型数据" onClick={() => setModal('report')}><Braces size={14} /></button>} /><div className="inspector-body"><div className="model-metrics">{[['三角面', asset?.triangles.toLocaleString() || '—'], ['骨骼', asset?.bones.length ?? '—'], ['蒙皮网格', asset?.skinnedMeshes ?? '—'], ['动画片段', asset?.clips.length ?? '—']].map(([label, value]) => <div key={label}><span>{label}</span><strong>{value}</strong></div>)}</div><p className="inspection-note">{isDemo ? '静态占位示例。请先生成或导入待调试的 GLB。' : asset?.skinnedMeshes ? '检测到骨骼与蒙皮。仍需检查肩髋、肘膝及头颈变形。' : '当前是静态资产，尚未绑定骨骼。'}</p><div className="inspection-actions"><button onClick={() => setView(view === 'design' ? 'rig' : 'design')}>{view === 'design' ? '进入骨骼调试' : '返回形象生成'}<ArrowRight size={12} /></button><button onClick={() => fileInput.current?.click()} disabled={Boolean(busy)}><Upload size={12} />导入 GLB</button><button onClick={() => exportAsset(true)} disabled={!asset || Boolean(busy)}><Download size={12} />导出调试包</button></div></div></section>
            {view === 'rig' && <><section className="card"><PanelHeading icon={Play} title="变形测试" aside={<Tag>手动试播</Tag>} /><div className="inspector-body">{asset?.clips.length ? <><label className="field-label" htmlFor="test-clip">模型自带动画</label><select id="test-clip" className="text-input" value={selectedClip} onChange={e => { setSelectedClip(e.target.value); resetPose(); }}>{asset.clips.map(clip => <option key={clip.name} value={clip.name}>{clipLabel(clip.name)} · {clip.duration.toFixed(1)}s</option>)}</select><div className="rig-playback"><button className="button primary" onClick={() => { engine.current?.playClip(selectedClip); setPaused(false); }} disabled={Boolean(busy)}><Play size={13} />播放片段</button><button className="button outline" onClick={() => { engine.current?.setPaused(!paused); setPaused(v => !v); }} disabled={!selectedClip || Boolean(busy)}>{paused ? <Play size={13} /> : <Pause size={13} />}{paused ? '继续' : '暂停'}</button><button className="button outline" onClick={resetPose} disabled={Boolean(busy)}><RotateCcw size={13} />还原姿态</button></div><p className="inspection-note">试播用于发现扭曲、穿模与错误权重。</p></> : <p className="inspection-note">当前没有动画。可导入带动画 GLB，或在 Blender 中制作测试动作。</p>}</div></section><section className="card"><PanelHeading icon={Move3D} title="骨骼层级" aside={<Tag>{asset?.bones.length || 0} 根</Tag>} /><div className="inspector-body">{asset?.bones.length ? <details className="bone-tree"><summary>展开真实骨骼与父节点</summary><ul>{asset.bones.map((bone, i) => <li key={`${bone.name}-${i}`}><code>{bone.name}</code><span>← {bone.parent || '场景根节点'}</span></li>)}</ul></details> : <p className="inspection-note">尚未检测到骨骼。</p>}</div></section></>}
          </section>
        </div><footer className="workspace-footer"><span>MORI ASSET LAB · 生成与骨骼调试</span><span>TEXT / IMAGE → STYLE → 3D → RIG</span></footer>
      </div>
    </main>
    <input hidden ref={fileInput} type="file" accept=".glb" onChange={e => { importFile(e.target.files?.[0]); e.target.value = ''; }} /><input hidden ref={referenceInput} type="file" accept="image/png,image/jpeg,image/webp" multiple onChange={chooseImages} />{toast && <div className="toast" role="status"><Info size={16} /><span>{toast}</span><button aria-label="关闭提示" onClick={() => setToast('')}><X size={14} /></button></div>}
    {(modal || inputJob) && <div className="modal-backdrop" onClick={closeModal}><section className="modal" ref={modalRef} role="dialog" aria-modal="true" aria-labelledby="modal-title" onClick={e => e.stopPropagation()}><button className="modal-close icon-button" autoFocus aria-label="关闭对话框" onClick={closeModal}><X size={19} /></button>{inputJob ? <><span className="eyebrow">GENERATION INPUT</span><h2 id="modal-title">模型生成输入</h2><p>处理后的参考图已包含风格；Rodin 只读取确认图。</p><div className="input-receipt"><label>原始描述</label><pre>{inputJob.input?.preparation?.brief || inputJob.input?.prompt || inputJob.prompt || '未提供文字'}</pre><label>提交的参考图</label>{inputJob.input ? <ul>{inputJob.input.images.map((image, i) => <li key={i}>{image.name}<small>{(image.size / 1024).toFixed(1)} KB</small></li>)}</ul> : <p>旧任务未记录图片信息。</p>}</div></> : modal === 'rodin' ? <><h2 id="modal-title">Rodin 连接</h2><p>在项目 .env 设置 RODIN_API_KEY 并重启本地服务。图像服务与 Rodin 分别计费，密钥只由本机后端读取。</p></> : modal === 'help' ? <><h2 id="modal-title">先完成形象与骨架</h2><ol className="focused-help"><li>提供文字、图片，或同时提供两者。</li><li>选择风格，先生成并确认二维参考图。</li><li>用确认图生成 3D 模型，检查轮廓与四肢。</li><li>Tripo 预检查与绑骨，再用 Blender 修正。</li></ol><p>骨骼变形需视觉验收。当前工作台聚焦模型资产；桌面运行、互动与换装暂不包含在内。</p></> : <><h2 id="modal-title">模型与骨骼数据</h2><pre className="manifest-json">{JSON.stringify(report, null, 2)}</pre><button className="button primary full-width" onClick={() => saveFile(JSON.stringify(report, null, 2), 'asset-report.json')}><Download size={14} />下载骨骼报告</button></>}</section></div>}
  </div>;
}
