
// BEGIN XIAONUAN BODY VIEW
{
  const physicalTurns = new Map();
  let ownedAudio = false;
  window.addEventListener("body:status", ({ detail: d }) => {
    if (d.connected !== ownedAudio) stopWorldSpeaking();
    if (d.connected || ownedAudio) Cat.talking = d.connected && d.phase === "speaking";
    ownedAudio = d.connected;
  });
  window.addEventListener("body:turn_start", ({ detail: d }) => { physicalTurns.set(d.turn_id, ""); say("…", true); });
  window.addEventListener("body:user", ({ detail: d }) => logLine("user", d.text));
  window.addEventListener("body:delta", ({ detail: d }) => {
    if (!physicalTurns.has(d.turn_id)) return;
    const raw = physicalTurns.get(d.turn_id) + d.text; physicalTurns.set(d.turn_id, raw);
    const lead = LEAD.exec(raw); if (lead) Cat.setEmotion(lead[1].toLowerCase());
    if (visibleText(raw)) say(visibleText(raw), true);
  });
  window.addEventListener("body:done", ({ detail: d }) => {
    logLine("assistant", d.text); say(d.text); caption(d.text, Math.max(6000, d.text.length * 250));
    Cat.setEmotion(d.emotion || "calm");
  });
  window.addEventListener("body:error", ({ detail: d }) => say(d.message || "实体回应暂时中断"));
  window.addEventListener("body:turn_end", ({ detail: d }) => { physicalTurns.delete(d.turn_id); });
}
// END XIAONUAN BODY VIEW
