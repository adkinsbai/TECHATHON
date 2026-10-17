// 世界积木：把“世界配方”里的每一项变成 3D 物体。地形、植物、地标、收集物、天气、噜噜的装扮。
import * as THREE from "three";

const rand = (a, b) => a + Math.random() * (b - a);
const pick = (arr) => arr[Math.floor(Math.random() * arr.length)];
const C = (hex) => new THREE.Color(hex);

// ---------- 读取当前章节的配方 ----------
export async function loadRecipe() {
  let id = new URLSearchParams(location.search).get("chapter");
  try { id = id || localStorage.getItem("chapter"); } catch {}
  id = id || "cabin";
  const m = /^w(\d+)$/.exec(id);
  if (!m) return { chapterId: id === "voyage" ? "voyage" : "cabin", recipe: null, worldId: null };
  try {
    const res = await fetch(`/api/worlds/${m[1]}`);
    if (!res.ok) throw new Error();
    const w = await res.json();
    return { chapterId: id, recipe: w.recipe, worldId: w.id, completed: !!w.completed };
  } catch {
    return { chapterId: "cabin", recipe: null, worldId: null };
  }
}

// ---------- 地形 ----------
// 返回 rawH(x,z)：不含“家”和出生点修整的原始高度
export function terrainFor(type, fbm) {
  switch (type) {
    case "snow": return (x, z) => 4 + fbm(x * 0.011 + 3, z * 0.011) * 12 + fbm(x * 0.05, z * 0.05, 3) * 0.8;
    case "candy": return (x, z) => 3.5 + fbm(x * 0.008 + 9, z * 0.008 + 2, 3) * 16;
    case "desert": return (x, z) => 2.8 + Math.sin(x * 0.045 + fbm(x * 0.01, z * 0.01, 2) * 4) * 2.2 + fbm(x * 0.012, z * 0.012 + 5, 3) * 5;
    case "crystal": return (x, z) => 3 + fbm(x * 0.013, z * 0.013 + 8) * 10 + Math.abs(fbm(x * 0.06 + 1, z * 0.06, 3)) * 4;
    case "islands":
    case "clouds": return (x, z) => -2.5 + fbm(x * 0.014 + 4, z * 0.014 + 1) * 17 + fbm(x * 0.05, z * 0.05, 3) * 1.2;
    case "forest":
    case "meadow":
    default: return (x, z) => 3.2 + fbm(x * 0.012 + 10, z * 0.012 + 3) * 9 + fbm(x * 0.05, z * 0.05, 3) * 1.1;
  }
}
export const isSea = (R) => R.water === "sea" || R.terrain === "islands" || R.terrain === "clouds";
export const hasGrass = (R) => !["desert", "snow", "crystal"].includes(R.terrain);

// ---------- 植物 ----------
// 返回 { meshes, place(x, h, z, scale) -> 碰撞半径 }
export function floraKit(type, colors, max) {
  const cols = colors.map(C);
  const lambert = (opts = {}) => new THREE.MeshLambertMaterial({ flatShading: true, ...opts });
  const trunkMat = new THREE.MeshLambertMaterial({ color: 0x9a6b4f });
  const parts = [];
  const add = (geo, mat, perTree = 1, colored = true) => {
    const mesh = new THREE.InstancedMesh(geo, mat, max * perTree);
    mesh.castShadow = mesh.receiveShadow = true;
    mesh.count = 0;
    parts.push({ mesh, colored });
    return mesh;
  };
  const m = new THREE.Matrix4(), q = new THREE.Quaternion(), s = new THREE.Vector3(), v = new THREE.Vector3(), up = new THREE.Vector3(0, 1, 0);
  const put = (mesh, x, y, z, sx, sy, sz, rot, color) => {
    q.setFromAxisAngle(up, rot);
    m.compose(v.set(x, y, z), q, s.set(sx, sy, sz));
    mesh.setMatrixAt(mesh.count, m);
    if (color) mesh.setColorAt(mesh.count, color);
    mesh.count++;
  };
  let place;
  switch (type) {
    case "pines": {
      const trunk = add(new THREE.CylinderGeometry(0.2, 0.3, 2.4, 6), trunkMat, 1, false);
      const cone = add(new THREE.ConeGeometry(1.7, 3.6, 7), lambert(), 2);
      place = (x, h, z, sc) => {
        const c = pick(cols), r = rand(0, 6);
        put(trunk, x, h + 1.1 * sc, z, sc, sc, sc, r);
        put(cone, x, h + 3.2 * sc, z, sc, sc, sc, r, c);
        put(cone, x, h + 5.1 * sc, z, sc * 0.72, sc * 0.8, sc * 0.72, r, c.clone().offsetHSL(0, 0, 0.06));
        return 0.4 * sc;
      };
      break;
    }
    case "mushrooms": {
      const stem = add(new THREE.CylinderGeometry(0.35, 0.5, 3, 10), new THREE.MeshLambertMaterial({ color: 0xfff3e0 }), 1, false);
      const cap = add(new THREE.SphereGeometry(1.8, 16, 10, 0, Math.PI * 2, 0, Math.PI / 2), lambert({ flatShading: false }));
      const dots = add(new THREE.SphereGeometry(0.22, 8, 6), new THREE.MeshLambertMaterial({ color: 0xffffff }), 5, false);
      place = (x, h, z, sc) => {
        const r = rand(0, 6);
        put(stem, x, h + 1.4 * sc, z, sc, sc, sc, r);
        put(cap, x, h + 2.8 * sc, z, sc, sc * 0.8, sc, r, pick(cols));
        for (let i = 0; i < 5; i++) {
          const a = rand(0, Math.PI * 2), rr = rand(0.4, 1.4) * sc;
          put(dots, x + Math.cos(a) * rr, h + 2.8 * sc + Math.sqrt(Math.max(0, (1.8 * sc) ** 2 - rr * rr)) * 0.8, z + Math.sin(a) * rr, sc, sc * 0.5, sc, 0);
        }
        return 0.45 * sc;
      };
      break;
    }
    case "crystals": {
      const mat = new THREE.MeshStandardMaterial({ flatShading: true, roughness: 0.15, metalness: 0.1, transparent: true, opacity: 0.85, emissive: 0x6a4fb0, emissiveIntensity: 0.35 });
      const shard = add(new THREE.OctahedronGeometry(1, 0), mat, 4);
      place = (x, h, z, sc) => {
        const c = pick(cols);
        for (let i = 0; i < 4; i++) {
          const a = rand(0, 6), d = i ? rand(0.4, 1.3) * sc : 0, hh = rand(1.5, 3.5) * sc * (i ? 0.6 : 1);
          put(shard, x + Math.cos(a) * d, h + hh * 0.8, z + Math.sin(a) * d, 0.5 * sc, hh, 0.5 * sc, a, c);
        }
        return 0.6 * sc;
      };
      break;
    }
    case "coral": {
      const branch = add(new THREE.CapsuleGeometry(0.28, 2.2, 4, 8), lambert({ flatShading: false }), 5);
      place = (x, h, z, sc) => {
        const c = pick(cols);
        for (let i = 0; i < 5; i++) {
          const g = new THREE.Euler(rand(-0.6, 0.6), rand(0, 6), rand(-0.6, 0.6));
          q.setFromEuler(g);
          m.compose(v.set(x + rand(-0.5, 0.5) * sc, h + 1.3 * sc, z + rand(-0.5, 0.5) * sc), q, s.set(sc, sc * rand(0.7, 1.4), sc));
          branch.setMatrixAt(branch.count, m);
          branch.setColorAt(branch.count++, c);
        }
        return 0.5 * sc;
      };
      break;
    }
    case "cactus": {
      const body = add(new THREE.CapsuleGeometry(0.45, 2.6, 4, 10), lambert({ flatShading: false }), 3);
      place = (x, h, z, sc) => {
        const c = pick(cols);
        put(body, x, h + 1.7 * sc, z, sc, sc, sc, 0, c);
        put(body, x + 0.75 * sc, h + 2.1 * sc, z, sc * 0.6, sc * 0.4, sc * 0.6, 0, c);
        put(body, x - 0.75 * sc, h + 1.6 * sc, z, sc * 0.6, sc * 0.35, sc * 0.6, 0, c);
        return 0.5 * sc;
      };
      break;
    }
    case "lollipops": {
      const stick = add(new THREE.CylinderGeometry(0.12, 0.12, 3.4, 8), new THREE.MeshLambertMaterial({ color: 0xffffff }), 1, false);
      const candy = add(new THREE.TorusGeometry(0.9, 0.42, 10, 24), lambert({ flatShading: false }));
      place = (x, h, z, sc) => {
        const r = rand(0, 6);
        put(stick, x, h + 1.7 * sc, z, sc, sc, sc, r);
        put(candy, x, h + 3.8 * sc, z, sc, sc, sc, r, pick(cols));
        return 0.3 * sc;
      };
      break;
    }
    case "lanterns": {
      const trunk = add(new THREE.CylinderGeometry(0.18, 0.28, 2.6, 6), trunkMat, 1, false);
      const crown = add(new THREE.IcosahedronGeometry(1.4, 1), lambert({ color: 0x5f9e7a }), 1, false);
      // 灯笼用不受光照影响的材质，颜色就是自己发出的光（每盏灯颜色不同）
      const lamp = add(new THREE.SphereGeometry(0.22, 10, 8), new THREE.MeshBasicMaterial(), 4);
      place = (x, h, z, sc) => {
        put(trunk, x, h + 1.2 * sc, z, sc, sc, sc, 0);
        put(crown, x, h + 3.3 * sc, z, sc, sc * 0.9, sc, rand(0, 6));
        for (let i = 0; i < 4; i++) {
          const a = (i / 4) * Math.PI * 2 + rand(0, 1);
          put(lamp, x + Math.cos(a) * 1.3 * sc, h + 2.4 * sc, z + Math.sin(a) * 1.3 * sc, sc, sc * 1.3, sc, 0, pick(cols));
        }
        return 0.35 * sc;
      };
      break;
    }
    case "round_trees":
    default: {
      const trunk = add(new THREE.CylinderGeometry(0.22, 0.34, 2.8, 7), trunkMat, 1, false);
      const blob = add(new THREE.IcosahedronGeometry(1.7, 1), lambert());
      place = (x, h, z, sc) => {
        put(trunk, x, h + 1.3 * sc, z, sc, sc, sc, rand(0, 6));
        put(blob, x, h + 3.6 * sc, z, sc * rand(0.9, 1.2), sc * rand(0.9, 1.15), sc * rand(0.9, 1.2), rand(0, 6), pick(cols));
        return 0.45 * sc;
      };
    }
  }
  return { meshes: parts.map((p) => p.mesh), place };
}

// ---------- 地标 ----------
// 返回 { group, radius（碰撞半径）, top（顶部高度，用来放名字） }
export function buildLandmark(type, accentHex) {
  const g = new THREE.Group();
  const accent = C(accentHex);
  const mat = (color, extra = {}) => new THREE.MeshStandardMaterial({ color, roughness: 0.75, ...extra });
  const glow = (color) => new THREE.MeshStandardMaterial({ color, emissive: color, emissiveIntensity: 1.6 });
  const add = (geo, m, x = 0, y = 0, z = 0) => { const mesh = new THREE.Mesh(geo, m); mesh.position.set(x, y, z); mesh.castShadow = mesh.receiveShadow = true; g.add(mesh); return mesh; };
  const wood = mat(0xc99a72), stone = mat(0xe8dcf0), white = mat(0xfff8f0), roof = mat(accent);
  let radius = 3, top = 6;
  switch (type) {
    case "lighthouse": {
      for (let i = 0; i < 5; i++) add(new THREE.CylinderGeometry(1.6 - i * 0.18, 1.8 - i * 0.18, 2.4, 20), i % 2 ? roof : white, 0, 1.2 + i * 2.4);
      add(new THREE.CylinderGeometry(1.1, 1.1, 1.6, 16), glow(0xfff1b0), 0, 13.2);
      add(new THREE.ConeGeometry(1.4, 1.6, 16), roof, 0, 14.8);
      // 灯光：绕着塔顶转的光束
      const pivot = new THREE.Group();
      pivot.position.y = 13.2;
      g.add(pivot);
      const beam = new THREE.Mesh(new THREE.ConeGeometry(2.5, 26, 24, 1, true), new THREE.MeshBasicMaterial({ color: 0xfff1b0, transparent: true, opacity: 0.18, side: THREE.DoubleSide, depthWrite: false, blending: THREE.AdditiveBlending }));
      beam.position.x = 13;
      beam.rotation.z = Math.PI / 2;
      pivot.add(beam);
      g.userData.spin = pivot;
      radius = 2; top = 16.5;
      break;
    }
    case "library": {
      add(new THREE.BoxGeometry(9, 5, 6), stone, 0, 2.5);
      for (const x of [-3.5, -1.2, 1.2, 3.5]) add(new THREE.CylinderGeometry(0.35, 0.35, 4.6, 10), white, x, 2.3, 3.3);
      const r = add(new THREE.ConeGeometry(6.4, 2.6, 4), roof, 0, 6.3);
      r.rotation.y = Math.PI / 4; r.scale.z = 0.7;
      add(new THREE.BoxGeometry(1.8, 2.8, 0.2), glow(0xffd59e), 0, 1.4, 3.05);
      for (let i = 0; i < 8; i++) add(new THREE.BoxGeometry(0.5, 0.7, 0.12), mat(new THREE.Color().setHSL(Math.random(), 0.6, 0.7)), rand(-4, 4), rand(1, 4), 3.02);
      radius = 5.5; top = 8.5;
      break;
    }
    case "tower": {
      add(new THREE.CylinderGeometry(2, 2.4, 14, 16), stone, 0, 7);
      add(new THREE.ConeGeometry(2.8, 4, 16), roof, 0, 16);
      for (let i = 0; i < 4; i++) add(new THREE.BoxGeometry(0.6, 1, 0.2), glow(0xffd59e), Math.sin(i * 1.6) * 2.05, 4 + i * 2.6, Math.cos(i * 1.6) * 2.05).lookAt(0, 4 + i * 2.6, 0);
      radius = 2.6; top = 18.5;
      break;
    }
    case "giant_tree": {
      add(new THREE.CylinderGeometry(1.4, 2.4, 12, 10), mat(0x9a6b4f), 0, 6);
      for (let i = 0; i < 6; i++) add(new THREE.IcosahedronGeometry(rand(3.5, 5), 1), mat(accent.clone().offsetHSL(rand(-0.05, 0.05), 0, rand(-0.1, 0.1)), { flatShading: true }), rand(-3, 3), rand(12, 16), rand(-3, 3));
      for (let i = 0; i < 10; i++) add(new THREE.SphereGeometry(0.25, 8, 6), glow(0xfff1b0), rand(-5, 5), rand(9, 13), rand(-5, 5));
      radius = 2.4; top = 20;
      break;
    }
    case "windmill": {
      add(new THREE.CylinderGeometry(1.6, 2.4, 9, 8), white, 0, 4.5);
      add(new THREE.ConeGeometry(2.2, 2.4, 8), roof, 0, 10.2);
      const hub = new THREE.Group(); hub.position.set(0, 8.5, 2.2); g.add(hub);
      for (let i = 0; i < 4; i++) { const b = new THREE.Mesh(new THREE.BoxGeometry(0.9, 6, 0.12), wood); b.position.y = 3; const arm = new THREE.Group(); arm.rotation.z = (i * Math.PI) / 2; arm.add(b); hub.add(arm); }
      g.userData.spinZ = hub;
      radius = 2.4; top = 12;
      break;
    }
    case "ferris_wheel": {
      const wheel = new THREE.Group(); wheel.position.y = 9; g.add(wheel);
      wheel.add(new THREE.Mesh(new THREE.TorusGeometry(7, 0.18, 8, 48), white));
      for (let i = 0; i < 10; i++) {
        const a = (i / 10) * Math.PI * 2;
        const spoke = new THREE.Mesh(new THREE.CylinderGeometry(0.06, 0.06, 7), white); spoke.position.set(Math.cos(a) * 3.5, Math.sin(a) * 3.5, 0); spoke.rotation.z = a - Math.PI / 2; wheel.add(spoke);
        const cab = new THREE.Mesh(new THREE.BoxGeometry(1, 1, 1), mat(new THREE.Color().setHSL(i / 10, 0.6, 0.72))); cab.position.set(Math.cos(a) * 7, Math.sin(a) * 7 - 0.6, 0); wheel.add(cab);
      }
      for (const x of [-2, 2]) { const leg = add(new THREE.CylinderGeometry(0.2, 0.3, 10), white, x * 0.6, 4.5, 0); leg.rotation.z = x * 0.08; }
      g.userData.spinZ = wheel;
      radius = 2; top = 17;
      break;
    }
    case "bell": {
      for (const x of [-1.8, 1.8]) add(new THREE.BoxGeometry(0.6, 6, 0.6), wood, x, 3);
      add(new THREE.BoxGeometry(4.6, 0.6, 0.8), wood, 0, 6.2);
      add(new THREE.CylinderGeometry(0.6, 1.4, 2, 20, 1, true), mat(0xf2c66d, { metalness: 0.6, roughness: 0.3, side: THREE.DoubleSide }), 0, 4.8);
      radius = 2.4; top = 7.5;
      break;
    }
    case "arch": {
      const a = add(new THREE.TorusGeometry(4, 0.6, 12, 32, Math.PI), stone, 0, 0);
      a.rotation.z = 0;
      for (let i = 0; i < 9; i++) { const ang = (i / 8) * Math.PI; add(new THREE.SphereGeometry(0.35, 10, 8), glow(accent), Math.cos(ang) * 4, Math.sin(ang) * 4, 0.6); }
      radius = 0.8; top = 6;
      break;
    }
    case "bridge": {
      const b = add(new THREE.TorusGeometry(6, 0.5, 8, 32, Math.PI), wood, 0, -2.5);
      b.scale.set(1, 0.5, 4);
      for (let i = -5; i <= 5; i += 2) add(new THREE.CylinderGeometry(0.12, 0.12, 1.2), white, i, 0.8 + Math.cos((i / 6) * 1.2) * 0.8, 1.6);
      radius = 1; top = 4;
      break;
    }
    case "observatory": {
      add(new THREE.CylinderGeometry(3.4, 3.6, 4, 20), stone, 0, 2);
      add(new THREE.SphereGeometry(3.4, 24, 12, 0, Math.PI * 2, 0, Math.PI / 2), mat(accent, { metalness: 0.4, roughness: 0.3 }), 0, 4);
      const scope = add(new THREE.CylinderGeometry(0.5, 0.7, 5, 12), mat(0xcfc2ff, { metalness: 0.6 }), 1.5, 7, 0);
      scope.rotation.z = -0.8;
      radius = 3.8; top = 9;
      break;
    }
    case "carousel": {
      add(new THREE.CylinderGeometry(4.5, 4.5, 0.5, 24), white, 0, 0.25);
      const spin = new THREE.Group(); g.add(spin);
      for (let i = 0; i < 6; i++) {
        const a = (i / 6) * Math.PI * 2;
        const pole = new THREE.Mesh(new THREE.CylinderGeometry(0.08, 0.08, 4), mat(0xf2c66d, { metalness: 0.6 })); pole.position.set(Math.cos(a) * 3.2, 2.5, Math.sin(a) * 3.2); spin.add(pole);
        const horse = new THREE.Mesh(new THREE.CapsuleGeometry(0.4, 1, 4, 8), mat(new THREE.Color().setHSL(i / 6, 0.6, 0.8))); horse.rotation.z = Math.PI / 2; horse.position.set(Math.cos(a) * 3.2, 1.8, Math.sin(a) * 3.2); spin.add(horse);
      }
      add(new THREE.ConeGeometry(5, 2.4, 24), roof, 0, 5.4);
      g.userData.spinY = spin;
      radius = 4.6; top = 8;
      break;
    }
    case "well": {
      add(new THREE.CylinderGeometry(1.6, 1.7, 1.4, 20, 1, true), stone, 0, 0.7).material.side = THREE.DoubleSide;
      add(new THREE.CircleGeometry(1.5, 20), glow(0x9fe6ff), 0, 0.5).rotation.x = -Math.PI / 2;
      for (const x of [-1.4, 1.4]) add(new THREE.BoxGeometry(0.25, 3, 0.25), wood, x, 1.5);
      const r = add(new THREE.ConeGeometry(2.4, 1.4, 4), roof, 0, 3.6); r.rotation.y = Math.PI / 4;
      radius = 1.9; top = 5;
      break;
    }
    case "tent": {
      const t = add(new THREE.ConeGeometry(3.2, 4.2, 6), mat(accent, { flatShading: true }), 0, 2.1);
      t.rotation.y = 0.3;
      add(new THREE.BoxGeometry(1.2, 1.6, 0.1), glow(0xffd59e), 0, 0.8, 2.6);
      radius = 3; top = 5.5;
      break;
    }
    case "boat": {
      const hull = add(new THREE.SphereGeometry(3, 20, 10, 0, Math.PI * 2, Math.PI / 2, Math.PI / 2), wood, 0, 1.2);
      hull.scale.set(0.55, 0.6, 1.2);
      add(new THREE.CylinderGeometry(0.12, 0.12, 6), white, 0, 4);
      const sail = add(new THREE.PlaneGeometry(2.4, 3.4), mat(0xffffff, { side: THREE.DoubleSide }), 0, 4.6, 0.2);
      sail.rotation.y = Math.PI / 2;
      add(new THREE.SphereGeometry(0.25, 8, 6), glow(0xffd59e), 0, 1.5, 3);
      g.userData.bob = true;
      radius = 2; top = 8;
      break;
    }
    case "statue":
    default: {
      add(new THREE.CylinderGeometry(1.6, 1.8, 1.4, 16), stone, 0, 0.7);
      add(new THREE.SphereGeometry(1.2, 20, 14), white, 0, 2.6).scale.set(1.15, 0.95, 1);
      add(new THREE.SphereGeometry(0.95, 20, 14), white, 0, 3.9).scale.set(1.15, 1, 1);
      for (const x of [-0.5, 0.5]) add(new THREE.ConeGeometry(0.28, 0.5, 10), white, x, 4.75, 0).rotation.z = -x * 0.5;
      radius = 1.9; top = 6;
    }
  }
  return { group: g, radius, top };
}
export function animateLandmark(g, t) {
  const u = g.userData;
  if (u.spin) u.spin.rotation.y = t * 0.6;
  if (u.spinZ) u.spinZ.rotation.z = t * 0.25;
  if (u.spinY) u.spinY.rotation.y = t * 0.4;
  if (u.bob) g.rotation.z = Math.sin(t * 0.8) * 0.05;
}

// ---------- 收集物 ----------
export function buildItem(shape, colorHex) {
  const color = C(colorHex);
  const mat = new THREE.MeshStandardMaterial({ color, emissive: color, emissiveIntensity: 0.9, roughness: 0.3, metalness: 0.2, side: THREE.DoubleSide });
  const g = new THREE.Group();
  let geo;
  const shapeGeo = (pts, depth = 0.16) => new THREE.ExtrudeGeometry(new THREE.Shape(pts.map(([x, y]) => new THREE.Vector2(x, y))), { depth, bevelEnabled: true, bevelSize: 0.04, bevelThickness: 0.04, bevelSegments: 2 }).center();
  switch (shape) {
    case "star": {
      const pts = [];
      for (let i = 0; i < 10; i++) { const a = (i / 10) * Math.PI * 2 + Math.PI / 2, r = i % 2 ? 0.28 : 0.65; pts.push([Math.cos(a) * r, Math.sin(a) * r]); }
      geo = shapeGeo(pts);
      break;
    }
    case "heart": {
      const s = new THREE.Shape();
      s.moveTo(0, -0.55); s.bezierCurveTo(-0.9, 0.1, -0.45, 0.7, 0, 0.3); s.bezierCurveTo(0.45, 0.7, 0.9, 0.1, 0, -0.55);
      geo = new THREE.ExtrudeGeometry(s, { depth: 0.18, bevelEnabled: true, bevelSize: 0.05, bevelThickness: 0.05 }).center();
      break;
    }
    case "page": case "letter": geo = new THREE.BoxGeometry(0.7, 0.9, 0.04); break;
    case "shell": geo = new THREE.SphereGeometry(0.5, 16, 8, 0, Math.PI * 2, 0, Math.PI / 2.2); break;
    case "key": {
      const k = new THREE.Group();
      k.add(new THREE.Mesh(new THREE.TorusGeometry(0.28, 0.08, 8, 20), mat));
      const shaft = new THREE.Mesh(new THREE.BoxGeometry(0.1, 0.8, 0.1), mat); shaft.position.y = -0.62; k.add(shaft);
      const tooth = new THREE.Mesh(new THREE.BoxGeometry(0.25, 0.1, 0.1), mat); tooth.position.set(0.12, -0.9, 0); k.add(tooth);
      g.add(k);
      break;
    }
    case "feather": geo = new THREE.SphereGeometry(0.5, 12, 8); break;
    case "crystal": geo = new THREE.OctahedronGeometry(0.5, 0); break;
    case "note": {
      const n = new THREE.Group();
      const head = new THREE.Mesh(new THREE.SphereGeometry(0.26, 14, 10), mat); head.scale.set(1.2, 0.9, 0.7); n.add(head);
      const stem = new THREE.Mesh(new THREE.BoxGeometry(0.07, 0.9, 0.07), mat); stem.position.set(0.27, 0.45, 0); n.add(stem);
      const flag = new THREE.Mesh(new THREE.BoxGeometry(0.3, 0.12, 0.07), mat); flag.position.set(0.4, 0.82, 0); flag.rotation.z = -0.5; n.add(flag);
      g.add(n);
      break;
    }
    case "flower": {
      const f = new THREE.Group();
      for (let i = 0; i < 6; i++) { const p = new THREE.Mesh(new THREE.SphereGeometry(0.22, 10, 8), mat); const a = (i / 6) * Math.PI * 2; p.position.set(Math.cos(a) * 0.3, Math.sin(a) * 0.3, 0); p.scale.z = 0.4; f.add(p); }
      f.add(new THREE.Mesh(new THREE.SphereGeometry(0.18, 10, 8), new THREE.MeshStandardMaterial({ color: 0xfff1a0, emissive: 0xffd86b, emissiveIntensity: 0.8 })));
      g.add(f);
      break;
    }
    default: geo = new THREE.IcosahedronGeometry(0.5, 0);
  }
  if (geo) { const mesh = new THREE.Mesh(geo, mat); if (shape === "feather") mesh.scale.set(0.35, 1.3, 0.15); g.add(mesh); }
  return g;
}

// ---------- 天气粒子 ----------
// mode：float（原地飘，萤火虫/星屑）、fall（往下落）、rise（往上飘）
export function weatherConfig(type, accentHex) {
  switch (type) {
    case "petals": return { count: 1400, color: "#ffc4dd", size: 34, mode: "fall", speed: 1.4, sway: 1.6 };
    case "snow": return { count: 2400, color: "#ffffff", size: 26, mode: "fall", speed: 1.8, sway: 0.8 };
    case "rain": return { count: 3000, color: "#bfe6ff", size: 14, mode: "fall", speed: 14, sway: 0.05 };
    case "leaves": return { count: 1000, color: "#ffb36b", size: 34, mode: "fall", speed: 1.6, sway: 2 };
    case "bubbles": return { count: 900, color: "#bff3ff", size: 40, mode: "rise", speed: 1.2, sway: 1 };
    case "stars": return { count: 1400, color: "#fff2b0", size: 22, mode: "float", speed: 0, sway: 0.4 };
    case "fireflies": return { count: 900, color: accentHex || "#fff2b0", size: 28, mode: "float", speed: 0, sway: 1.5 };
    case "clear":
    default: return { count: 300, color: "#fff6dc", size: 20, mode: "float", speed: 0, sway: 1 };
  }
}

// ---------- 噜噜的装扮 ----------
export function dressCat(cat, outfit, colorHex) {
  if (!outfit || outfit === "none") return;
  const color = C(colorHex);
  const mat = new THREE.MeshToonMaterial({ color });
  const mesh = (geo, parent, x, y, z) => { const m = new THREE.Mesh(geo, mat); m.position.set(x, y, z); m.castShadow = true; parent.add(m); return m; };
  const head = cat.head, body = cat.body;
  switch (outfit) {
    case "scarf": {
      const s = mesh(new THREE.TorusGeometry(0.44, 0.1, 10, 28), body, 0, 0.84, 0.04); s.rotation.x = Math.PI / 2;
      const tail = mesh(new THREE.BoxGeometry(0.18, 0.45, 0.08), body, 0.22, 0.62, 0.45); tail.rotation.z = 0.25;
      break;
    }
    case "hat": {
      const h = mesh(new THREE.ConeGeometry(0.3, 0.65, 18), head, 0.05, 0.75, 0); h.rotation.z = -0.15;
      mesh(new THREE.SphereGeometry(0.08, 10, 8), head, 0.12, 1.08, 0).material = new THREE.MeshToonMaterial({ color: 0xfff1b0 });
      break;
    }
    case "cape": {
      const c = mesh(new THREE.CylinderGeometry(0.5, 0.85, 0.95, 20, 1, true, Math.PI * 0.6, Math.PI * 0.8), body, 0, 0.55, -0.05);
      c.material.side = THREE.DoubleSide;
      break;
    }
    case "flower_crown": {
      const ring = new THREE.Group(); ring.position.set(0, 0.42, 0); ring.rotation.x = -0.15; head.add(ring);
      for (let i = 0; i < 9; i++) {
        const a = (i / 9) * Math.PI * 2;
        const f = new THREE.Mesh(new THREE.SphereGeometry(0.08, 8, 6), new THREE.MeshToonMaterial({ color: new THREE.Color().setHSL((i / 9 + 0.9) % 1, 0.7, 0.75) }));
        f.position.set(Math.cos(a) * 0.4, 0, Math.sin(a) * 0.35);
        ring.add(f);
      }
      break;
    }
    case "glasses": {
      for (const sx of [-1, 1]) { const r = mesh(new THREE.TorusGeometry(0.13, 0.022, 8, 24), head, 0.21 * sx, 0.02, 0.52); r.material = new THREE.MeshToonMaterial({ color }); }
      mesh(new THREE.BoxGeometry(0.14, 0.02, 0.02), head, 0, 0.04, 0.54);
      break;
    }
    case "bow": {
      for (const sx of [-1, 1]) { const b = mesh(new THREE.ConeGeometry(0.12, 0.22, 12), head, 0.28 + 0.1 * sx, 0.42, 0.12); b.rotation.z = (Math.PI / 2) * sx; }
      mesh(new THREE.SphereGeometry(0.06, 8, 6), head, 0.28, 0.42, 0.12);
      break;
    }
    case "backpack": {
      mesh(new THREE.BoxGeometry(0.6, 0.6, 0.35), body, 0, 0.62, -0.62);
      for (const sx of [-1, 1]) { const st = mesh(new THREE.TorusGeometry(0.3, 0.03, 6, 16, Math.PI), body, 0.22 * sx, 0.7, -0.3); st.rotation.y = Math.PI / 2; }
      break;
    }
  }
}

// ---------- 小工具 ----------
export function textSprite(text, color = "#e07a8b") {
  const c = document.createElement("canvas");
  c.width = 512; c.height = 96;
  const g = c.getContext("2d");
  g.fillStyle = "rgba(255,248,240,.88)";
  g.beginPath(); g.roundRect(8, 8, 496, 80, 40); g.fill();
  g.fillStyle = color; g.font = "bold 40px 'LXGW WenKai Screen','Microsoft YaHei'"; g.textAlign = "center"; g.textBaseline = "middle";
  g.fillText(text, 256, 50);
  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;
  const s = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, transparent: true, depthWrite: false }));
  s.scale.set(5.2, 0.98, 1);
  return s;
}
export { rand, pick };
