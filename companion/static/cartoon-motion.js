// 程序化卡通动作：不需要骨骼，直接让整个模型“活”起来。免费、所有生成模型都能用，符合绘本卡通的感觉。
// 动物：呼吸（轻微压扁拉伸）+ 晃动；隔几秒在展区里蹦跳着走到附近一点，再转回来面向游客。
// 树：轻轻随风摇；停在树上的鸟：上下点头。有骨骼动画的模型（Tripo 绑骨后）不走这里。
import * as THREE from 'three';

const TAU = Math.PI * 2;
const ease = (x) => x * x * (3 - 2 * x);
const angleTo = (from, to) => { let d = (to - from) % TAU; if (d > Math.PI) d -= TAU; if (d < -Math.PI) d += TAU; return d; };

export function attachMotion(root, body, definition, {perched = false, fighting = false} = {}) {
  const seed = (root.position.x * 12.9898 + root.position.z * 78.233) % 1;
  const rand = (() => { let s = Math.abs(Math.sin(seed * 43758.5453)) || .5; return () => (s = (s * 9301 + 49297) % 233280) / 233280; })();
  root.userData.motion = {
    kind: definition.kind, perched, fighting, body, phase: rand() * TAU, rand,
    baseScale: body.scale.clone(),   // 模型的米制归一化缩放，压扁拉伸要乘在它上面
    height: definition.height_m || 1,
    homeYaw: root.rotation.y, state: 'idle', until: 2 + rand() * 6, t0: 0, from: null, to: null,
    wander: Math.min(2.4, .6 + (definition.height_m || 1)),
  };
}

// hop：0..1 的蹦跳进度；返回离地高度和压扁拉伸系数
function hopShape(p, height) {
  const lift = Math.sin(p * Math.PI) * Math.min(.22, .08 + height * .05);
  const squash = p < .12 ? 1 - (1 - p / .12) * .12 : p > .88 ? 1 - ((p - .88) / .12) * .12 : 1 + Math.sin(p * Math.PI) * .06;
  return {lift, squash};
}

export function updateMotion(root, t, dt, heightAt) {
  const m = root.userData.motion;
  if (!m || root.userData.anim) return;
  const {body} = m;
  if (m.kind === 'plant') {           // 树：以底部为轴轻轻摇
    body.rotation.z = Math.sin(t * .7 + m.phase) * .018;
    body.rotation.x = Math.sin(t * .53 + m.phase * 1.7) * .012;
    return;
  }
  if (m.kind !== 'animal') return;
  if (m.perched) {                    // 停在树上：点头、偶尔转头
    body.position.y = Math.abs(Math.sin(t * 2.4 + m.phase)) * .03;
    body.rotation.y = Math.sin(t * .6 + m.phase) * .5;
    return;
  }
  const breathe = Math.sin(t * 2.1 + m.phase);
  let sx = 1 - breathe * .012, sy = 1 + breathe * .022, lift = 0;
  body.rotation.z = Math.sin(t * 1.1 + m.phase) * .035;
  if (m.fighting) {                   // 打斗那一对由时间线移动，这里只加蹦跳
    const moving = root.userData.fightApproach || 0;
    if (moving > .05) { const h = hopShape((t * 2.6 + m.phase) % 1, m.height); lift = h.lift * 1.4; sy *= h.squash; sx /= Math.sqrt(h.squash); }
  } else {
    const base = root.userData.base;
    if (m.state === 'idle' && t > m.until) {
      const a = m.rand() * TAU, r = m.wander * (.4 + m.rand() * .6);
      m.from = root.position.clone(); m.to = new THREE.Vector3(base.x + Math.cos(a) * r, 0, base.z + Math.sin(a) * r);
      m.state = 'walk'; m.t0 = t; m.duration = Math.max(1.2, m.from.distanceTo(new THREE.Vector3(m.to.x, m.from.y, m.to.z)) / .9);
    }
    if (m.state === 'walk') {
      const p = Math.min(1, (t - m.t0) / m.duration), k = ease(p);
      root.position.x = m.from.x + (m.to.x - m.from.x) * k;
      root.position.z = m.from.z + (m.to.z - m.from.z) * k;
      const face = Math.atan2(m.to.x - m.from.x, m.to.z - m.from.z);
      root.rotation.y += angleTo(root.rotation.y, face) * Math.min(1, dt * 6);
      const h = hopShape(((t - m.t0) * 2.2) % 1, m.height);
      lift = h.lift; sy *= h.squash; sx /= Math.sqrt(h.squash);
      if (p >= 1) { m.state = 'turn'; m.t0 = t; }
    } else if (m.state === 'turn') {  // 走完转回来面向游客
      root.rotation.y += angleTo(root.rotation.y, m.homeYaw) * Math.min(1, dt * 3);
      if (Math.abs(angleTo(root.rotation.y, m.homeYaw)) < .03) { m.state = 'idle'; m.until = t + 4 + m.rand() * 6; }
    }
    root.position.y = heightAt(root.position.x, root.position.z);
    const c = root.userData.collider; if (c) { c.x = root.position.x; c.z = root.position.z; }
  }
  body.position.y = lift;
  body.scale.set(m.baseScale.x * sx, m.baseScale.y * sy, m.baseScale.z * sx);
}
