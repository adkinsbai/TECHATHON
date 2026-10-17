// 聊天页左侧的 3D 伙伴：用角色模型代替原来画的小猫。
// 原来的 SVG 形象还在（透明），继续负责摸摸、点击、情绪状态和爱心特效；这里每帧读取它的情绪和动作类名，让模型做整身动作。
import * as THREE from "three";
import { loadCharacter } from "/static/character.js?v=2";

const wrap = document.getElementById("avatarWrap");
const svg = document.getElementById("avatar");

async function main() {
  let model;
  try {
    model = await loadCharacter(1.9);
  } catch (e) {
    console.warn("角色模型加载失败，继续用原来的形象", e);
    return;
  }

  const canvas = document.createElement("canvas");
  canvas.className = "avatar3d";
  wrap.insertBefore(canvas, svg);
  svg.classList.add("hit-area"); // 只保留交互，不显示

  const renderer = new THREE.WebGLRenderer({ canvas, alpha: true, antialias: true });
  renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(30, 1, 0.1, 50);
  camera.position.set(0, 1.15, 5.2);
  camera.lookAt(0, 0.92, 0);

  scene.add(new THREE.HemisphereLight(0xfff4e6, 0xf2c4b4, 1.6));
  const key = new THREE.DirectionalLight(0xffe7c8, 1.8);
  key.position.set(2, 4, 3);
  scene.add(key);
  const rim = new THREE.DirectionalLight(0xffc4dd, 0.8);
  rim.position.set(-3, 2, -2);
  scene.add(rim);

  // 坐垫
  const cushion = new THREE.Mesh(new THREE.CylinderGeometry(1.0, 1.1, 0.22, 40), new THREE.MeshStandardMaterial({ color: 0xff9fb1, roughness: 0.8 }));
  cushion.position.y = -0.11;
  scene.add(cushion);

  const pivot = new THREE.Group();
  pivot.add(model);
  scene.add(pivot);

  function resize() {
    const r = wrap.getBoundingClientRect();
    const s = Math.max(1, Math.round(Math.min(r.width, r.height)));
    renderer.setSize(s, s, false);
  }
  resize();
  new ResizeObserver(resize).observe(wrap);

  // avatar.js 里的 Avatar 是全局常量（不在 window 上），直接按名字取
  // eslint-disable-next-line no-undef
  const A = typeof Avatar !== "undefined" ? Avatar : null;
  // 说话时轻轻点头：包一层原来的 Avatar.speaking
  let speaking = false;
  if (A) {
    const orig = A.speaking;
    A.speaking = (on) => { speaking = on; orig(on); };
  }

  // 眼神（整个身体）微微跟着鼠标
  let lookX = 0;
  addEventListener("pointermove", (e) => {
    const r = wrap.getBoundingClientRect();
    lookX = Math.max(-1, Math.min(1, (e.clientX - (r.left + r.width / 2)) / 500));
  });

  const clock = new THREE.Clock();
  let lastEmotion = "", emoT = 0;
  const lerp = (a, b, t) => a + (b - a) * t;
  function tick() {
    const dt = Math.min(clock.getDelta(), 0.05), t = clock.elapsedTime;
    const emotion = A?.current || "calm";
    if (emotion !== lastEmotion) { lastEmotion = emotion; emoT = 0; }
    emoT += dt;
    const cls = wrap.classList;
    let tilt = 0, nod = 0, bounce = 0;
    switch (emotion) {
      case "happy": bounce = emoT < 2 ? Math.abs(Math.sin(emoT * 8)) * 0.12 : 0; break;
      case "shy": tilt = 0.14; nod = 0.12; break;
      case "sad": nod = 0.2; break;
      case "worried": nod = 0.08; break;
      case "surprised": bounce = emoT < 0.6 ? Math.sin(emoT * 6) * 0.14 : 0; break;
      case "playful": tilt = Math.sin(t * 2.5) * 0.12; break;
      case "sleepy": nod = 0.14 + Math.sin(t) * 0.04; tilt = Math.sin(t * 0.7) * 0.06; break;
      case "missing": nod = -0.06; break;
    }
    if (cls.contains("purring")) { tilt += Math.sin(t * 40) * 0.015; bounce += Math.abs(Math.sin(t * 20)) * 0.02; }
    if (cls.contains("pondering")) tilt += 0.1;
    if (speaking) nod += Math.sin(t * 9) * 0.04;
    const breathe = 1 + Math.sin(t * 2.2) * 0.018;
    pivot.scale.set(1 / Math.sqrt(breathe), breathe, 1 / Math.sqrt(breathe));
    pivot.position.y = bounce;
    pivot.rotation.z = lerp(pivot.rotation.z, tilt, 0.12);
    pivot.rotation.x = lerp(pivot.rotation.x, nod, 0.1);
    pivot.rotation.y = lerp(pivot.rotation.y, lookX * 0.5 + Math.sin(t * 0.4) * 0.08, 0.08);
    renderer.render(scene, camera);
    requestAnimationFrame(tick);
  }
  tick();
}

main();
