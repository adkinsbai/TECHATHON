// 开始页的“由对话生成的世界”：列出世界工作室生成的场景和仓库自带的示例，
// 每个世界展示它来自的那段对话，并给出进入入口。进入某个生成的世界时，只展示这个世界的对话。
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));

function bubbles(quotes, limit) {
  const shown = quotes.slice(0, limit);
  const more = quotes.length - shown.length;
  return shown.map((q) => `<p class="dw-bubble">${esc(q)}</p>`).join('')
    + (more > 0 ? `<p class="dw-more">还有 ${more} 句对话</p>` : '');
}

function card(job, {current}) {
  const quotes = Array.isArray(job.conversation) ? job.conversation : [];
  const ready = job.asset_count > 0 && job.ready_count === job.asset_count;
  const objects = job.plan?.instances?.length || 0;
  const tag = job.demo ? '<span class="dw-tag">示例</span>' : '<span class="dw-tag mine">我生成的</span>';
  const action = current ? ''
    : ready ? `<a class="btn small" href="${esc(job.world_url)}">进入这个世界 →</a>`
    : `<a class="btn small ghost" href="/world-studio?scene=${esc(job.id)}">生成中 ${job.ready_count}/${job.asset_count}</a>`;
  return `<article class="dw-item">
    <div class="dw-head"><b>${esc(job.plan?.title || '对话里的世界')}</b>${tag}</div>
    <div class="dw-chat" aria-label="生成这个世界的对话">${bubbles(quotes, current ? 8 : 3)}</div>
    <div class="dw-foot"><span>${job.asset_count} 类模型 · ${objects} 个物体</span>${action}</div>
  </article>`;
}

export async function renderDialogWorlds(box, scene) {
  if (!box) return;
  if (scene) {   // 正在一个生成的世界里：只展示它的来源对话
    box.querySelector('h2').textContent = '这个世界来自这段对话';
    box.querySelector('.dw-list').innerHTML = card(scene, {current: true});
    box.hidden = false;
    return;
  }
  let jobs = [];
  try { jobs = await fetch('/api/scene-studio').then((r) => (r.ok ? r.json() : [])); } catch {}
  jobs = jobs.filter((j) => j.plan && Array.isArray(j.conversation) && j.conversation.length);
  box.querySelector('.dw-list').innerHTML = jobs.length ? jobs.map((j) => card(j, {current: false})).join('')
    : '<p class="dw-empty">还没有由对话生成的世界。</p>';
  box.hidden = false;
}
