// 形象：肥嘟嘟的小猫。情绪驱动眼睛/眉毛/嘴巴/腮红/耳朵/特效；眼睛跟着鼠标转；可以摸摸它。
const Avatar = (() => {
  const $ = (id) => document.getElementById(id);
  const svg = $("avatar"), eyesEl = $("eyes"), browsEl = $("brows"), mouthEl = $("mouth");
  const blushL = $("blushL"), blushR = $("blushR"), fx = $("fx"), wrap = $("avatarWrap");
  const EY = 120; // 眼睛中心高度

  const hi = (x, y, r1 = 6.5, r2 = 2.6) =>
    `<circle class="eye-hi" cx="${x + 5}" cy="${y - 7}" r="${r1}"/><circle class="eye-hi" cx="${x - 6}" cy="${y + 8}" r="${r2}"/>`;
  const EYE = {
    open: (x) => `<g class="pupil"><ellipse class="eye" cx="${x}" cy="${EY}" rx="16" ry="19"/>${hi(x, EY)}</g>`,
    wide: (x) => `<g class="pupil"><ellipse class="eye" cx="${x}" cy="${EY - 1}" rx="18" ry="21.5"/>${hi(x, EY - 1, 7.5, 3)}
      <path class="eye-hi sparkle" d="M${x + 9} ${EY + 6} l1.5 3.5 3.5 1.5 -3.5 1.5 -1.5 3.5 -1.5 -3.5 -3.5 -1.5 3.5 -1.5z"/></g>`,
    teary: (x) => `<g class="pupil"><ellipse class="eye" cx="${x}" cy="${EY + 1}" rx="16" ry="18"/>${hi(x, EY + 1, 6, 3)}
      <path class="tear-line" d="M${x - 12} ${EY + 13} Q${x} ${EY + 19} ${x + 12} ${EY + 13}"/></g>`,
    happy: (x) => `<path class="eye-line" d="M${x - 14} ${EY + 5} Q${x} ${EY - 13} ${x + 14} ${EY + 5}"/>`,
    closed: (x) => `<path class="eye-line" d="M${x - 14} ${EY - 2} Q${x} ${EY + 10} ${x + 14} ${EY - 2}"/>`,
    flat: (x) => `<path class="eye-line" d="M${x - 13} ${EY + 2} L${x + 13} ${EY}"/>`,
    heart: (x) => `<path class="eye-heart" d="M${x} ${EY + 13} C${x - 22} ${EY - 2} ${x - 12} ${EY - 20} ${x} ${EY - 8} C${x + 12} ${EY - 20} ${x + 22} ${EY - 2} ${x} ${EY + 13}Z"/>
      <circle class="eye-hi" cx="${x - 7}" cy="${EY - 6}" r="3"/>`,
    wink: (x) => `<path class="eye-line" d="M${x - 14} ${EY + 2} Q${x} ${EY - 8} ${x + 14} ${EY + 2}"/>`,
  };
  const MOUTH = {
    cat: "M108 146 Q114 153 120 146 Q126 153 132 146",
    smile: "M110 147 Q120 156 130 147",
    grin: "M108 146 Q120 166 132 146 Q120 150 108 146Z",
    small: "M115 149 Q120 152 125 149",
    o: "M115 151 Q120 143 125 151 Q120 159 115 151Z",
    flat: "M112 150 L128 150",
    frown: "M110 155 Q120 146 130 155",
    wavy: "M106 152 Q111 147 116 152 Q121 157 126 152 Q131 147 134 152",
    talk: "M110 146 Q120 162 130 146 Q120 150 110 146Z",
  };
  const FILLED = ["grin", "o", "talk"];
  const BROWS = {
    sad: '<path class="brow" d="M74 98 L98 91"/><path class="brow" d="M142 91 L166 98"/>',
    up: '<path class="brow" d="M74 93 Q86 84 99 91"/><path class="brow" d="M141 91 Q154 84 166 93"/>',
    angry: '<path class="brow" d="M74 90 L99 98"/><path class="brow" d="M141 98 L166 90"/>',
  };
  const FACES = {
    happy:     { eyes: ["happy", "happy"], mouth: "grin", blush: .6, motion: "bounce", fx: ["♥", "✦", "♥"] },
    calm:      { eyes: ["open", "open"], mouth: "cat", blush: .35 },
    shy:       { eyes: ["closed", "closed"], mouth: "small", blush: 1, ears: "down", fx: ["♡"] },
    sad:       { eyes: ["teary", "teary"], mouth: "frown", blush: .2, brows: "sad", motion: "droop", ears: "down", fx: ["tear"] },
    worried:   { eyes: ["open", "open"], mouth: "wavy", blush: .25, brows: "sad", ears: "down", fx: ["💧"] },
    surprised: { eyes: ["wide", "wide"], mouth: "o", blush: .3, brows: "up", motion: "bounce", ears: "up", fx: ["!"] },
    playful:   { eyes: ["wink", "open"], mouth: "cat", blush: .5, motion: "tilt", fx: ["♪", "♫"] },
    sleepy:    { eyes: ["closed", "closed"], mouth: "small", blush: .3, motion: "sway", ears: "down", fx: ["z", "Z", "z"] },
    missing:   { eyes: ["wide", "wide"], mouth: "small", blush: .7, brows: "sad", fx: ["♡", "♡"] },
    angry:     { eyes: ["flat", "flat"], mouth: "frown", blush: .6, brows: "angry", ears: "back", fx: ["💢"] },
  };
  const LABEL = { happy: "开心", calm: "平静", shy: "害羞", sad: "难过", worried: "担心", surprised: "惊讶",
                  playful: "调皮", sleepy: "困困的", missing: "想你", angry: "有点生气" };

  let current = "calm", currentIntensity = .5, baseMouth = "cat", talkTimer = null;

  function setEmotion(emotion = "calm", intensity = .5) {
    current = FACES[emotion] ? emotion : "calm";
    currentIntensity = intensity;
    const f = FACES[current];
    let eyes = f.eyes;
    if (current === "happy" && intensity >= .8) eyes = ["heart", "heart"];
    eyesEl.innerHTML = EYE[eyes[0]](88) + EYE[eyes[1]](152);
    browsEl.innerHTML = f.brows ? BROWS[f.brows] : "";
    baseMouth = f.mouth;
    if (!talkTimer) setMouth(baseMouth);
    const b = Math.min(1, f.blush * (0.7 + intensity * 0.6));
    blushL.style.opacity = blushR.style.opacity = b;
    svg.querySelector(".blush-line").style.opacity = b > .7 ? 1 : 0;
    svg.dataset.ears = f.ears || "";
    wrap.classList.remove("bounce", "droop", "tilt", "sway");
    void wrap.offsetWidth;
    if (f.motion) wrap.classList.add(f.motion);
    if (f.fx && intensity > .35) burst(f.fx);
  }

  function setMouth(name) {
    mouthEl.setAttribute("d", MOUTH[name]);
    mouthEl.classList.toggle("filled", FILLED.includes(name));
  }

  function burst(symbols) {
    symbols.forEach((s, i) => {
      const el = document.createElement("span");
      if (s === "tear") {
        el.className = "tear";
        el.style.left = "33%";
        el.style.top = "52%";
      } else {
        el.textContent = s;
        el.style.left = `${18 + Math.random() * 64}%`;
        el.style.top = `${6 + Math.random() * 22}%`;
      }
      el.style.animationDelay = `${i * .35}s`;
      fx.appendChild(el);
      setTimeout(() => el.remove(), 3200 + i * 350);
    });
  }

  function speaking(on) {
    clearInterval(talkTimer);
    talkTimer = null;
    if (on) {
      let open = false;
      talkTimer = setInterval(() => {
        open = !open || Math.random() < .3;
        setMouth(open ? "talk" : baseMouth);
      }, 140 + Math.random() * 60);
    } else {
      setMouth(baseMouth);
    }
  }

  function thinking(on) {
    $("thinking").classList.toggle("on", on);
    wrap.classList.toggle("pondering", on);
  }

  function activity(text) {
    const el = $("activity");
    el.hidden = !text;
    el.textContent = text || "";
  }

  // 眨眼（睁眼类表情才眨）
  (function blinkLoop() {
    setTimeout(() => {
      if (eyesEl.querySelector(".pupil")) {
        eyesEl.classList.add("blink");
        setTimeout(() => eyesEl.classList.remove("blink"), 180);
      }
      blinkLoop();
    }, 2200 + Math.random() * 3800);
  })();

  // 耳朵偶尔抖一下
  (function earLoop() {
    setTimeout(() => {
      const ear = svg.querySelector(Math.random() < .5 ? ".ear.l" : ".ear.r");
      ear.classList.add("twitch");
      setTimeout(() => ear.classList.remove("twitch"), 400);
      earLoop();
    }, 4000 + Math.random() * 7000);
  })();

  // 眼睛跟着鼠标
  let look = { x: 0, y: 0 }, idleLook = 0;
  window.addEventListener("pointermove", (e) => {
    const r = svg.getBoundingClientRect();
    const cx = r.left + r.width / 2, cy = r.top + r.height * .5;
    const dx = e.clientX - cx, dy = e.clientY - cy, d = Math.hypot(dx, dy) || 1;
    const k = Math.min(1, d / 400);
    look = { x: (dx / d) * 4.5 * k, y: (dy / d) * 3.5 * k };
    idleLook = Date.now();
    applyLook();
  });
  function applyLook() {
    eyesEl.querySelectorAll(".pupil").forEach((p) => (p.style.transform = `translate(${look.x}px, ${look.y}px)`));
    svg.querySelector(".head-g").style.setProperty("--lx", `${look.x * .5}px`);
    svg.querySelector(".head-g").style.setProperty("--ly", `${look.y * .3}px`);
  }
  // 鼠标不动时，自己东张西望
  setInterval(() => {
    if (Date.now() - idleLook < 4000) return;
    look = Math.random() < .4 ? { x: 0, y: 0 } : { x: (Math.random() - .5) * 8, y: (Math.random() - .5) * 5 };
    applyLook();
  }, 2600);

  // 摸摸：在小猫身上来回移动（或手指滑动）
  let petDist = 0, lastPt = null, purring = false, petCount = 0;
  svg.addEventListener("pointermove", (e) => {
    if (lastPt) petDist += Math.hypot(e.clientX - lastPt.x, e.clientY - lastPt.y);
    lastPt = { x: e.clientX, y: e.clientY };
    if (petDist > 420 && !purring) purr();
  });
  svg.addEventListener("pointerleave", () => { lastPt = null; petDist = 0; });
  svg.addEventListener("click", () => {
    if (purring) return;
    const prev = current, pi = currentIntensity;
    setEmotion("surprised", .5);
    setTimeout(() => setEmotion(prev, pi * .5), 1200);
  });
  function purr() {
    purring = true;
    petCount++;
    const prev = current, pi = currentIntensity;
    setEmotion("happy", petCount % 3 === 0 ? .9 : .6);
    wrap.classList.add("purring");
    $("purr").hidden = false;
    window.dispatchEvent(new CustomEvent("avatar:pet", { detail: { count: petCount } }));
    setTimeout(() => {
      wrap.classList.remove("purring");
      $("purr").hidden = true;
      setEmotion(prev, pi * .5);
      purring = false;
      petDist = 0;
    }, 2600);
  }

  setEmotion("calm");
  return { setEmotion, speaking, thinking, activity, label: (e) => LABEL[e] || "平静", get current() { return current; } };
})();
