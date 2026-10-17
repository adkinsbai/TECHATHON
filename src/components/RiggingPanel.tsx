import { useEffect, useState } from 'react';
import { ArrowRight, Check, Download, Info, LoaderCircle, Move3D, RotateCcw } from 'lucide-react';
import JSZip from 'jszip';
import type { AssetInfo } from '../types';
import type { CharacterEngine } from '../engine/CharacterEngine';
import { defaultRig, jointLabel, RIG_BONES } from '../lib/rig';
import type { RigJob, RigPoint, RigSettings } from '../lib/rig';

type Props = { asset: AssetInfo; engine: CharacterEngine | null; busy: boolean; notify: (message: string) => void; onImport: (bytes: ArrayBuffer, name: string) => Promise<void> };
export default function RiggingPanel({ asset, engine, busy, notify, onImport }: Props) {
  const storageKey = `mori-rig-${asset.fileName}-${asset.size}`;
  const [settings, setSettings] = useState<RigSettings>(() => {
    try { const saved = JSON.parse(localStorage.getItem(storageKey) || 'null'); if (saved?.version === defaultRig().version && Object.keys(defaultRig().points).every(k => Array.isArray(saved.points?.[k]) && saved.points[k].length === 3 && saved.points[k].every(Number.isFinite))) return { ...saved, weightMode: saved.weightMode || 'heat' }; } catch {}
    return defaultRig();
  });
  const [selected, setSelected] = useState('hips'); const [mirror, setMirror] = useState(true);
  const [configured, setConfigured] = useState(false); const [jobs, setJobs] = useState<RigJob[]>([]);
  const [working, setWorking] = useState(false); const [allJobs, setAllJobs] = useState(false);
  const eligible = !asset.bones.length && !asset.clips.length && !asset.morphTargets.length;
  const running = jobs.some(j => j.state === 'running');
  const [error, setError] = useState('');
  useEffect(() => {
    fetch('/api/config').then(r => r.json()).then(c => setConfigured(Boolean(c.blenderConfigured))).catch(() => setError('本地服务无法连接。'));
    let stopped = false; let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try { const response = await fetch('/api/rigs'); const data = await response.json(); if (!response.ok) throw new Error(data.error || '绑定记录读取失败。'); if (!stopped) { setJobs(data.jobs || []); setError(''); } }
      catch (e) { if (!stopped) setError((e as Error).message); }
      if (!stopped) timer = setTimeout(poll, 3000);
    };
    poll(); return () => { stopped = true; clearTimeout(timer); };
  }, []);
  useEffect(() => { try { localStorage.setItem(storageKey, JSON.stringify(settings)); } catch {} }, [settings, storageKey]);
  useEffect(() => {
    if (eligible) { engine?.setPaused(true); engine?.setRigGuides(settings, selected); if (engine) engine.onRigPoint = setSelected; }
    return () => { engine?.setRigGuides(null); if (engine) engine.onRigPoint = undefined; };
  }, [settings, selected, engine, eligible]);
  function move(axis: number, value: number) {
    setSettings(previous => {
      const point = [...previous.points[selected]] as RigPoint; point[axis] = value;
      const points = { ...previous.points, [selected]: point };
      if (mirror && /\.[LR]$/.test(selected)) { const other = selected.replace(/\.([LR])$/, (_, side) => side === 'L' ? '.R' : '.L'); points[other] = [-point[0], point[1], point[2]]; }
      return { ...previous, points };
    });
  }
  async function modelBytes() { if (!engine) throw new Error('3D 引擎尚未就绪。'); return engine.exportModel(); }
  async function bind() {
    setWorking(true); setError('');
    try {
      const bytes = await modelBytes(); const form = new FormData();
      form.set('model', new Blob([bytes], { type: 'model/gltf-binary' }), asset.fileName); form.set('settings', JSON.stringify(settings));
      const response = await fetch('/api/rigs', { method: 'POST', body: form }); const data = await response.json();
      if (!response.ok) throw new Error(data.error || '提交绑定失败。');
      setJobs(previous => [data, ...previous.filter(j => j.id !== data.id)]); notify('已交给本机 Blender 绑定，可在这里查看结果。');
    } catch (e) { setError((e as Error).message); } finally { setWorking(false); }
  }
  async function kit() {
    setWorking(true); setError('');
    try {
      const bytes = await modelBytes(); const response = await fetch('/api/rigging/script'); if (!response.ok) throw new Error('绑定脚本读取失败。');
      const zip = new JSZip(); zip.file('input.glb', bytes); zip.file('rig.json', JSON.stringify({ ...settings, bones: RIG_BONES }, null, 2)); zip.file('rig_character.py', await response.text());
      zip.file('README.txt', 'MORI Blender 绑定包\n\n使用 Blender 4.5 LTS。在本目录执行：\nblender --background --factory-startup --disable-autoexec --python-exit-code 1 --python rig_character.py -- .\n\n输出 character.blend、character-rigged.glb、report.json。此脚本仅适用于静态双足站立角色；先在工作台对齐关节，检查自动权重和试动作。\n坐标：GLB +Y 向上、+Z 向前；Blender +Z 向上、-Y 向前。\n骨架版本 mori-biped-v1。无脸部、手指、耳尾专用骨；测试片段不代表最终互动动画。\n');
      const blob = await zip.generateAsync({ type: 'blob' }); const url = URL.createObjectURL(blob); const a = document.createElement('a'); a.href = url; a.download = 'mori-blender-kit.zip'; a.click(); setTimeout(() => URL.revokeObjectURL(url), 5000);
      notify('已下载模型、关节配置和 Blender 脚本。');
    } catch (e) { setError((e as Error).message); } finally { setWorking(false); }
  }
  async function load(job: RigJob) {
    if (!job.modelUrl) return; setWorking(true);
    try { const response = await fetch(job.modelUrl); if (!response.ok) throw new Error('绑定模型读取失败。'); await onImport(await response.arrayBuffer(), `rigged-${job.id.slice(0, 8)}.glb`); }
    catch (e) { setError((e as Error).message); } finally { setWorking(false); }
  }
  return <>
    <div className="panel-heading"><span><Move3D size={16} />Blender 骨骼绑定</span><span className="tag">双足 · V1</span></div>
    <div className="panel-body rig-panel">
      <p className="section-description">对齐关节，让静态形象成为能制作动作的角色。</p>
      <div className="rig-connection"><span className={`connection ${configured ? 'ready' : ''}`} />{configured ? '本机 Blender 已就绪 · 无 API 费用' : '未检测到 Blender'}</div>
      {!configured && <p className="rig-note">可先下载绑定包，在 Blender 4.5 LTS 中运行。配置本机 Blender 后可直接绑定。</p>}
      {eligible ? <>
        <div className="rig-step"><span>01</span><strong>确认模型朝向</strong></div>
        <p className="rig-note">正面应朝向屏幕。旋转模型后再对齐关节。</p>
        <div className="rig-yaw">{[0, 90, 180, 270].map(yaw => <button key={yaw} className={settings.yaw === yaw ? 'chosen' : ''} onClick={() => setSettings(s => ({ ...s, yaw }))}>{yaw}°</button>)}</div>
        <div className="rig-view-buttons"><button onClick={() => engine?.setFront()}>正面检查</button><button onClick={() => engine?.setSide()}>侧面检查</button></div>
        <div className="rig-step"><span>02</span><strong>对齐骨骼关节</strong></div>
        <p className="rig-note">蓝点是关节，橙点是当前选择。可点选 3D 中的关节；数值是相对身高的位置。左 / 右以角色自身为准。</p>
        <label className="field-label" htmlFor="rig-joint">当前关节</label><select className="text-input" id="rig-joint" value={selected} onChange={e => setSelected(e.target.value)}>{Object.keys(settings.points).map(key => <option key={key} value={key}>{jointLabel(key)}</option>)}</select>
        <div className="rig-coordinates">{['左右 X', '高度 Y', '前后 Z'].map((name, axis) => <label key={name}><span>{name}</span><input aria-label={`${jointLabel(selected)}${name}`} type="range" min={axis === 1 ? 0 : -0.65} max={axis === 1 ? 1.2 : .65} step="0.005" value={settings.points[selected][axis]} onChange={e => move(axis, Number(e.target.value))} /><input aria-label={`${jointLabel(selected)}${name}数值`} type="number" min={axis === 1 ? 0 : -1} max={axis === 1 ? 1.2 : 1} step="0.005" value={settings.points[selected][axis]} onChange={e => { const value = e.target.valueAsNumber; if (Number.isFinite(value)) move(axis, value); }} /></label>)}</div>
        <label className="checkbox-label"><input type="checkbox" checked={mirror} onChange={e => setMirror(e.target.checked)} /><span>左右关节对称调整</span></label>
        <button className="reset-appearance" onClick={() => setSettings(defaultRig())}><RotateCcw size={12} />重置关节与朝向</button>
        <div className="rig-step"><span>03</span><strong>绑定并检查变形</strong></div>
        <p className="rig-note">19 根基础骨骼 · 3 段试动作。适合四肢分开的双足角色；衣服、道具和大头比例需要重点检查。</p>
        <label className="field-label" htmlFor="weight-mode">初始蒙皮方式</label><select className="text-input" id="weight-mode" value={settings.weightMode} onChange={e => setSettings(s => ({ ...s, weightMode: e.target.value as RigSettings['weightMode'] }))}><option value="heat">Blender 骨热 · 先尝试自动权重</option><option value="distance">距离蒙皮 · 失败时的初始方案</option></select>
        <p className="rig-note">{settings.weightMode === 'distance' ? '按最近骨段生成平滑初始权重，不识别衣物或肢体语义，需要在 Blender 中修正。' : '先焊接重合顶点，再计算 Blender 原生自动权重；UV 与材质保留。失败时可改用距离蒙皮。'}</p>
        <button className="button primary full-width" onClick={bind} disabled={!configured || running || working || busy}>{working || running ? <LoaderCircle size={15} className="spin" /> : <Move3D size={15} />}{running ? 'Blender 正在绑定…' : working ? '正在准备…' : '用 Blender 绑定骨骼'}</button>
        <button className="button outline full-width rig-kit" disabled={working || busy} onClick={kit}><Download size={14} />下载 Blender 绑定包</button>
      </> : <div className="capability-callout"><Info size={16} /><span>此模型已有骨架、动画或形变。请使用现有骨架制作动作，或在 Blender 中继续编辑。导入静态 GLB 后可创建新骨架。</span></div>}
      {error && <p className="rig-error" role="alert">{error}</p>}
      {jobs.length > 0 && <div className="rig-history"><div className="rig-step"><Check size={13} /><strong>绑定记录</strong><button onClick={() => setAllJobs(v => !v)}>{allJobs ? '收起' : `${jobs.length} 条`}</button></div>{(allJobs ? jobs : jobs.slice(0, 3)).map(job => <article key={job.id}><strong>{job.state === 'done' ? '绑定完成 · 待视觉检查' : job.state === 'running' ? '正在绑定' : '需要修正'}</strong><small>{job.fileName} · {new Date(job.createdAt).toLocaleString('zh-CN')}</small><p>{job.message}</p>{job.report && <><p>{job.report.bones} 根骨骼 · {job.report.vertices.toLocaleString()} 顶点 · {job.report.unweighted} 个未绑定</p><details><summary>检查报告与限制</summary>{job.report.warnings.map((warning, i) => <p key={i}>{warning}</p>)}</details></>}<div className="rig-result-actions">{job.modelUrl && <button disabled={working || busy} onClick={() => load(job)}>导入并试动作<ArrowRight size={12} /></button>}{job.blendUrl && <a href={job.blendUrl} download>下载 .blend</a>}{job.modelUrl && <a href={job.modelUrl} download>下载 GLB</a>}{job.reportUrl && <a href={job.reportUrl} download>报告</a>}</div></article>)}</div>}
      <p className="rig-note rig-bottom-note">绑定任务在本机后台运行。结果保留原模型，点击“导入并试动作”才替换当前预览。</p>
    </div>
  </>;
}
