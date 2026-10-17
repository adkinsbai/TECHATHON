
// BEGIN XIAONUAN BODY VIEW
{
  const physicalTurns = new Map();
  let ownedAudio = false;
  window.addEventListener("body:status", ({ detail: d }) => {
    if (d.connected && !ownedAudio) stopSpeaking();
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
