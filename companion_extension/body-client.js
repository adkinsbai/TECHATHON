/* Shared physical-body controls; the existing views own their character rendering. */
(() => {
  "use strict";
  const labels = { offline: "等待实体连接", idle: "可以摸摸，也可以说话", calibrating: "松开传感器，正在校准",
    listening: "正在听你说话", recording: "正在听你说话", thinking: "小暖正在想", speaking: "小暖正在说话", error: "连接需要检查" };
  let state = { connected: false, phase: "offline", settings: { volume: 10 } }, received = 0, streamOpen = false;
  let externalTurn = null;
  const panel = document.createElement("details");
  panel.className = "body-panel";
  panel.innerHTML = `<summary><span class="body-dot"></span><span>实体小暖</span><span class="body-pill">未连接</span><span class="body-chevron">⌄</span></summary>
    <div class="body-inner"><div class="body-phase" role="status" aria-live="polite">等待实体连接</div>
    <p class="body-guide">按住说话，松开后回答。轻轻短按一下，小暖也能感觉到。</p>
    <div class="body-pressure"><span>触碰</span><progress max="4095" value="0" aria-label="传感器按压力度"></progress><span class="body-pressure-text">等待数据</span></div>
    <label class="body-volume">扬声器音量 <output>10%</output><input aria-label="实体扬声器音量" type="range" min="0" max="100" step="1" value="10"></label>
    <div class="body-buttons"><button type="button" class="body-record" disabled>开始录音</button><button type="button" class="body-calibrate" disabled>松手校准</button></div>
    <p class="body-error" role="alert" hidden></p><p class="body-foot">实体与电脑连接到同一 Wi-Fi 后，就会出现在这里。</p></div>`;
  document.body.appendChild(panel);
  const find = (s) => panel.querySelector(s);
  const slider = find("input"), output = find("output"), error = find(".body-error");
  const emit = (name, data) => window.dispatchEvent(new CustomEvent(`body:${name}`, { detail: data }));
  const connected = () => !!(streamOpen && state.connected && Date.now() - received < 8000 &&
    (!Number.isFinite(state.last_seen) || Date.now() / 1000 - state.last_seen <= 8));
  window.BodyClient = { get routesAudio() { return connected(); },
    get busy() { return !!externalTurn || (connected() && ["recording", "listening", "thinking"].includes(state.phase)); },
    get state() { return { ...state, connected: connected() }; } };

  function showError(message = "") { error.textContent = message; error.hidden = !message; }
  function render() {
    const online = connected(), recording = ["listening", "recording"].includes(state.phase);
    panel.dataset.connected = String(online);
    find(".body-pill").textContent = online ? "已连接" : "未连接";
    find(".body-phase").textContent = online ? (labels[state.phase] || "实体已连接") : "等待实体连接";
    find(".body-record").disabled = !online || state.phase === "thinking";
    find(".body-record").textContent = recording ? "结束并发送" : "开始录音";
    find(".body-calibrate").disabled = !online || recording;
    const raw = Number.isFinite(state.raw) ? state.raw : null;
    find("progress").value = online && raw !== null ? Math.max(0, 4095 - raw) : 0;
    find(".body-pressure-text").textContent = online && raw !== null ? (state.pressed ? "按住中" : "已松开") : "等待数据";
    if (document.activeElement !== slider) slider.value = state.settings?.volume ?? 10;
    output.value = `${slider.value}%`;
    if (state.error) showError(state.error);
  }
  function acceptStatus(next) {
    state = { ...next, settings: next.settings || state.settings };
    received = Date.now();
    render(); emit("status", window.BodyClient.state);
  }
  async function request(path, method, body) {
    const res = await fetch(path, { method, headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body), signal: AbortSignal.timeout(5000) });
    if (!res.ok) { let message = "操作暂时没有完成"; try { message = (await res.json()).detail || message; } catch {}
      throw new Error(typeof message === "string" ? message : "请检查输入后再试"); }
    return res.json();
  }
  slider.addEventListener("input", () => { output.value = `${slider.value}%`; });
  slider.addEventListener("change", async () => {
    try { acceptStatus(await request("/api/body/settings", "PATCH", { volume: Number(slider.value) })); showError(); }
    catch (e) { showError(e.message); slider.value = state.settings?.volume ?? 10; output.value = `${slider.value}%`; }
  });
  async function command(name) { try { await request("/api/body/command", "POST", { command: name }); showError(); }
    catch (e) { showError(e.message); } }
  find(".body-record").addEventListener("click", () => command(["recording", "listening"].includes(state.phase) ? "record_stop" : "record_start"));
  find(".body-calibrate").addEventListener("click", () => command("calibrate"));
  // A focused slider or button must not also move the player in the 3D world.
  for (const name of ["keydown", "keyup", "pointerdown", "pointerup", "click"])
    panel.addEventListener(name, (e) => e.stopPropagation());

  const stream = new EventSource("/api/body/stream");
  stream.onopen = () => { streamOpen = true; render(); };
  stream.onerror = () => { streamOpen = false;
    if (externalTurn) emit("turn_end", { turn_id: externalTurn, source: "body" });
    externalTurn = null; render(); emit("status", window.BodyClient.state); };
  stream.addEventListener("hello", (e) => { try { acceptStatus(JSON.parse(e.data).status); } catch {} });
  stream.addEventListener("status", (e) => { try { acceptStatus(JSON.parse(e.data)); } catch {} });
  for (const name of ["turn_start", "user", "delta", "done", "error", "turn_end"]) {
    stream.addEventListener(name, (e) => {
      try { const data = JSON.parse(e.data);
        if (data.source !== "body") return;
        if (name === "turn_start") externalTurn = data.turn_id;
        if (name === "turn_end" && externalTurn === data.turn_id) externalTurn = null;
        emit(name, data);
      } catch {}
    });
  }
  let wasConnected = false;
  setInterval(() => { render(); const current = connected();
    if (current !== wasConnected) { wasConnected = current; emit("status", window.BodyClient.state); }
  }, 1000);
  render();
})();
