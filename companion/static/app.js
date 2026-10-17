const $ = (id) => document.getElementById(id);
const store = {
  get(k, d) { try { const v = localStorage.getItem(k); return v === null ? d : JSON.parse(v); } catch { return d; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch {} },
};

let persona = null;
let busy = false;
let ttsMode = "glm";      // glm 不可用时切到 browser
let asrMode = "glm";
let currentAudio = null;

// ---------- 时间主题 ----------
function applyTimeTheme() {
  const h = new Date().getHours();
  const t = h >= 5 && h < 10 ? "morning" : h < 17 ? "day" : h < 19 ? "evening" : "night";
  document.documentElement.dataset.time = h < 5 ? "night" : t;
}
applyTimeTheme();
setInterval(applyTimeTheme, 10 * 60 * 1000);

// ---------- 小工具 ----------
function toast(text, ms = 2600) {
  const el = $("toast");
  el.textContent = text;
  el.hidden = false;
  clearTimeout(toast.t);
  toast.t = setTimeout(() => (el.hidden = true), ms);
}

async function api(path, opts = {}) {
  const res = await fetch(path, {
    headers: opts.body && !(opts.body instanceof FormData) ? { "Content-Type": "application/json" } : {},
    ...opts,
    body: opts.body && !(opts.body instanceof FormData) ? JSON.stringify(opts.body) : opts.body,
  });
  if (!res.ok) {
    let msg = res.statusText;
    try { msg = (await res.json()).detail || msg; } catch {}
    throw new Error(msg);
  }
  return res.status === 204 ? null : res.json();
}

const fmtTime = (ts) => new Date(ts * 1000).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });
const fmtDay = (ts) => {
  const d = new Date(ts * 1000), now = new Date();
  const diff = Math.floor((new Date(now.toDateString()) - new Date(d.toDateString())) / 864e5);
  return diff === 0 ? "今天" : diff === 1 ? "昨天" : d.toLocaleDateString("zh-CN", { month: "long", day: "numeric", weekday: "short" });
};
// 回复开头是情绪标签 [shy 0.7]，显示时去掉；标签没写完时先不显示
const LEAD = /^\s*[\[【]\s*([A-Za-z]+)[\s,，:：]*([\d.]+)?\s*[\]】]\s*/;
const visibleText = (raw) => {
  if (/^\s*[\[【][^\]】]*$/.test(raw)) return "";
  return raw.replace(LEAD, "").replace(/<state>[\s\S]*$/, "").replace(/<[a-z/]*$/i, "").trim();
};
const escapeHtml = (s) => s.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);

// ---------- 消息渲染 ----------
const box = $("messages");
let lastDay = null;

function scrollDown() { box.scrollTop = box.scrollHeight; }

function addDaySep(ts) {
  const day = fmtDay(ts);
  if (day === lastDay) return;
  lastDay = day;
  const el = document.createElement("div");
  el.className = "day-sep";
  el.textContent = day;
  box.appendChild(el);
}

function renderMessage(role, text, ts = Date.now() / 1000) {
  addDaySep(ts);
  const msg = document.createElement("div");
  msg.className = `msg ${role}`;
  const parts = role === "assistant" ? text.split(/\n+/).filter((s) => s.trim()) : [text];
  for (const p of parts) {
    const b = document.createElement("div");
    b.className = "bubble";
    b.textContent = p.trim();
    msg.appendChild(b);
  }
  const meta = document.createElement("div");
  meta.className = "meta";
  meta.textContent = fmtTime(ts);
  msg.appendChild(meta);
  box.appendChild(msg);
  scrollDown();
  return msg;
}

function renderError(text) {
  const msg = document.createElement("div");
  msg.className = "msg assistant error";
  msg.innerHTML = `<div class="bubble">${escapeHtml(text)}</div>`;
  box.appendChild(msg);
  scrollDown();
}

// ---------- 状态面板 ----------
async function refreshStatus() {
  const s = await api("/api/status");
  $("name").textContent = $("headName").textContent = s.persona.name;
  document.title = s.persona.name;
  $("moodText").textContent = `此刻 · ${Avatar.label(s.mood.emotion)}`;
  $("bondNum").textContent = Math.round(s.closeness);
  $("bondFill").style.width = `${s.closeness}%`;
  $("daysText").textContent = s.days ? `认识第 ${s.days} 天` : "今天刚认识";
  Avatar.activity(s.activity);
  return s;
}

function setBond(c) {
  $("bondNum").textContent = Math.round(c);
  $("bondFill").style.width = `${c}%`;
}

// 摸摸 TA
window.addEventListener("avatar:pet", async () => {
  lastInteraction = Date.now();
  try { setBond((await api("/api/pet", { method: "POST" })).closeness); } catch {}
});

// 开着窗口但很久没说话时，TA 会轻轻开口（服务器保证每段沉默最多一次）
let lastInteraction = Date.now();
["keydown", "pointerdown"].forEach((ev) => window.addEventListener(ev, () => (lastInteraction = Date.now())));
setInterval(() => {
  if (busy || document.visibilityState !== "visible") return;
  if (Date.now() - lastInteraction < 10 * 60 * 1000) return;
  lastInteraction = Date.now();
  if (!window.BodyClient?.busy) streamReply("/api/nudge");
}, 60 * 1000);
// 隔一会儿刷新一下 TA 在做什么
setInterval(() => { if (!busy) refreshStatus().catch(() => {}); }, 5 * 60 * 1000);

function setStatus(text) { $("status").textContent = text; }

// ---------- 对话（流式） ----------
async function streamReply(url, body) {
  busy = true;
  $("sendBtn").disabled = true;
  Avatar.thinking(true);
  setStatus("正在输入…");
  let msg = null, bubble = null, raw = "", result = null, earlyEmotion = false;
  try {
    const res = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: body ? JSON.stringify(body) : null });
    if (res.status === 204) return null;
    if (!res.ok) throw new Error((await res.text()) || res.statusText);
    const reader = res.body.getReader();
    const dec = new TextDecoder();
    let buf = "";
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      let i;
      while ((i = buf.indexOf("\n\n")) >= 0) {
        const chunk = buf.slice(0, i);
        buf = buf.slice(i + 2);
        const ev = /event: (.*)/.exec(chunk)?.[1];
        const data = JSON.parse(/data: (.*)/s.exec(chunk)?.[1] || "{}");
        if (ev === "delta") {
          raw += data.text;
          const lead = !earlyEmotion && LEAD.exec(raw);
          if (lead) { earlyEmotion = true; Avatar.setEmotion(lead[1].toLowerCase(), parseFloat(lead[2] || ".5")); }
          if (!visibleText(raw)) continue;
          if (!msg) {
            Avatar.thinking(false);
            addDaySep(Date.now() / 1000);
            msg = document.createElement("div");
            msg.className = "msg assistant";
            bubble = document.createElement("div");
            bubble.className = "bubble cursor";
            msg.appendChild(bubble);
            box.appendChild(msg);
          }
          bubble.textContent = visibleText(raw);
          scrollDown();
        } else if (ev === "done") {
          result = data;
        } else if (ev === "error") {
          throw new Error(data.message);
        }
      }
    }
    if (msg) msg.remove();
    if (result) {
      renderMessage("assistant", result.text);
      if (Avatar.current !== result.emotion) Avatar.setEmotion(result.emotion, result.intensity);
      $("moodText").textContent = `此刻 · ${Avatar.label(result.emotion)}`;
      setBond(result.closeness);
      speak(result.text);
    }
    return result;
  } catch (e) {
    if (msg) msg.remove();
    renderError(`（${e.message}）`);
    Avatar.setEmotion("worried", .4);
  } finally {
    lastInteraction = Date.now();
    busy = false;
    $("sendBtn").disabled = false;
    Avatar.thinking(false);
    setStatus("在线");
  }
}

async function send(text, heard = null) {
  text = text.trim();
  if (!text || busy || window.BodyClient?.busy) return;
  stopSpeaking();
  Avatar.activity("");
  const msg = renderMessage("user", text);
  const bits = [heard?.emotion && heard.emotion !== "平静" ? `听起来${heard.emotion}` : "", heard?.event || ""].filter(Boolean);
  if (heard) {
    const tag = document.createElement("div");
    tag.className = "heard";
    tag.textContent = `🎙 语音${bits.length ? " · " + bits.join(" · ") : ""}`;
    msg.insertBefore(tag, msg.querySelector(".meta"));
  }
  await streamReply("/api/chat", { text, voice_emotion: heard?.emotion || "", voice_event: heard?.event || "" });
}

const input = $("input");
$("composer").addEventListener("submit", (e) => {
  e.preventDefault();
  const t = input.value;
  input.value = "";
  autosize();
  send(t);
});
input.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
    e.preventDefault();
    $("composer").requestSubmit();
  }
});
function autosize() {
  input.style.height = "auto";
  input.style.height = `${Math.min(input.scrollHeight + 3, 140)}px`;
  input.style.overflowY = input.scrollHeight > 140 ? "auto" : "hidden";
}
input.addEventListener("input", autosize);

// ---------- 朗读 ----------
let voiceOn = store.get("voiceOn", false);
function syncVoiceToggle() { $("voiceToggle").setAttribute("aria-pressed", String(voiceOn)); $("autoSpeak").checked = voiceOn; }
syncVoiceToggle();
$("voiceToggle").addEventListener("click", () => {
  voiceOn = !voiceOn;
  store.set("voiceOn", voiceOn);
  syncVoiceToggle();
  toast(voiceOn ? "会把回复读给你听" : "朗读已关闭");
  if (!voiceOn) stopSpeaking();
});

const cleanForSpeech = (t) => t.replace(/[（(][^）)]*[）)]/g, "").replace(/[\p{Extended_Pictographic}]/gu, "").replace(/[~～]+/g, "，").trim();

let bodySpeechGeneration = 0, bodySpeechForced = false;
function stopSpeaking() {
  bodySpeechGeneration += 1;
  bodySpeechForced = false;
  if (currentAudio) { currentAudio.pause(); currentAudio = null; }
  if (window.speechSynthesis) speechSynthesis.cancel();
  Avatar.speaking(false);
}

async function speak(text, force = false) {
  if (window.BodyClient?.routesAudio && !force) return;
  if (!voiceOn && !force) return;
  text = cleanForSpeech(text);
  if (!text) return;
  stopSpeaking();
  const speechGeneration = bodySpeechGeneration;
  bodySpeechForced = force;
  const speechCancelled = () => speechGeneration !== bodySpeechGeneration || (window.BodyClient?.routesAudio && !force);
  if (ttsMode === "glm" && persona?.voice !== "browser") {
    try {
      const res = await fetch("/api/tts", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text }) });
      if (speechCancelled()) return;
      if (!res.ok) throw new Error((await res.json()).detail);
      const blob = await res.blob();
      if (speechCancelled()) return;
      const url = URL.createObjectURL(blob);
      const audio = new Audio(url);
      currentAudio = audio;
      audio.onplay = () => { if (speechCancelled()) { audio.pause(); return; } Avatar.speaking(true); };
      audio.onended = audio.onpause = () => { Avatar.speaking(false); URL.revokeObjectURL(url); };
      await audio.play();
      return;
    } catch (e) {
      if (speechCancelled()) return;
      console.warn("GLM TTS 不可用，改用浏览器语音：", e.message);
      ttsMode = "browser";
      $("voiceStatus").textContent = `GLM 语音合成不可用（${e.message.slice(0, 80)}），正在使用浏览器自带的声音。`;
    }
  }
  if (speechCancelled() || !window.speechSynthesis) return;
  const u = new SpeechSynthesisUtterance(text);
  u.lang = "zh-CN";
  const zh = speechSynthesis.getVoices().filter((v) => v.lang.startsWith("zh"));
  u.voice = zh.find((v) => /Xiaoxiao|Xiaoyi|女|Female|Tingting/i.test(v.name)) || zh[0] || null;
  u.pitch = 1.15;
  u.rate = 1.02;
  u.onstart = () => Avatar.speaking(true);
  u.onend = u.onerror = () => Avatar.speaking(false);
  speechSynthesis.speak(u);
}

// ---------- 语音输入 ----------
const Recorder = (() => {
  let ctx, stream, node, source, chunks = [], rate = 48000;
  async function start() {
    stream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true } });
    ctx = new AudioContext();
    rate = ctx.sampleRate;
    source = ctx.createMediaStreamSource(stream);
    node = ctx.createScriptProcessor(4096, 1, 1);
    chunks = [];
    node.onaudioprocess = (e) => chunks.push(new Float32Array(e.inputBuffer.getChannelData(0)));
    source.connect(node);
    node.connect(ctx.destination);
  }
  function stop() {
    node.disconnect(); source.disconnect();
    stream.getTracks().forEach((t) => t.stop());
    ctx.close();
    return toWav(chunks, rate, 16000);
  }
  function toWav(parts, from, to) {
    const len = parts.reduce((n, p) => n + p.length, 0);
    const all = new Float32Array(len);
    let o = 0;
    for (const p of parts) { all.set(p, o); o += p.length; }
    const ratio = from / to, outLen = Math.floor(len / ratio);
    const pcm = new Int16Array(outLen);
    for (let i = 0; i < outLen; i++) {
      const s = Math.max(-1, Math.min(1, all[Math.floor(i * ratio)]));
      pcm[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
    }
    const buf = new ArrayBuffer(44 + pcm.length * 2), v = new DataView(buf);
    const w = (off, str) => [...str].forEach((c, i) => v.setUint8(off + i, c.charCodeAt(0)));
    w(0, "RIFF"); v.setUint32(4, 36 + pcm.length * 2, true); w(8, "WAVE"); w(12, "fmt ");
    v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, 1, true);
    v.setUint32(24, to, true); v.setUint32(28, to * 2, true); v.setUint16(32, 2, true); v.setUint16(34, 16, true);
    w(36, "data"); v.setUint32(40, pcm.length * 2, true);
    new Int16Array(buf, 44).set(pcm);
    return { blob: new Blob([buf], { type: "audio/wav" }), seconds: outLen / to };
  }
  return { start, stop };
})();

let recording = false, browserRec = null;
const SR = window.SpeechRecognition || window.webkitSpeechRecognition;

$("micBtn").addEventListener("click", async () => {
  if (busy) return;
  const mic = $("micBtn");
  if (asrMode === "browser") return browserListen();
  if (!recording) {
    try {
      stopSpeaking();
      await Recorder.start();
      recording = true;
      mic.classList.add("recording");
      setStatus("在听你说…");
      Avatar.setEmotion("calm");
    } catch (e) {
      toast("没能打开麦克风：" + e.message);
    }
    return;
  }
  recording = false;
  mic.classList.remove("recording");
  const { blob, seconds } = Recorder.stop();
  if (seconds < 0.5) { setStatus("在线"); return toast("说得太短啦"); }
  setStatus("在辨认你说的话…");
  try {
    const fd = new FormData();
    fd.append("file", blob, "speech.wav");
    const heard = await api("/api/asr", { method: "POST", body: fd });
    setStatus("在线");
    if (heard.text) send(heard.text, heard); else toast("没听清，再说一次好吗？");
  } catch (e) {
    setStatus("在线");
    if (SR) {
      asrMode = "browser";
      toast("GLM 语音识别不可用，已改用浏览器识别，请再按一次麦克风说话", 4000);
    } else {
      toast("语音识别不可用：" + e.message, 4000);
    }
  }
});

function browserListen() {
  if (browserRec) { browserRec.stop(); return; }
  browserRec = new SR();
  browserRec.lang = "zh-CN";
  browserRec.interimResults = true;
  let finalText = "";
  browserRec.onstart = () => { $("micBtn").classList.add("recording"); setStatus("在听你说…"); stopSpeaking(); };
  browserRec.onresult = (e) => {
    finalText = [...e.results].map((r) => r[0].transcript).join("");
    input.value = finalText;
    autosize();
  };
  browserRec.onerror = (e) => toast("识别出错：" + e.error);
  browserRec.onend = () => {
    $("micBtn").classList.remove("recording");
    setStatus("在线");
    browserRec = null;
    if (finalText.trim()) { input.value = ""; autosize(); send(finalText); }
  };
  browserRec.start();
}

// ---------- 设定抽屉 ----------
const drawer = $("drawer"), mask = $("drawerMask");
function openDrawer(tab = "persona") {
  drawer.hidden = mask.hidden = false;
  switchTab(tab);
}
function closeDrawer() { drawer.hidden = mask.hidden = true; }
$("openSettings").addEventListener("click", () => openDrawer());
$("closeSettings").addEventListener("click", closeDrawer);
mask.addEventListener("click", closeDrawer);
document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !drawer.hidden) closeDrawer(); });

function switchTab(name) {
  document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t.dataset.tab === name));
  document.querySelectorAll(".panel").forEach((p) => p.classList.toggle("active", p.dataset.panel === name));
  if (name === "persona") fillPersona();
  if (name === "memory") loadMemories();
  if (name === "diary") loadDiary();
  if (name === "dreams") loadDreams();
  if (name === "voice") loadVoices();
  if (name === "import") { $("imp_user").value ||= persona?.user_name !== "你" ? persona?.user_name || "" : ""; }
}
document.querySelectorAll(".tab").forEach((t) => t.addEventListener("click", () => switchTab(t.dataset.tab)));

const PFIELDS = ["name", "user_name", "identity", "personality", "speaking_style", "relationship", "background"];
async function fillPersona() {
  persona = await api("/api/persona");
  PFIELDS.forEach((f) => ($(`p_${f}`).value = persona[f] || ""));
  $("p_catchphrases").value = (persona.catchphrases || []).join("，");
  const n = (persona.examples || []).length;
  $("exampleCount").textContent = n ? `已从聊天记录学习了 ${n} 段对话示例，用来模仿说话语气。` : "";
  $("clearExamples").hidden = !n;
}
$("savePersona").addEventListener("click", async () => {
  const p = {};
  PFIELDS.forEach((f) => (p[f] = $(`p_${f}`).value.trim()));
  p.catchphrases = $("p_catchphrases").value.split(/[,，、]/).map((s) => s.trim()).filter(Boolean);
  persona = await api("/api/persona", { method: "PUT", body: p });
  await refreshStatus();
  toast("设定已保存，TA 会按新的样子和你说话");
});
$("clearExamples").addEventListener("click", async () => {
  persona = await api("/api/persona", { method: "PUT", body: { examples: [] } });
  fillPersona();
});

// 记忆
async function loadMemories() {
  const { memories, episodes } = await api("/api/memories");
  $("memCount").textContent = memories.length ? `（${memories.length}）` : "";
  const ml = $("memList");
  ml.innerHTML = memories.length ? "" : '<li class="empty">还没有记住什么，多聊聊吧</li>';
  for (const m of memories) {
    const li = document.createElement("li");
    li.innerHTML = `<span class="stars">${"★".repeat(Math.max(1, Math.min(5, m.importance)))}</span>
      <span class="txt" contenteditable="true" spellcheck="false">${escapeHtml(m.content)}</span>
      <button title="忘掉这条">×</button>`;
    const txt = li.querySelector(".txt");
    txt.addEventListener("blur", async () => {
      const v = txt.textContent.trim();
      if (v && v !== m.content) { await api(`/api/memories/${m.id}`, { method: "PUT", body: { content: v, importance: m.importance } }); m.content = v; toast("已修改"); }
    });
    txt.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); txt.blur(); } });
    li.querySelector("button").addEventListener("click", async () => { await api(`/api/memories/${m.id}`, { method: "DELETE" }); loadMemories(); });
    ml.appendChild(li);
  }
  const el = $("epList");
  el.innerHTML = episodes.length ? "" : '<li class="empty">还没有回忆片段</li>';
  for (const e of episodes) {
    const li = document.createElement("li");
    li.innerHTML = `<span class="txt"><small>${new Date(e.end_ts * 1000).toLocaleString("zh-CN", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" })}</small>${escapeHtml(e.summary)}</span><button title="删除">×</button>`;
    li.querySelector("button").addEventListener("click", async () => { await api(`/api/episodes/${e.id}`, { method: "DELETE" }); loadMemories(); });
    el.appendChild(li);
  }
}
$("addMem").addEventListener("click", async () => {
  const v = $("newMem").value.trim();
  if (!v) return;
  await api("/api/memories", { method: "POST", body: { content: v, importance: 4 } });
  $("newMem").value = "";
  loadMemories();
  toast("记住啦");
});
$("newMem").addEventListener("keydown", (e) => { if (e.key === "Enter") $("addMem").click(); });
$("consolidate").addEventListener("click", async (e) => {
  e.target.disabled = true;
  e.target.textContent = "整理中…";
  try { await api("/api/memories/consolidate", { method: "POST" }); await loadMemories(); toast("整理好了"); }
  finally { e.target.disabled = false; e.target.textContent = "现在整理一次记忆"; }
});
$("clearChat").addEventListener("click", async () => {
  if (!confirm("清空聊天记录？TA 会先把重要的事情存进记忆，记忆不会丢。")) return;
  await api("/api/history", { method: "DELETE" });
  box.innerHTML = "";
  lastDay = null;
  toast("聊天记录已清空");
});

// 日记
async function loadDiary() {
  const list = await api("/api/diary");
  const el = $("diaryList");
  el.innerHTML = list.length ? "" : '<li class="empty">还没有日记。你离开一会儿，TA 就会开始写啦。</li>';
  for (const d of list) {
    const li = document.createElement("li");
    li.innerHTML = `<div class="diary-meta">${new Date(d.ts * 1000).toLocaleString("zh-CN", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" })}
      ${d.activity ? `· ${escapeHtml(d.activity)}` : ""}</div><div>${escapeHtml(d.content)}</div>`;
    el.appendChild(li);
  }
}
$("diaryNow").addEventListener("click", async (e) => {
  e.target.disabled = true;
  e.target.textContent = "TA 正在写…";
  try { await api("/api/diary/now", { method: "POST" }); await loadDiary(); refreshStatus(); }
  catch (err) { toast("没写成：" + err.message); }
  finally { e.target.disabled = false; e.target.textContent = "让 TA 现在写一篇"; }
});

// 梦与世界
const fmtDate = (ts) => new Date(ts * 1000).toLocaleString("zh-CN", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" });
async function loadDreams() {
  const [dreams, worlds] = await Promise.all([api("/api/dreams"), api("/api/worlds")]);
  const dl = $("dreamList");
  dl.innerHTML = dreams.length ? "" : '<li class="empty">还没有记下梦。下次做了梦，讲给 TA 听吧。</li>';
  for (const d of dreams) {
    const li = document.createElement("li");
    const tags = [...(d.imagery || []), ...(d.feelings || [])].map((t) => `#${escapeHtml(t)}`).join(" ");
    li.innerHTML = `<div class="diary-meta">${fmtDate(d.ts)} · ${escapeHtml(d.title || "一个梦")}${d.world_id ? " · 已编进世界" : ""}
      <button class="mini-del" title="删除">×</button></div><div>${escapeHtml(d.content)}</div>${tags ? `<small>${tags}</small>` : ""}`;
    li.querySelector(".mini-del").addEventListener("click", async () => { await api(`/api/dreams/${d.id}`, { method: "DELETE" }); loadDreams(); });
    dl.appendChild(li);
  }
  const wl = $("worldList");
  wl.innerHTML = worlds.length ? "" : '<li class="empty">还没有编织过世界。</li>';
  for (const w of [...worlds].reverse()) {
    const li = document.createElement("li");
    li.innerHTML = `<div class="diary-meta">${fmtDate(w.created)}${w.completed ? " · ✓ 一起冒险过" : " · 还没进去过"}</div>
      <div><b>${escapeHtml(w.title)}</b>：${escapeHtml(w.recipe.intro || "")}</div>
      <small>灵感：${escapeHtml(w.inspiration || "你们的生活")}</small>
      <div class="row-btns" style="margin-top:6px"><a class="btn primary" href="/world?chapter=w${w.id}" target="_blank">进入这个世界</a></div>`;
    wl.appendChild(li);
  }
}
$("addDream").addEventListener("click", async () => {
  const content = $("dreamText").value.trim();
  if (!content) return;
  await api("/api/dreams", { method: "POST", body: { content } });
  $("dreamText").value = "";
  toast("记下来了，TA 会好好收藏这个梦");
  loadDreams();
});
$("weaveBtn").addEventListener("click", async (e) => {
  e.target.disabled = true;
  e.target.textContent = "TA 正在把你的生活和梦编成一个世界…（约半分钟）";
  try {
    const { recipe } = await api("/api/worlds/weave", { method: "POST" });
    toast(`新世界「${recipe.title}」编好啦！`, 4000);
    loadDreams();
  } catch (err) {
    toast("没编成：" + err.message, 4000);
  } finally {
    e.target.disabled = false;
    e.target.textContent = "✦ 现在编织一个新世界";
  }
});

// 导入聊天记录
$("imp_file").addEventListener("change", async (e) => {
  const f = e.target.files[0];
  if (!f) return;
  $("imp_text").value = await f.text();
  toast(`已读取 ${f.name}，共 ${$("imp_text").value.length} 字`);
});
let importData = null;
$("analyze").addEventListener("click", async (e) => {
  const text = $("imp_text").value, who = $("imp_who").value.trim(), user = $("imp_user").value.trim();
  if (!who || !user) return toast("请先填写两个人在记录里的名字");
  if (text.trim().length < 50) return toast("聊天记录太短了");
  e.target.disabled = true;
  e.target.textContent = "正在认真读你们的聊天记录…（可能要一两分钟）";
  try {
    importData = await api("/api/persona/from_chat", { method: "POST", body: { text, who, user_name: user } });
    showImport(who);
  } catch (err) {
    toast("分析失败：" + err.message, 4000);
  } finally {
    e.target.disabled = false;
    e.target.textContent = "开始分析";
  }
});
function showImport(who) {
  const d = importData, el = $("impResult");
  const row = (k, v) => (v ? `<dt>${k}</dt><dd>${escapeHtml(Array.isArray(v) ? v.join("、") : v)}</dd>` : "");
  el.innerHTML = `<dl>
    ${row("身份", d.identity)}${row("性格", d.personality)}${row("说话方式", d.speaking_style)}
    ${row("口头禅", d.catchphrases)}${row("关系", d.relationship)}${row("背景", d.background)}
    ${row("对话示例", `${(d.examples || []).length} 段`)}${row("关于你的事", d.facts_about_user)}
    </dl>
    <label class="check"><input type="checkbox" id="impName" checked> 把名字也改成「${escapeHtml(who)}」</label>
    <label class="check"><input type="checkbox" id="impFacts" checked> 把“关于你的事”存进记忆</label>
    <div class="row-btns"><button class="btn primary" id="applyImport">应用到 TA 身上</button></div>`;
  el.hidden = false;
  $("applyImport").addEventListener("click", async () => {
    const p = { identity: d.identity, personality: d.personality, speaking_style: d.speaking_style,
                catchphrases: d.catchphrases || [], relationship: d.relationship, background: d.background,
                examples: d.examples || [], user_name: $("imp_user").value.trim() };
    if ($("impName").checked) p.name = who;
    Object.keys(p).forEach((k) => (p[k] === undefined || p[k] === "") && delete p[k]);
    persona = await api("/api/persona", { method: "PUT", body: p });
    if ($("impFacts").checked && d.facts_about_user?.length) {
      await api("/api/memories/bulk", { method: "POST", body: { facts: d.facts_about_user } });
    }
    await refreshStatus();
    toast("已应用，去和 TA 聊聊吧");
    switchTab("persona");
  });
}

// 声音
async function loadVoices() {
  persona = persona || (await api("/api/persona"));
  const { voices, local_tts, local_asr } = await api("/api/voices");
  const sel = $("voiceSelect");
  sel.innerHTML = Object.entries(voices).map(([k, v]) => `<option value="${k}">${v}</option>`).join("") +
    '<option value="browser">浏览器自带声音</option>';
  sel.value = voices[persona.voice] || persona.voice === "browser" ? persona.voice : Object.keys(voices)[0];
  $("voiceStatus").textContent = [
    local_tts ? "✓ 本地语音合成（Kokoro）已启用，离线可用" : "本地语音合成模型未找到",
    local_asr ? "✓ 本地语音识别（SenseVoice）已启用，还能听出你说话的情绪" : "本地语音识别模型未找到",
  ].join("\n");
  syncVoiceToggle();
}
$("saveVoice").addEventListener("click", async () => {
  persona = await api("/api/persona", { method: "PUT", body: { voice: $("voiceSelect").value } });
  voiceOn = $("autoSpeak").checked;
  store.set("voiceOn", voiceOn);
  syncVoiceToggle();
  ttsMode = "glm";
  toast("已保存");
});
$("testVoice").addEventListener("click", async () => {
  persona = await api("/api/persona", { method: "PUT", body: { voice: $("voiceSelect").value } });
  ttsMode = "glm";
  speak(`你好呀，我是${persona.name}，以后就用这个声音陪你说话啦。`, true);
});

// ---------- 启动 ----------
(async function boot() {
  try {
    persona = await api("/api/persona");
    const s = await refreshStatus();
    Avatar.setEmotion(s.mood.emotion, .3);
    const hist = await api("/api/history?limit=60");
    for (const m of hist) renderMessage(m.role, m.content, m.ts);
    await streamReply("/api/hello");
  } catch (e) {
    renderError(`（连不上后台服务：${e.message}）`);
  }
  input.focus();
})();
if (window.speechSynthesis) speechSynthesis.getVoices();

// BEGIN XIAONUAN BODY VIEW
{
  const physicalTurns = new Map();
  let ownedAudio = false;
  window.addEventListener("body:status", ({ detail: d }) => {
    if (d.connected !== ownedAudio && !bodySpeechForced) stopSpeaking();
    if (d.connected || ownedAudio) Avatar.speaking(d.connected && d.phase === "speaking");
    ownedAudio = d.connected;
  });
  window.addEventListener("body:turn_start", ({ detail: d }) => {
    physicalTurns.set(d.turn_id, { raw: "", node: null });
    Avatar.thinking(true); setStatus("实体小暖正在回应…");
  });
  window.addEventListener("body:user", ({ detail: d }) => renderMessage("user", d.text, d.ts));
  window.addEventListener("body:delta", ({ detail: d }) => {
    const turn = physicalTurns.get(d.turn_id); if (!turn) return;
    turn.raw += d.text;
    const lead = LEAD.exec(turn.raw); if (lead) Avatar.setEmotion(lead[1].toLowerCase(), Number(lead[2] || .5));
    const text = visibleText(turn.raw); if (!text) return;
    if (!turn.node) turn.node = renderMessage("assistant", text);
    else turn.node.querySelector(".bubble").textContent = text;
    scrollDown();
  });
  window.addEventListener("body:done", ({ detail: d }) => {
    const turn = physicalTurns.get(d.turn_id); if (turn?.node) turn.node.remove();
    renderMessage("assistant", d.text, d.ts); Avatar.thinking(false);
    Avatar.setEmotion(d.emotion || "calm", d.intensity || .5);
    $("moodText").textContent = `此刻 · ${Avatar.label(d.emotion)}`;
    if (Number.isFinite(d.closeness)) setBond(d.closeness);
  });
  window.addEventListener("body:error", ({ detail: d }) => renderError(d.message || "实体回应暂时中断"));
  window.addEventListener("body:turn_end", ({ detail: d }) => {
    physicalTurns.delete(d.turn_id); Avatar.thinking(false); setStatus("在线"); lastInteraction = Date.now();
  });
}
// END XIAONUAN BODY VIEW
