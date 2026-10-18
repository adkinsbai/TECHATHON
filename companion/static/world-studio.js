const $ = id => document.getElementById(id);
let selected = new URLSearchParams(location.search).get('scene'), job = null, config;
const remake=new Set();
const states = {planning:'规划中',planned:'规划完成',generating:'并行制作中',partial:'部分已完成',ready:'世界已就绪',failed:'需要检查'};
async function api(url, body) {
  const response = await fetch('/api/scene-studio' + url, body === undefined ? {} : {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  const data = await response.json(); if (!response.ok) throw new Error(data.detail || '请求失败'); return data;
}
function text(tag, value, className) {const el=document.createElement(tag);el.textContent=value;if(className)el.className=className;return el;}
function showError(e) {$('error').textContent=e.message;}
async function history() {
  const jobs=await api(''); $('history').replaceChildren();
  for (const j of jobs.slice(0,8)) {const button=text('button',(j.plan?.title || '正在整理故事')+' · '+j.ready_count+'/'+j.asset_count);button.onclick=()=>{selected=j.id;window.history.replaceState({},'',`?scene=${j.id}`);$('assets').replaceChildren();refresh();};$('history').append(button);}
}
function render(j) {
  job=j;$('state').textContent=states[j.state]||j.state;$('error').textContent=j.error||'';
  $('plan').disabled=j.state==='planning';$('recent').disabled=j.state==='planning';
  $('generate').disabled=!j.plan || j.running || j.ready_count===j.asset_count;
  $('generate').textContent=j.ready_count===j.asset_count&&j.asset_count?'所有资产已完成':j.state==='planned'?`并行制作 ${j.asset_count-j.ready_count} 类资产 →`:'继续未完成的资产 →';
  $('enter').hidden=!j.plan;$('enter').href=j.world_url;$('enter').textContent=j.ready_count===j.asset_count?'进入这个世界 ↗':`预览布局 · ${j.ready_count}/${j.asset_count} 就绪 ↗`;
  $('external').hidden=!j.plan;
  if(!j.plan)return;
  $('revision-controls').hidden=false;$('revise').disabled=j.running;
  $('scene-title').textContent=j.plan.title;$('summary').textContent=j.plan.summary;
  $('counts').replaceChildren();for(const [n,label] of [[j.asset_count,'类独立资产'],[j.plan.instances.length,'个场景实例'],[j.plan.relations.length,'组故事关系']]){const el=text('span',label);el.prepend(text('strong',n));$('counts').append(el);}
  $('schema').hidden=false;$('download').hidden=false;$('json').textContent=JSON.stringify(j.plan,null,2);
  const old=new Map([...$('assets').children].map(el=>[el.dataset.id,el]));
  for(const asset of j.plan.assets){
    const status=j.assets[asset.id];let card=old.get(asset.id);
    if(!card){card=text('div','','asset');card.dataset.id=asset.id;card.innerHTML='<div class="asset-image"></div><div class="asset-body"><h3></h3><small></small><p></p><progress max="4"></progress><div class="reference"></div></div>';$('assets').append(card);}
    old.delete(asset.id);card.querySelector('h3').textContent=asset.name;
    const n=j.plan.instances.filter(i=>i.asset_id===asset.id).length;
    card.querySelector('small').textContent=`${asset.kind==='animal'?'动物':asset.kind==='plant'?'植物':'建筑 / 道具'} / ${asset.height_m}m / 复用 ${n} 次${asset.inferred?' · 场景设计补充':''}`;
    card.querySelector('p').textContent=status.message+(status.rig?` · 动作：${status.rig.message||status.rig.state}`:'');card.querySelector('progress').value=({planned:0,image_running:1,model_submitting:2,model_running:2,downloading:3,ready:4})[status.state]||0;
    const area=card.querySelector('.asset-image');
    if(status.image_url && !area.querySelector('img')){const img=new Image();img.src=status.image_url;img.alt=asset.name+' · GPT 参考图';area.replaceChildren(img);}else if(!status.image_url)area.textContent=asset.id.toUpperCase();
    const reference=card.querySelector('.reference');
    if(status.has_reference)reference.textContent='已添加参考图 · GPT 将统一风格';
    else if(status.state==='planned'&&!j.running&&!reference.children.length){const input=document.createElement('input');input.type='file';input.accept='image/png,image/jpeg,image/webp';input.title='可选：添加这个资产的参考图';input.onchange=async()=>{if(!input.files[0])return;const form=new FormData();form.append('file',input.files[0]);const r=await fetch(`/api/scene-studio/${j.id}/assets/${asset.id}/reference`,{method:'POST',body:form});if(!r.ok)showError(new Error((await r.json()).detail));refresh();};reference.append(input);}
    else if(status.state!=='planned')reference.replaceChildren();
    let redo=card.querySelector('.remake');
    if(!redo){redo=text('label',' 重新制作这个资产','remake');const check=document.createElement('input');check.type='checkbox';Object.assign(check.style,{width:'auto',margin:'10px 4px 0 0'});check.onchange=()=>check.checked?remake.add(asset.id):remake.delete(asset.id);redo.prepend(check);card.querySelector('.asset-body').append(redo);}
    redo.querySelector('input').disabled=j.running;
  }
  for(const el of old.values())el.remove();
  $('relations-section').hidden=!j.plan.relations.length;$('relations').replaceChildren(...j.plan.relations.map(r=>text('div',r.description,'relation')));
}
async function refresh(){try{if(selected)render(await api('/'+selected));}catch(e){showError(e);}}
async function plan(recent=false){$('error').textContent='';$('plan').disabled=true;$('recent').disabled=true;try{const j=await api('/plan',{conversation:$('conversation').value.split('\n').map(x=>x.trim()).filter(Boolean),use_recent_chat:recent});selected=j.id;$('assets').replaceChildren();render(j);window.history.replaceState({},'',`?scene=${j.id}`);await history();}catch(e){showError(e);$('plan').disabled=false;$('recent').disabled=false;}}
$('plan').onclick=()=>plan();$('recent').onclick=()=>plan(true);
$('generate').onclick=async()=>{try{await api('/'+selected+'/generate',{provider:$('provider').value});await refresh();}catch(e){showError(e);}};
$('revise').onclick=async()=>{const changes=$('changes').value.trim();if(!changes)return;try{await api('/'+selected+'/revise',{changes,regenerate_asset_ids:[...remake]});remake.clear();$('assets').replaceChildren();await refresh();}catch(e){showError(e);}};
$('external').onclick=async()=>{try{const response=await fetch('/api/open-world',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({scene_id:selected})});const data=await response.json();if(!response.ok)throw new Error(data.detail);$('external').textContent='已打开，请切换浏览器窗口';}catch(e){showError(e);}};
$('download').onclick=()=>{const a=document.createElement('a');const url=URL.createObjectURL(new Blob([JSON.stringify(job.plan,null,2)],{type:'application/json'}));a.href=url;a.download='scene-blueprint.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);};
config=await api('/config');$('conversation').value=config.demo_conversation.join('\n');$('demo').onclick=()=>{$('conversation').value=config.demo_conversation.join('\n');};
$('config').textContent=`规划：${config.planner_model} · 生图：${config.image_model}。同时生图 ${config.concurrency.images} 个，建模 ${config.concurrency.models} 个。`;
for(const provider of ['rodin','tripo'])$('provider').querySelector(`[value=${provider}]`).disabled=!config[provider+'_configured'];$('provider').querySelector('[value=auto]').disabled=!(config.rodin_configured&&config.tripo_configured);
await history();await refresh();setInterval(refresh,2500);
