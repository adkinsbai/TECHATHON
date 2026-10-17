// 梦幻星球：第一人称 3D 世界。草原、湖泊、森林、彩色云、两个太阳，噜噜住在湖边的小木屋里。
import * as THREE from "three";
import { createSpace } from "/static/space.js?v=1";
import * as WG from "/static/worldgen.js?v=2";
import { loadCharacter, CHARACTER } from "/static/character.js?v=2";

// 伙伴的 3D 模型（噜噜）；加载失败就退回程序画的小猫
const CHAR_H = 1.9;
const CHAR_MODEL = await loadCharacter(CHAR_H).catch((e) => { console.warn("角色模型加载失败，使用备用形象", e); return null; });

// 当前章节：第一章/第二章是固定的梦幻星球；“w数字”是噜噜根据生活和梦编织出来的世界（按配方搭建）
const BOOT = await WG.loadRecipe();
const R = BOOT.recipe;          // 编织世界的配方；固定章节时为 null
const GEN = !!R;

const $ = (id) => document.getElementById(id);
const rand = (a, b) => a + Math.random() * (b - a);
const lerp = (a, b, t) => a + (b - a) * t;
const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
const smooth = (e0, e1, x) => { const t = clamp((x - e0) / (e1 - e0), 0, 1); return t * t * (3 - 2 * t); };
const pick = (arr) => arr[Math.floor(Math.random() * arr.length)];

// ======================= 噪声与地形 =======================
function hash(x, y) {
  let h = Math.imul(x | 0, 374761393) ^ Math.imul(y | 0, 668265263);
  h = Math.imul(h ^ (h >>> 13), 1274126177);
  return ((h ^ (h >>> 16)) >>> 0) / 4294967296;
}
function vnoise(x, y) {
  const xi = Math.floor(x), yi = Math.floor(y), xf = x - xi, yf = y - yi;
  const u = xf * xf * (3 - 2 * xf), v = yf * yf * (3 - 2 * yf);
  const a = hash(xi, yi), b = hash(xi + 1, yi), c = hash(xi, yi + 1), d = hash(xi + 1, yi + 1);
  return (a + (b - a) * u + (c - a) * v + (a - b - c + d) * u * v) * 2 - 1;
}
function fbm(x, y, oct = 4) {
  let s = 0, a = 0.5, f = 1;
  for (let i = 0; i < oct; i++) { s += a * vnoise(x * f, y * f); f *= 2; a *= 0.5; }
  return s;
}

const WATER = 0;
const LAKE = { x: 38, z: 20, r: 28 };
const CABIN = { x: -24, z: -16 };
const SPAWN = { x: 22, z: 70 };
const WORLD_R = 168;

// 编织世界：地形按配方；湖只在 water=lake 时有；海/群岛时海平面覆盖全图
const rawH = GEN ? WG.terrainFor(R.terrain, fbm) : (x, z) => 3.2 + fbm(x * 0.012 + 10, z * 0.012 + 3) * 9 + fbm(x * 0.05, z * 0.05, 3) * 1.1;
const SEA = GEN && WG.isSea(R);
const HAS_LAKE = !GEN || R.water === "lake";
const CABIN_Y = Math.max(2, rawH(CABIN.x, CABIN.z));
const lakeDist = (x, z) => Math.hypot(x - LAKE.x, (z - LAKE.z) * 1.25);
const lakeR = (x, z) => LAKE.r + fbm(x * 0.04, z * 0.04, 2) * 7;

// 从出生点到“家”（小木屋 / 编织世界里噜噜等你的地标）的小路
const PATH = new THREE.CatmullRomCurve3([
  new THREE.Vector3(SPAWN.x, 0, SPAWN.z - 4), new THREE.Vector3(8, 0, 44), new THREE.Vector3(-8, 0, 18),
  new THREE.Vector3(-18, 0, 0), new THREE.Vector3(CABIN.x, 0, CABIN.z + 6),
]);
const PATH_PTS = PATH.getSpacedPoints(80);
const pathDist2 = (x, z) => { let m = Infinity; for (const p of PATH_PTS) m = Math.min(m, (p.x - x) ** 2 + (p.z - z) ** 2); return m; };
const nearPath = (x, z, d) => PATH_PTS.some((p) => (p.x - x) ** 2 + (p.z - z) ** 2 < d * d);

function heightAt(x, z) {
  let h = rawH(x, z);
  if (HAS_LAKE) {
    const dl = lakeDist(x, z), rr = lakeR(x, z);
    h = lerp(h, Math.min(h, 1.0), smooth(rr + 18, rr + 4, dl));
    h = lerp(h, -3.2, smooth(rr + 6, rr - 8, dl));
  }
  // 群岛 / 浮空大陆：沿着小路垫出一条沙洲，保证从出生点能走到家
  if (SEA) h = Math.max(h, lerp(-3, 1.4, smooth(64, 9, pathDist2(x, z))));
  const dc = Math.hypot(x - CABIN.x, z - CABIN.z);
  h = lerp(h, CABIN_Y, smooth(20, 11, dc));
  const ds = Math.hypot(x - SPAWN.x, z - SPAWN.z);
  h = lerp(h, Math.max(h, 2.5), smooth(14, 4, ds));
  const r = Math.hypot(x, z);
  if (!SEA) h += smooth(118, 195, r) * 60 * (0.75 + 0.35 * fbm(x * 0.02 + 7, z * 0.02, 2));
  return h;
}
const forestNoise = (x, z) => fbm(x * 0.018 + 50, z * 0.018 - 20, 3);

// ======================= 渲染器与场景 =======================
const canvas = $("scene");
const renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
renderer.setPixelRatio(Math.min(devicePixelRatio, 1.5));
renderer.setSize(innerWidth, innerHeight);
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = 1.05;

const scene = new THREE.Scene();
const PAL = GEN ? R.palette : null;
const NIGHT = GEN && R.time === "night", DUSK = GEN && (R.time === "dusk" || R.time === "dawn");
const FOG = new THREE.Color(GEN ? PAL.horizon : "#f9c7dc");
if (NIGHT) renderer.toneMappingExposure = 0.95;
scene.fog = new THREE.Fog(FOG, 80, 380);
scene.background = FOG;

const camera = new THREE.PerspectiveCamera(70, innerWidth / innerHeight, 0.1, 2500);
camera.rotation.order = "YXZ";
addEventListener("resize", () => {
  camera.aspect = innerWidth / innerHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(innerWidth, innerHeight);
});

function canvasTexture(w, h, draw, srgb = true) {
  const c = document.createElement("canvas");
  c.width = w; c.height = h;
  draw(c.getContext("2d"), w, h);
  const t = new THREE.CanvasTexture(c);
  if (srgb) t.colorSpace = THREE.SRGBColorSpace;
  return t;
}
const glowTex = (color) => canvasTexture(128, 128, (g) => {
  const grd = g.createRadialGradient(64, 64, 0, 64, 64, 64);
  grd.addColorStop(0, color); grd.addColorStop(0.25, color + "aa"); grd.addColorStop(1, color + "00");
  g.fillStyle = grd; g.fillRect(0, 0, 128, 128);
});

// ======================= 天空：渐变 + 星星 + 两个太阳 =======================
const skyGroup = new THREE.Group();
scene.add(skyGroup);
const sky = new THREE.Mesh(new THREE.SphereGeometry(1200, 32, 16), new THREE.ShaderMaterial({
  side: THREE.BackSide, depthWrite: false, fog: false,
  uniforms: GEN ? {
    top: { value: new THREE.Color(PAL.sky_top) }, mid: { value: new THREE.Color(PAL.sky_mid) },
    horizon: { value: new THREE.Color(PAL.horizon) }, bottom: { value: new THREE.Color(PAL.horizon).lerp(new THREE.Color("#ffffff"), 0.25) },
  } : {
    top: { value: new THREE.Color("#3f2f8f") }, mid: { value: new THREE.Color("#b88be6") },
    horizon: { value: new THREE.Color("#ffc8dd") }, bottom: { value: new THREE.Color("#ffe2c6") },
  },
  vertexShader: "varying vec3 vDir; void main(){ vDir = normalize(position); gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }",
  fragmentShader: `uniform vec3 top, mid, horizon, bottom; varying vec3 vDir;
    void main(){
      float h = vDir.y;
      vec3 c = h > 0.0 ? mix(horizon, mid, smoothstep(0.0, 0.32, h)) : mix(horizon, bottom, smoothstep(0.0, -0.25, h));
      c = mix(c, top, smoothstep(0.32, 0.95, h));
      gl_FragColor = vec4(c, 1.0);
      #include <tonemapping_fragment>
      #include <colorspace_fragment>
    }`,
}));
sky.frustumCulled = false;
skyGroup.add(sky);

{ // 星星（淡淡的，白天也能看到几颗）
  const n = 1400, pos = new Float32Array(n * 3);
  for (let i = 0; i < n; i++) {
    const th = Math.random() * Math.PI * 2, y = rand(0.15, 1);
    const r = Math.sqrt(1 - y * y);
    pos.set([Math.cos(th) * r * 1100, y * 1100, Math.sin(th) * r * 1100], i * 3);
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.BufferAttribute(pos, 3));
  skyGroup.add(new THREE.Points(g, new THREE.PointsMaterial({
    color: 0xfff6e0, size: NIGHT ? 2.6 : 2, sizeAttenuation: false, transparent: true, opacity: NIGHT ? 1 : DUSK ? 0.8 : 0.65, fog: false, depthWrite: false,
  })));
}

// 天上的太阳和月亮：固定章节是一金一粉两个太阳；编织世界按配方来（0~3 个太阳、0~3 个月亮）
function celestialBodies() {
  if (!GEN) return [
    { dir: new THREE.Vector3(0.45, 0.32, -0.83).normalize(), color: "#ffd27a", r: 46, glow: 340, light: 0xffe0b0, li: 2.3 },
    { dir: new THREE.Vector3(-0.78, 0.2, -0.6).normalize(), color: "#ff8fcf", r: 28, glow: 230, light: 0xff9fd6, li: 0.9 },
  ];
  const out = [];
  const sunColors = ["#ffd27a", PAL.accent, "#ff8fcf"];
  const lowSun = DUSK ? 0.12 : 0.32;
  for (let i = 0; i < R.suns; i++) {
    const a = -0.6 + i * 0.9;
    out.push({ dir: new THREE.Vector3(Math.sin(a), lowSun + i * 0.08, -Math.cos(a)).normalize(), color: sunColors[i], r: 46 - i * 10, glow: 340 - i * 60,
      light: new THREE.Color(sunColors[i]).lerp(new THREE.Color("#ffffff"), 0.5).getHex(), li: (NIGHT ? 0.6 : 2.2) / (i + 1) });
  }
  for (let i = 0; i < R.moons; i++) {
    const a = 0.9 + i * 0.8;
    out.push({ dir: new THREE.Vector3(Math.sin(a), 0.45 + i * 0.1, -Math.cos(a)).normalize(), color: i ? "#cfe8ff" : "#fff4dc", r: 30 - i * 8, glow: 200,
      light: 0xc9d6ff, li: NIGHT ? 1.1 / (i + 1) : 0.3, moon: true });
  }
  if (!out.length) out.push({ dir: new THREE.Vector3(0.3, 0.5, -0.8).normalize(), color: "#ffffff", r: 0, glow: 0, light: 0xffffff, li: NIGHT ? 0.8 : 1.8, hidden: true });
  return out;
}
const SUNS = celestialBodies();
const sunLights = [];
for (const s of SUNS) {
  if (!s.hidden) {
    const disc = new THREE.Mesh(new THREE.SphereGeometry(s.r, 24, 16), new THREE.MeshBasicMaterial({ color: s.color, fog: false }));
    disc.position.copy(s.dir).multiplyScalar(1000);
    const halo = new THREE.Sprite(new THREE.SpriteMaterial({ map: glowTex(s.color), blending: THREE.AdditiveBlending, fog: false, depthWrite: false, transparent: true, opacity: s.moon ? 0.5 : 1 }));
    halo.scale.setScalar(s.glow);
    halo.position.copy(disc.position);
    skyGroup.add(disc, halo);
  }
  const L = new THREE.DirectionalLight(s.light, s.li);
  scene.add(L, L.target);
  sunLights.push(L);
}
const mainSun = sunLights[0];
mainSun.castShadow = true;
mainSun.shadow.mapSize.set(2048, 2048);
Object.assign(mainSun.shadow.camera, { left: -70, right: 70, top: 70, bottom: -70, near: 1, far: 320 });
mainSun.shadow.bias = -0.0004;
mainSun.shadow.normalBias = 0.04;
scene.add(GEN
  ? new THREE.HemisphereLight(new THREE.Color(PAL.sky_mid).lerp(new THREE.Color("#ffffff"), 0.5), new THREE.Color(PAL.ground_b), NIGHT ? 0.75 : 1.1)
  : new THREE.HemisphereLight(0xdccbff, 0x84d08f, 1.15));

// ======================= 地形 =======================
{
  const size = 420, seg = 280;
  const g = new THREE.PlaneGeometry(size, size, seg, seg);
  g.rotateX(-Math.PI / 2);
  const p = g.attributes.position, colors = new Float32Array(p.count * 3);
  const c = new THREE.Color(), sand = new THREE.Color("#f2d9ae"), g1 = new THREE.Color("#93d98a"), g2 = new THREE.Color("#5fbf7c"),
    meadow = new THREE.Color("#c4ea8e"), lav = new THREE.Color("#b8a2e3"), peak = new THREE.Color("#ffe0ef"), mud = new THREE.Color("#c9b48f");
  if (GEN) {
    g1.set(PAL.ground_a); g2.set(PAL.ground_b);
    meadow.set(PAL.ground_a).lerp(new THREE.Color("#ffffff"), 0.25);
    lav.set(PAL.sky_mid).lerp(new THREE.Color("#ffffff"), 0.3);
    if (R.terrain === "snow") { g1.set("#f4f8ff"); g2.set("#dfe8f7"); meadow.set("#ffffff"); }
    if (R.terrain === "desert") sand.set(PAL.ground_a);
  }
  for (let i = 0; i < p.count; i++) {
    const x = p.getX(i), z = p.getZ(i), h = heightAt(x, z);
    p.setY(i, h);
    const n = fbm(x * 0.04 + 3, z * 0.04, 3);
    c.copy(g1).lerp(g2, smooth(-0.3, 0.4, n)).lerp(meadow, smooth(0.25, 0.55, fbm(x * 0.03 - 9, z * 0.03 + 4, 2)) * 0.6);
    if (h < 0.7) c.lerp(sand, smooth(0.7, 0.2, h));
    if (h < -0.6) c.lerp(mud, 0.6);
    if (h > 12) c.lerp(lav, smooth(12, 24, h));
    if (h > 30) c.lerp(peak, smooth(30, 48, h));
    colors.set([c.r, c.g, c.b], i * 3);
  }
  g.setAttribute("color", new THREE.BufferAttribute(colors, 3));
  g.computeVertexNormals();
  const ground = new THREE.Mesh(g, new THREE.MeshLambertMaterial({ vertexColors: true }));
  ground.receiveShadow = true;
  scene.add(ground);
}

// ======================= 湖 / 海 =======================
// 编织世界里水的颜色跟着配色走；“云海”世界的水是白色的云
const waterColor = !GEN ? new THREE.Color(0x86d8f8)
  : R.terrain === "clouds" ? new THREE.Color("#fdf6ff")
  : new THREE.Color("#7fd3f7").lerp(new THREE.Color(PAL.sky_mid), 0.35);
const water = new THREE.Mesh(
  SEA ? new THREE.PlaneGeometry(1400, 1400).rotateX(-Math.PI / 2) : new THREE.CircleGeometry(LAKE.r + 20, 72).rotateX(-Math.PI / 2),
  new THREE.MeshStandardMaterial({
    color: waterColor, transparent: true, opacity: GEN && R.terrain === "clouds" ? 0.92 : 0.8, roughness: 0.06, metalness: 0.2,
    emissive: waterColor.clone().multiplyScalar(0.45), emissiveIntensity: NIGHT ? 0.5 : 0.18,
  }));
if (SEA) water.position.set(0, WATER, 0);
else { water.position.set(LAKE.x, WATER, LAKE.z); water.scale.z = 1 / 1.25; }
water.receiveShadow = true;
water.visible = HAS_LAKE || SEA;
scene.add(water);
if (HAS_LAKE && !SEA) { // 睡莲
  const pads = new THREE.InstancedMesh(new THREE.CylinderGeometry(0.7, 0.7, 0.05, 14), new THREE.MeshLambertMaterial({ color: 0x5ec07a }), 40);
  const lotus = new THREE.InstancedMesh(new THREE.IcosahedronGeometry(0.28, 0), new THREE.MeshLambertMaterial({ color: 0xffffff, flatShading: true }), 40);
  const m = new THREE.Matrix4(), col = new THREE.Color();
  for (let i = 0; i < 40; i++) {
    let x, z;
    do { x = LAKE.x + rand(-34, 34); z = LAKE.z + rand(-26, 26); } while (heightAt(x, z) > -1.2);
    m.makeTranslation(x, WATER + 0.03, z);
    pads.setMatrixAt(i, m);
    m.makeTranslation(x + 0.2, WATER + 0.22, z);
    lotus.setMatrixAt(i, m);
    lotus.setColorAt(i, col.set(pick(["#ffb3d1", "#fff0f6", "#e4c6ff", "#ffd59e"])));
  }
  scene.add(pads, lotus);
}

// ======================= 草（随风摇） =======================
const clock = new THREE.Clock();
const grassUniforms = {
  uTime: { value: 0 },
  uBase: { value: GEN ? new THREE.Color(PAL.ground_b).multiplyScalar(0.6) : new THREE.Color("#2f8048") },
  uTip: { value: GEN ? new THREE.Color(PAL.ground_a).lerp(new THREE.Color("#ffffff"), 0.2) : new THREE.Color("#b6ec86") },
};
if (!GEN || WG.hasGrass(R)) {
  const blade = new THREE.BufferGeometry();
  blade.setAttribute("position", new THREE.Float32BufferAttribute([-0.05, 0, 0, 0.05, 0, 0, -0.035, 0.22, 0, 0.035, 0.22, 0, 0, 0.45, 0], 3));
  blade.setAttribute("uv", new THREE.Float32BufferAttribute([0, 0, 1, 0, 0, 0.5, 1, 0.5, 0.5, 1], 2));
  blade.setIndex([0, 1, 2, 2, 1, 3, 2, 3, 4]);
  const mat = new THREE.ShaderMaterial({
    uniforms: THREE.UniformsUtils.merge([THREE.UniformsLib.fog, grassUniforms]),
    side: THREE.DoubleSide, fog: true,
    vertexShader: `#include <common>
      #include <fog_pars_vertex>
      uniform float uTime; varying vec2 vUv; varying vec3 vCol;
      void main(){
        vUv = uv;
        vec4 wp = modelMatrix * instanceMatrix * vec4(position, 1.0);
        float k = uv.y * uv.y;
        float sway = sin(uTime * 1.7 + wp.x * 0.32 + wp.z * 0.21) * 0.22 + sin(uTime * 3.1 + wp.x * 0.9) * 0.05;
        wp.x += sway * k; wp.z += sway * 0.6 * k;
        #ifdef USE_INSTANCING_COLOR
          vCol = instanceColor;
        #else
          vCol = vec3(1.0);
        #endif
        vec4 mvPosition = viewMatrix * wp;
        gl_Position = projectionMatrix * mvPosition;
        #include <fog_vertex>
      }`,
    fragmentShader: `#include <common>
      #include <fog_pars_fragment>
      uniform vec3 uBase, uTip; varying vec2 vUv; varying vec3 vCol;
      void main(){
        gl_FragColor = vec4(mix(uBase, uTip * vCol, vUv.y), 1.0);
        #include <tonemapping_fragment>
        #include <colorspace_fragment>
        #include <fog_fragment>
      }`,
  });
  mat.uniforms.uTime = grassUniforms.uTime;
  const N = 80000;
  const grass = new THREE.InstancedMesh(blade, mat, N);
  const m = new THREE.Matrix4(), q = new THREE.Quaternion(), s = new THREE.Vector3(), v = new THREE.Vector3(), col = new THREE.Color(), up = new THREE.Vector3(0, 1, 0);
  let n = 0;
  for (let tries = 0; tries < N * 3 && n < N; tries++) {
    const a = Math.random() * Math.PI * 2, r = Math.sqrt(Math.random()) * 125;
    const x = Math.cos(a) * r + 5, z = Math.sin(a) * r;
    const h = heightAt(x, z);
    if (h < 0.5 || h > 12) continue;
    if (Math.abs(x - CABIN.x) < 6 && Math.abs(z - CABIN.z) < 5) continue;
    v.set(x, h - 0.05, z);
    q.setFromAxisAngle(up, Math.random() * Math.PI);
    const sc = rand(0.7, 1.3);
    s.set(sc, sc * rand(0.7, 1.3), sc);
    m.compose(v, q, s);
    grass.setMatrixAt(n, m);
    grass.setColorAt(n, GEN ? col.setScalar(rand(0.8, 1.05)) : col.setHSL(rand(0.24, 0.34), 0.55, rand(0.55, 0.8)));
    n++;
  }
  grass.count = n;
  grass.frustumCulled = false;
  scene.add(grass);
}

// ======================= 花 =======================
{
  const N = 2600;
  const flowers = new THREE.InstancedMesh(new THREE.IcosahedronGeometry(0.11, 0), new THREE.MeshLambertMaterial({ flatShading: true }), N);
  const m = new THREE.Matrix4(), col = new THREE.Color();
  let n = 0;
  for (let t = 0; t < N * 3 && n < N; t++) {
    const x = rand(-120, 130), z = rand(-120, 120), h = heightAt(x, z);
    if (h < 0.8 || h > 11 || forestNoise(x, z) > 0.1) continue;
    if (fbm(x * 0.05 + 30, z * 0.05, 2) < 0.05) continue; // 成片开
    m.makeTranslation(x, h + rand(0.3, 0.55), z);
    flowers.setMatrixAt(n, m);
    flowers.setColorAt(n, col.set(pick(GEN ? [...R.flora.colors, PAL.accent, "#ffffff"] : ["#ff9ec7", "#ffe17a", "#ffffff", "#c9a8ff", "#8fd3ff", "#ffb38a"])));
    n++;
  }
  flowers.count = n;
  scene.add(flowers);
}

// ======================= 森林 =======================
const treeColliders = [];
if (GEN) {
  // 编织世界：按配方的植物种类、颜色、密度来种
  const N = Math.round(120 + R.flora.density * 520);
  const kit = WG.floraKit(R.flora.type, R.flora.colors, N);
  const dense = R.terrain === "forest" ? -0.15 : 0.08 - R.flora.density * 0.2;
  let n = 0;
  for (let t = 0; t < 9000 && n < N; t++) {
    const x = rand(-150, 150), z = rand(-150, 150), h = heightAt(x, z);
    if (forestNoise(x, z) < dense && Math.random() > 0.03) continue;
    if (h < 1 || h > 20 || Math.hypot(x, z) > 150) continue;
    if (Math.hypot(x - CABIN.x, z - CABIN.z) < 17 || Math.hypot(x - SPAWN.x, z - SPAWN.z) < 12) continue;
    if (treeColliders.some((c) => (c.x - x) ** 2 + (c.z - z) ** 2 < 9) || nearPath(x, z, 4)) continue;
    const r = kit.place(x, h, z, rand(0.8, 1.5));
    treeColliders.push({ x, z, r });
    n++;
  }
  for (const mesh of kit.meshes) { if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true; scene.add(mesh); }
}
if (!GEN) {
  const N = 520;
  const trunks = new THREE.InstancedMesh(new THREE.CylinderGeometry(0.22, 0.34, 2.8, 7), new THREE.MeshLambertMaterial({ color: 0x9a6b4f }), N);
  const blobs = new THREE.InstancedMesh(new THREE.IcosahedronGeometry(1.7, 1), new THREE.MeshLambertMaterial({ flatShading: true }), N);
  const cones = new THREE.InstancedMesh(new THREE.ConeGeometry(1.7, 3.6, 7), new THREE.MeshLambertMaterial({ flatShading: true }), N * 2);
  const m = new THREE.Matrix4(), q = new THREE.Quaternion(), s = new THREE.Vector3(), v = new THREE.Vector3(), col = new THREE.Color(), up = new THREE.Vector3(0, 1, 0);
  let nt = 0, nb = 0, nc = 0;
  const ROUND = ["#8fe39d", "#ffb7d5", "#c9b5ff", "#9fe6d3", "#ffd6a0", "#b5f08a"];
  const PINE = ["#4fae84", "#62c19a", "#7aa8e0"];
  for (let t = 0; t < 6000 && nt < N; t++) {
    const x = rand(-150, 150), z = rand(-150, 150), h = heightAt(x, z);
    if (forestNoise(x, z) < 0.08 && Math.random() > 0.015) continue;
    if (h < 1 || h > 20 || Math.hypot(x, z) > 150) continue;
    if (Math.hypot(x - CABIN.x, z - CABIN.z) < 17 || Math.hypot(x - SPAWN.x, z - SPAWN.z) < 12) continue;
    if (treeColliders.some((c) => (c.x - x) ** 2 + (c.z - z) ** 2 < 9) || nearPath(x, z, 4)) continue;
    const sc = rand(0.8, 1.5);
    q.setFromAxisAngle(up, Math.random() * Math.PI * 2);
    m.compose(v.set(x, h + 1.3 * sc, z), q, s.set(sc, sc, sc));
    trunks.setMatrixAt(nt++, m);
    if (Math.random() < 0.6) {
      m.compose(v.set(x, h + 3.6 * sc, z), q, s.set(sc * rand(0.9, 1.2), sc * rand(0.9, 1.15), sc * rand(0.9, 1.2)));
      blobs.setMatrixAt(nb, m);
      blobs.setColorAt(nb++, col.set(pick(ROUND)));
    } else {
      const c = col.set(pick(PINE)).clone();
      m.compose(v.set(x, h + 3.2 * sc, z), q, s.set(sc, sc, sc));
      cones.setMatrixAt(nc, m); cones.setColorAt(nc++, c);
      m.compose(v.set(x, h + 5.1 * sc, z), q, s.set(sc * 0.72, sc * 0.8, sc * 0.72));
      cones.setMatrixAt(nc, m); cones.setColorAt(nc++, c.offsetHSL(0, 0, 0.06));
    }
    treeColliders.push({ x, z, r: 0.45 * sc });
  }
  trunks.count = nt; blobs.count = nb; cones.count = nc;
  for (const mesh of [trunks, blobs, cones]) { mesh.castShadow = true; mesh.receiveShadow = true; scene.add(mesh); }

  // 湖边的石头
  const rocks = new THREE.InstancedMesh(new THREE.DodecahedronGeometry(0.8, 0), new THREE.MeshLambertMaterial({ color: 0xb9adc9, flatShading: true }), 60);
  let nr = 0;
  for (let t = 0; t < 2000 && nr < 60; t++) {
    const x = rand(-140, 140), z = rand(-140, 140), h = heightAt(x, z);
    const nearLake = Math.abs(lakeDist(x, z) - lakeR(x, z) - 4) < 5;
    if (!(nearLake || Math.random() < 0.02) || h < -0.2) continue;
    const sc = rand(0.5, 1.6);
    m.compose(v.set(x, h + 0.2, z), q.setFromEuler(new THREE.Euler(rand(0, 3), rand(0, 3), rand(0, 3))), s.set(sc, sc * 0.7, sc));
    rocks.setMatrixAt(nr++, m);
  }
  rocks.count = nr;
  rocks.castShadow = true;
  scene.add(rocks);
}

// ======================= 小路（踏脚石） =======================
{
  const curve = PATH;
  const N = 70;
  const stones = new THREE.InstancedMesh(new THREE.CylinderGeometry(0.55, 0.62, 0.16, 9), new THREE.MeshLambertMaterial({ color: 0xe8dcf0 }), N);
  const m = new THREE.Matrix4(), q = new THREE.Quaternion(), s = new THREE.Vector3(), up = new THREE.Vector3(0, 1, 0);
  for (let i = 0; i < N; i++) {
    const p = curve.getPoint(i / (N - 1));
    p.x += rand(-0.5, 0.5); p.z += rand(-0.5, 0.5);
    p.y = heightAt(p.x, p.z) + 0.04;
    m.compose(p, q.setFromAxisAngle(up, rand(0, 3)), s.set(rand(0.8, 1.2), 1, rand(0.8, 1.2)));
    stones.setMatrixAt(i, m);
  }
  stones.receiveShadow = true;
  scene.add(stones);
}

// ======================= 彩色云 & 浮空岛 =======================
const cloudGroup = new THREE.Group();
scene.add(cloudGroup);
{
  const white = new THREE.Color("#ffffff");
  const COLORS = GEN
    ? [PAL.horizon, PAL.sky_mid, PAL.accent, ...R.flora.colors].map((c) => "#" + new THREE.Color(c).lerp(white, 0.45).getHexString())
    : ["#ffc4dd", "#ffd9b3", "#d6c4ff", "#bfe9ff", "#c8f7d4", "#fff1b8", "#ffb8c9"];
  const geo = new THREE.IcosahedronGeometry(1, 1);
  for (let i = 0; i < (R?.terrain === "clouds" ? 50 : 34); i++) {
    const color = new THREE.Color(pick(COLORS));
    const mat = new THREE.MeshLambertMaterial({ color, emissive: color, emissiveIntensity: NIGHT ? 0.12 : 0.35, flatShading: true, fog: false });
    const cloud = new THREE.Group();
    const puffs = 5 + Math.floor(Math.random() * 5);
    for (let k = 0; k < puffs; k++) {
      const puff = new THREE.Mesh(geo, mat);
      const s = rand(5, 10);
      puff.scale.set(s * rand(1, 1.5), s * rand(0.6, 0.9), s);
      puff.position.set(k * rand(5, 7) - puffs * 3, rand(-1.5, 2.5), rand(-4, 4));
      cloud.add(puff);
    }
    const a = Math.random() * Math.PI * 2, r = rand(120, 420);
    cloud.position.set(Math.cos(a) * r, rand(70, 140), Math.sin(a) * r);
    cloud.rotation.y = Math.random() * Math.PI;
    cloud.userData.bob = Math.random() * 10;
    cloudGroup.add(cloud);
  }
}
const islands = [];
{
  const rockMat = new THREE.MeshLambertMaterial({ color: 0xb79fd6, flatShading: true });
  const topMat = new THREE.MeshLambertMaterial({ color: 0x9be39a, flatShading: true });
  for (const [x, y, z, s] of [[-70, 55, 40, 1], [90, 70, -60, 1.4], [-20, 80, -110, 0.9], [120, 48, 60, 0.8]]) {
    const isl = new THREE.Group();
    const rock = new THREE.Mesh(new THREE.ConeGeometry(7, 11, 8), rockMat);
    rock.rotation.x = Math.PI; rock.position.y = -5.5;
    const top = new THREE.Mesh(new THREE.CylinderGeometry(7.3, 7, 1.2, 8), topMat);
    const trunk = new THREE.Mesh(new THREE.CylinderGeometry(0.3, 0.4, 3, 6), new THREE.MeshLambertMaterial({ color: 0x9a6b4f }));
    trunk.position.y = 2;
    const crown = new THREE.Mesh(new THREE.IcosahedronGeometry(2.2, 1), new THREE.MeshLambertMaterial({ color: pick([0xffb7d5, 0xc9b5ff, 0x8fe39d]), flatShading: true }));
    crown.position.y = 4.6;
    isl.add(rock, top, trunk, crown);
    isl.position.set(x, y, z);
    isl.scale.setScalar(s);
    isl.userData.y = y;
    scene.add(isl);
    islands.push(isl);
  }
}

// ======================= 天气粒子（萤火虫 / 星屑 / 花瓣 / 雪 / 雨 / 落叶 / 泡泡） =======================
// float：散在世界里原地飘；fall / rise：在玩家周围一个大盒子里循环下落 / 上升（盒子跟着玩家走）
const WEATHER = GEN ? WG.weatherConfig(R.weather, PAL.accent) : { count: 700, color: "#fff2b0", size: 28, mode: "float", speed: 0, sway: 1.5 };
const WEATHER_MODE = { float: 0, fall: 1, rise: 2 }[WEATHER.mode];
const BOX = 120, BOX_H = 40;
const fireflyMat = new THREE.ShaderMaterial({
  uniforms: {
    uTime: { value: 0 }, uTex: { value: glowTex(WEATHER.color) }, uMode: { value: WEATHER_MODE },
    uSpeed: { value: WEATHER.speed }, uSway: { value: WEATHER.sway }, uSize: { value: WEATHER.size }, uH: { value: BOX_H },
    uTwinkle: { value: R?.weather === "rain" ? 0 : 1 },
  },
  transparent: true, depthWrite: false, blending: R?.weather === "rain" || R?.weather === "leaves" ? THREE.NormalBlending : THREE.AdditiveBlending,
  vertexShader: `uniform float uTime, uMode, uSpeed, uSway, uSize, uH, uTwinkle; attribute float seed; varying float vA;
    void main(){
      vec3 p = position;
      float s = 0.6 + seed * 0.8;
      if (uMode > 0.5) {
        float dir = uMode > 1.5 ? 1.0 : -1.0;
        p.y = mod(p.y + dir * uTime * uSpeed * s, uH);
      }
      p.x += sin(uTime * 0.5 * s + seed * 6.0) * uSway; p.z += cos(uTime * 0.4 * s + seed * 4.0) * uSway;
      if (uMode < 0.5) p.y += sin(uTime * 0.8 + seed * 11.0) * 0.6;
      vA = mix(1.0, 0.5 + 0.5 * sin(uTime * 2.0 + seed * 20.0), uTwinkle);
      vec4 mv = modelViewMatrix * vec4(p, 1.0);
      gl_PointSize = uSize / -mv.z * 10.0;
      gl_Position = projectionMatrix * mv;
    }`,
  fragmentShader: "uniform sampler2D uTex; varying float vA; void main(){ vec4 c = texture2D(uTex, gl_PointCoord); gl_FragColor = vec4(c.rgb, c.a * vA); }",
});
const weatherPoints = (() => {
  const n = WEATHER.count, pos = new Float32Array(n * 3), seed = new Float32Array(n);
  for (let i = 0; i < n; i++) {
    if (WEATHER_MODE === 0) {
      const x = rand(-110, 120), z = rand(-110, 110);
      pos.set([x, Math.max(heightAt(x, z), WATER) + rand(0.6, R?.weather === "stars" ? 14 : 4), z], i * 3);
    } else {
      pos.set([rand(-BOX / 2, BOX / 2), rand(0, BOX_H), rand(-BOX / 2, BOX / 2)], i * 3);
    }
    seed[i] = Math.random();
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.BufferAttribute(pos, 3));
  g.setAttribute("seed", new THREE.BufferAttribute(seed, 1));
  const pts = new THREE.Points(g, fireflyMat);
  pts.frustumCulled = false;
  scene.add(pts);
  return pts;
})();

// ======================= 小木屋 =======================
const boxColliders = [];
const CW = 10, CD = 8, WALL_H = 3.6, T = 0.3, DOOR_W = 1.9, DOOR_H = 2.7;
const FLOOR_Y = CABIN_Y + 0.35;
const inCabin = (x, z) => !GEN && Math.abs(x - CABIN.x) < CW / 2 && Math.abs(z - CABIN.z) < CD / 2;
const cabin = new THREE.Group();
cabin.position.set(CABIN.x, CABIN_Y, CABIN.z);
scene.add(cabin);
let cabinLight, catLamp;
{
  const logTex = canvasTexture(256, 256, (g, w, h) => {
    for (let y = 0; y < h; y += 32) {
      const grd = g.createLinearGradient(0, y, 0, y + 32);
      grd.addColorStop(0, "#d9a06b"); grd.addColorStop(0.5, "#c88a55"); grd.addColorStop(1, "#9c6538");
      g.fillStyle = grd; g.fillRect(0, y, w, 32);
      g.fillStyle = "rgba(90,50,20,.25)";
      for (let k = 0; k < 6; k++) g.fillRect(Math.random() * w, y + 8 + Math.random() * 16, rand(20, 60), 1.5);
    }
  });
  logTex.wrapS = logTex.wrapT = THREE.RepeatWrapping;
  logTex.repeat.set(2, 1.2);
  const plankTex = canvasTexture(256, 256, (g, w, h) => {
    for (let x = 0; x < w; x += 32) {
      g.fillStyle = pick(["#e8c39a", "#deb68a", "#e3bd92"]); g.fillRect(x, 0, 32, h);
      g.fillStyle = "rgba(120,70,30,.35)"; g.fillRect(x, 0, 2, h);
    }
  });
  plankTex.wrapS = plankTex.wrapT = THREE.RepeatWrapping;
  plankTex.repeat.set(3, 3);

  const wood = new THREE.MeshStandardMaterial({ map: logTex, roughness: 0.9 });
  const woodPlain = new THREE.MeshStandardMaterial({ color: 0xb98154, roughness: 0.85 });
  const floorMat = new THREE.MeshStandardMaterial({ map: plankTex, roughness: 0.8 });
  const roofMat = new THREE.MeshStandardMaterial({ color: 0xe57f93, roughness: 0.75, flatShading: true });
  const glowWin = new THREE.MeshStandardMaterial({ color: 0xffd9a0, emissive: 0xffb866, emissiveIntensity: 1.4 });

  const add = (geo, mat, x, y, z, collide = false) => {
    const mesh = new THREE.Mesh(geo, mat);
    mesh.position.set(x, y, z);
    mesh.castShadow = mesh.receiveShadow = true;
    cabin.add(mesh);
    if (collide) {
      geo.computeBoundingBox();
      const b = geo.boundingBox;
      boxColliders.push({
        minX: CABIN.x + x + b.min.x, maxX: CABIN.x + x + b.max.x, minZ: CABIN.z + z + b.min.z, maxZ: CABIN.z + z + b.max.z,
        minY: CABIN_Y + y + b.min.y, maxY: CABIN_Y + y + b.max.y,
      });
    }
    return mesh;
  };
  const wy = 0.35 + WALL_H / 2;
  add(new THREE.BoxGeometry(CW + 0.6, 0.35, CD + 0.6), floorMat, 0, 0.175, 0);
  add(new THREE.BoxGeometry(2.4, 0.18, 1.2), woodPlain, 0, 0.09, CD / 2 + 0.9); // 门口台阶
  add(new THREE.BoxGeometry(CW, WALL_H, T), wood, 0, wy, -CD / 2, true);
  add(new THREE.BoxGeometry(T, WALL_H, CD), wood, -CW / 2, wy, 0, true);
  add(new THREE.BoxGeometry(T, WALL_H, CD), wood, CW / 2, wy, 0, true);
  const side = (CW - DOOR_W) / 2;
  add(new THREE.BoxGeometry(side, WALL_H, T), wood, -(DOOR_W / 2 + side / 2), wy, CD / 2, true);
  add(new THREE.BoxGeometry(side, WALL_H, T), wood, DOOR_W / 2 + side / 2, wy, CD / 2, true);
  add(new THREE.BoxGeometry(DOOR_W, WALL_H - DOOR_H, T), wood, 0, 0.35 + DOOR_H + (WALL_H - DOOR_H) / 2, CD / 2, true);
  // 打开的门
  const doorPanel = new THREE.Mesh(new THREE.BoxGeometry(DOOR_W, DOOR_H, 0.12), new THREE.MeshStandardMaterial({ color: 0xf08f8f, roughness: 0.7 }));
  doorPanel.geometry.translate(DOOR_W / 2, 0, 0);
  doorPanel.position.set(-DOOR_W / 2, 0.35 + DOOR_H / 2, CD / 2 + 0.1);
  doorPanel.rotation.y = -1.9;
  doorPanel.castShadow = true;
  cabin.add(doorPanel);
  // 窗户（暖光）
  for (const [x, z, ry] of [[-CW / 2 - 0.17, -1, Math.PI / 2], [CW / 2 + 0.17, -1, Math.PI / 2], [-2.6, -CD / 2 - 0.17, 0], [2.6, -CD / 2 - 0.17, 0],
    [-CW / 2 + 0.17, -1, Math.PI / 2], [CW / 2 - 0.17, -1, Math.PI / 2], [-2.6, -CD / 2 + 0.17, 0], [2.6, -CD / 2 + 0.17, 0], [-3.2, CD / 2 + 0.17, 0], [3.2, CD / 2 + 0.17, 0]]) {
    const win = new THREE.Mesh(new THREE.PlaneGeometry(1.4, 1.2), glowWin);
    win.position.set(x, 2.2, z);
    win.rotation.y = ry;
    win.material.side = THREE.DoubleSide;
    cabin.add(win);
  }
  // 屋顶
  const yt = 0.35 + WALL_H, rise = 2.5, half = CD / 2 + 0.9;
  const slabLen = Math.hypot(half, rise + 0.25), ang = Math.atan2(rise + 0.25, half);
  for (const sgn of [1, -1]) {
    const slab = add(new THREE.BoxGeometry(CW + 1.4, 0.28, slabLen), roofMat, 0, yt + rise - (rise + 0.25) / 2, sgn * half / 2);
    slab.rotation.x = sgn * ang;
  }
  const tri = new THREE.Shape([new THREE.Vector2(-CD / 2, 0), new THREE.Vector2(CD / 2, 0), new THREE.Vector2(0, rise)]);
  for (const sgn of [1, -1]) {
    const gable = new THREE.Mesh(new THREE.ShapeGeometry(tri), new THREE.MeshStandardMaterial({ map: logTex, side: THREE.DoubleSide }));
    gable.rotation.y = Math.PI / 2;
    gable.position.set(sgn * CW / 2, yt, 0);
    cabin.add(gable);
  }
  add(new THREE.BoxGeometry(0.9, 2.4, 0.9), new THREE.MeshStandardMaterial({ color: 0xc9a3d9 }), 2.8, yt + 2, -1.7);

  // 屋内
  const furn = (geo, color, x, y, z, extra = {}, collide = false) => add(geo, new THREE.MeshStandardMaterial({ color, roughness: 0.8, ...extra }), x, y, z, collide);
  furn(new THREE.CylinderGeometry(2.4, 2.4, 0.03, 40), 0xffc2d4, 0, 0.37, 0.4);
  furn(new THREE.BoxGeometry(2.2, 0.5, 3.4), 0xb98154, -3.6, 0.6, -2.1, {}, true);
  furn(new THREE.BoxGeometry(2, 0.3, 3.2), 0xfffaf2, -3.6, 0.95, -2.1);
  furn(new THREE.BoxGeometry(2.05, 0.12, 2), 0xffb3c7, -3.6, 1.12, -1.4);
  furn(new THREE.BoxGeometry(1.2, 0.3, 0.7), 0xffffff, -3.6, 1.2, -3.2);
  furn(new THREE.CylinderGeometry(0.7, 0.7, 0.08, 24), 0xd9a06b, 3.4, 1.05, -2.4);
  furn(new THREE.CylinderGeometry(0.1, 0.14, 1, 8), 0xb98154, 3.4, 0.85, -2.4);
  furn(new THREE.BoxGeometry(1.2, 0.6, 1.2), 0xb98154, 3.4, 0.6, -2.4, { transparent: true, opacity: 0 }, true); // 桌子的碰撞体
  furn(new THREE.CylinderGeometry(0.12, 0.12, 0.3, 12), 0xfff1c9, 3.4, 1.25, -2.4, { emissive: 0xffc46b, emissiveIntensity: 2 });
  furn(new THREE.BoxGeometry(0.5, 2.6, 1.8), 0x9c6538, 4.5, 1.65, 1.2, {}, true);
  for (let i = 0; i < 9; i++) {
    furn(new THREE.BoxGeometry(0.35, rand(0.35, 0.5), 0.14), new THREE.Color().setHSL(Math.random(), 0.6, 0.72).getHex(), 4.35, 1.3 + Math.floor(i / 3) * 0.75, 0.6 + (i % 3) * 0.45);
  }
  furn(new THREE.CylinderGeometry(0.35, 0.28, 0.6, 12), 0xf0a07a, -4.2, 0.65, 3.1);
  furn(new THREE.IcosahedronGeometry(0.6, 1), 0x7fd28f, -4.2, 1.35, 3.1, { flatShading: true });
  // 噜噜的坐垫
  furn(new THREE.CylinderGeometry(1.05, 1.15, 0.32, 28), 0xff9fb1, 0, 0.52, -2.3);
  // 屋顶下的小串灯
  for (let i = 0; i < 12; i++) {
    const x = -4.4 + i * 0.8;
    furn(new THREE.SphereGeometry(0.07, 8, 6), pick([0xffe08a, 0xffb3c7, 0xc9b5ff]), x, 3.5 - Math.sin(i / 11 * Math.PI) * 0.35, -3.7, { emissive: 0xffd08a, emissiveIntensity: 2 });
  }
  cabinLight = new THREE.PointLight(0xffc98a, 12, 16, 2);
  cabinLight.position.set(0, 3.2, 0);
  cabin.add(cabinLight);
  catLamp = new THREE.PointLight(0xffb59a, 3, 6, 2);
  catLamp.position.set(3.4, 1.6, -2.4);
  cabin.add(catLamp);
  // 门口的灯笼
  for (const x of [-1.5, 1.5]) {
    furn(new THREE.BoxGeometry(0.3, 0.42, 0.3), 0xfff1c9, x, 3.0, CD / 2 + 0.35, { emissive: 0xffb866, emissiveIntensity: 2.2 });
  }
  const porch = new THREE.PointLight(0xffc27a, 12, 10, 2);
  porch.position.set(0, 3, CD / 2 + 1);
  cabin.add(porch);
  // 门牌
  const signTex = canvasTexture(256, 96, (g) => {
    g.fillStyle = "#f6e1c3"; g.fillRect(0, 0, 256, 96);
    g.strokeStyle = "#b98154"; g.lineWidth = 8; g.strokeRect(4, 4, 248, 88);
    g.fillStyle = "#7a4a2c"; g.font = "bold 42px 'LXGW WenKai Screen','Microsoft YaHei'"; g.textAlign = "center"; g.textBaseline = "middle";
    g.fillText("噜噜的家", 128, 50);
  });
  const sign = new THREE.Mesh(new THREE.PlaneGeometry(1.6, 0.6), new THREE.MeshStandardMaterial({ map: signTex }));
  sign.position.set(0, 0.35 + DOOR_H + 0.42, CD / 2 + 0.17);
  cabin.add(sign);
}

// 烟囱的烟
const smoke = [];
{
  const tex = glowTex("#ffffff");
  for (let i = 0; i < 14; i++) {
    const s = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, transparent: true, opacity: 0, depthWrite: false, color: pick([0xffe4f0, 0xf0e6ff, 0xffffff]) }));
    s.userData.t = i / 14;
    cabin.add(s);
    smoke.push(s);
  }
}

// ======================= 3D 噜噜 =======================
const Cat = (() => {
  const gradient = new THREE.DataTexture(new Uint8Array([110, 190, 255]), 3, 1, THREE.RedFormat);
  gradient.minFilter = gradient.magFilter = THREE.NearestFilter;
  gradient.needsUpdate = true;
  const toon = (color) => new THREE.MeshToonMaterial({ color, gradientMap: gradient });
  const fur = toon(0xf7dcc0), white = toon(0xfff3e6), pink = toon(0xff9fb0), stripe = toon(0xe99a5c), dark = toon(0x2a1d2b);
  const shine = new THREE.MeshBasicMaterial({ color: 0xffffff });

  const root = new THREE.Group();
  const bodyG = new THREE.Group();
  root.add(bodyG);
  const mesh = (geo, mat, parent, x = 0, y = 0, z = 0) => {
    const m = new THREE.Mesh(geo, mat);
    m.position.set(x, y, z);
    m.castShadow = true;
    parent.add(m);
    return m;
  };
  const body = mesh(new THREE.SphereGeometry(0.58, 32, 24), fur, bodyG, 0, 0.52, 0);
  body.scale.set(1.18, 0.92, 1.05);
  mesh(new THREE.SphereGeometry(0.36, 24, 16), white, bodyG, 0, 0.46, 0.4).scale.set(1, 1, 0.55);
  for (const x of [-0.25, 0.25]) mesh(new THREE.SphereGeometry(0.16, 16, 12), fur, bodyG, x, 0.1, 0.52).scale.set(1.1, 0.7, 1.25);

  const head = new THREE.Group();
  head.position.set(0, 1.18, 0.06);
  bodyG.add(head);
  mesh(new THREE.SphereGeometry(0.52, 32, 24), fur, head).scale.set(1.2, 1, 1.05);
  const ears = [];
  for (const sx of [-1, 1]) {
    const ear = new THREE.Group();
    ear.position.set(0.32 * sx, 0.36, 0);
    ear.rotation.z = -0.38 * sx;
    head.add(ear);
    mesh(new THREE.ConeGeometry(0.17, 0.34, 16), fur, ear, 0, 0.12, 0);
    mesh(new THREE.ConeGeometry(0.1, 0.22, 12), pink, ear, 0, 0.1, 0.06);
    ears.push(ear);
  }
  [[-0.09, 0.4, 0.33], [0, 0.43, 0.3], [0.09, 0.4, 0.33]].forEach(([x, y, z]) => {
    const st = mesh(new THREE.BoxGeometry(0.045, 0.15, 0.03), stripe, head, x, y, z);
    st.rotation.x = -0.75;
  });
  const eyes = [];
  for (const sx of [-1, 1]) {
    const eye = new THREE.Group();
    eye.position.set(0.21 * sx, 0.02, 0.45);
    head.add(eye);
    mesh(new THREE.SphereGeometry(0.11, 20, 16), dark, eye).scale.set(1, 1.22, 0.55);
    mesh(new THREE.SphereGeometry(0.038, 10, 8), shine, eye, 0.035, 0.055, 0.055);
    mesh(new THREE.SphereGeometry(0.016, 8, 6), shine, eye, -0.035, -0.045, 0.055);
    eyes.push(eye);
  }
  mesh(new THREE.SphereGeometry(0.045, 12, 8), pink, head, 0, -0.1, 0.52).scale.set(1.3, 0.8, 1);
  for (const sx of [-1, 1]) {
    const arc = mesh(new THREE.TorusGeometry(0.038, 0.009, 6, 14, Math.PI), dark, head, 0.038 * sx, -0.15, 0.5);
    arc.rotation.z = Math.PI;
  }
  const blushMat = new THREE.MeshBasicMaterial({ color: 0xff9fb0, transparent: true, opacity: 0.5, depthWrite: false });
  for (const sx of [-1, 1]) {
    const b = new THREE.Mesh(new THREE.CircleGeometry(0.1, 20), blushMat);
    b.position.set(0.34 * sx, -0.1, 0.4);
    b.rotation.y = 0.65 * sx;
    head.add(b);
  }
  const whiskerMat = new THREE.LineBasicMaterial({ color: 0xc9a68a });
  for (const sx of [-1, 1]) for (const dy of [-0.05, -0.12]) {
    const g = new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(0.28 * sx, dy, 0.42), new THREE.Vector3(0.62 * sx, dy + 0.03, 0.36)]);
    head.add(new THREE.Line(g, whiskerMat));
  }
  const tail = new THREE.Group();
  tail.position.set(0.1, 0.3, -0.55);
  bodyG.add(tail);
  const tailCurve = new THREE.CatmullRomCurve3([
    new THREE.Vector3(0, 0, 0), new THREE.Vector3(0.35, 0.05, -0.25), new THREE.Vector3(0.6, 0.35, -0.3), new THREE.Vector3(0.55, 0.75, -0.18),
  ]);
  mesh(new THREE.TubeGeometry(tailCurve, 24, 0.1, 10), fur, tail);
  mesh(new THREE.SphereGeometry(0.1, 12, 10), stripe, tail, 0.55, 0.75, -0.18);

  // 3D 资产角色：有模型就把程序画的小猫藏起来，用模型做整身动作（呼吸、蹦跳、歪头、低头、转身看你）
  const pivot = new THREE.Group();
  root.add(pivot);
  const headAnchor = new THREE.Group(); // 装扮挂在头顶附近
  headAnchor.position.y = CHAR_H - 0.45;
  pivot.add(headAnchor);
  if (CHAR_MODEL) {
    bodyG.visible = false;
    pivot.add(CHAR_MODEL);
  }

  // 名牌
  const nameTag = new THREE.Sprite(new THREE.SpriteMaterial({ transparent: true, depthWrite: false }));
  nameTag.position.set(0, 2.25, 0);
  nameTag.scale.set(1.3, 0.36, 1);
  root.add(nameTag);
  function setName(name) {
    nameTag.material.map = canvasTexture(256, 72, (g) => {
      g.fillStyle = "rgba(255,248,240,.88)";
      g.beginPath(); g.roundRect(8, 8, 240, 56, 28); g.fill();
      g.fillStyle = "#e07a8b"; g.font = "bold 34px 'LXGW WenKai Screen','Microsoft YaHei'"; g.textAlign = "center"; g.textBaseline = "middle";
      g.fillText(`♡ ${name}`, 128, 38);
    });
    nameTag.material.needsUpdate = true;
  }
  setName(CHARACTER.name);

  // 爱心等小特效
  const fxTex = {};
  const symbolTex = (ch, color) => fxTex[ch] ||= canvasTexture(64, 64, (g) => {
    g.fillStyle = color; g.font = "bold 48px sans-serif"; g.textAlign = "center"; g.textBaseline = "middle"; g.fillText(ch, 32, 36);
  });
  const particles = [];
  function burst(ch, color, n = 3) {
    for (let i = 0; i < n; i++) {
      const s = new THREE.Sprite(new THREE.SpriteMaterial({ map: symbolTex(ch, color), transparent: true, depthWrite: false }));
      s.position.set(rand(-0.5, 0.5), 1.6 + rand(0, 0.3), rand(0, 0.3));
      s.scale.setScalar(0.35);
      s.userData = { life: 0, delay: i * 0.3, vx: rand(-0.2, 0.2) };
      root.add(s);
      particles.push(s);
    }
  }

  let emotion = "calm", emoT = 0, blinkAt = 2, talking = false, lookYaw = 0, walking = false;
  const FX = { happy: ["♥", "#ff6f8a"], shy: ["♡", "#ff8fa8"], sad: ["💧", "#7fc3ff"], worried: ["💧", "#7fc3ff"], surprised: ["!", "#ff9a3c"],
    playful: ["♪", "#a78bfa"], sleepy: ["z", "#8aa0ff"], missing: ["♡", "#ff8fa8"], angry: ["💢", "#ff5a5a"] };
  function setEmotion(e) {
    emotion = e || "calm";
    emoT = 0;
    if (FX[emotion]) burst(...FX[emotion], emotion === "happy" ? 4 : 2);
  }

  function update(dt, t, playerWorld) {
    emoT += dt;
    // 呼吸、尾巴
    body.scale.y = 0.92 * (1 + Math.sin(t * 2.2) * 0.025);
    const wag = emotion === "happy" || emotion === "playful" ? 4.5 : 2;
    tail.rotation.y = Math.sin(t * wag) * 0.4;
    tail.rotation.z = Math.sin(t * wag * 0.5) * 0.15;
    // 看向玩家
    const local = root.worldToLocal(playerWorld.clone());
    const targetYaw = clamp(Math.atan2(local.x, local.z), -0.9, 0.9);
    const near = local.length() < 9;
    lookYaw = lerp(lookYaw, near ? targetYaw : Math.sin(t * 0.4) * 0.3, 1 - Math.exp(-dt * 3));
    head.rotation.y = lookYaw;
    // 情绪姿态
    let tilt = 0, nod = 0, earRot = 0, eyeScale = 1, bounce = 0, blush = 0.5;
    switch (emotion) {
      case "happy": bounce = emoT < 2 ? Math.abs(Math.sin(emoT * 8)) * 0.12 : 0; blush = 0.7; eyeScale = 0.55; break;
      case "shy": tilt = 0.18; nod = 0.12; blush = 0.95; eyeScale = 0.35; earRot = 0.25; break;
      case "sad": nod = 0.28; earRot = 0.55; eyeScale = 0.9; blush = 0.25; break;
      case "worried": nod = 0.1; earRot = 0.35; break;
      case "surprised": eyeScale = 1.3; earRot = -0.15; bounce = emoT < 0.5 ? Math.sin(emoT * 6) * 0.15 : 0; break;
      case "playful": tilt = Math.sin(t * 2.5) * 0.15; blush = 0.6; break;
      case "sleepy": nod = 0.18 + Math.sin(t) * 0.05; eyeScale = 0.12; earRot = 0.3; tilt = Math.sin(t * 0.7) * 0.08; break;
      case "missing": nod = -0.08; blush = 0.7; eyeScale = 1.15; break;
      case "angry": earRot = 0.8; eyeScale = 0.6; break;
    }
    if (talking) nod += Math.sin(t * 9) * 0.04;
    if (walking) bounce = Math.abs(Math.sin(t * 9)) * 0.14;
    if (CHAR_MODEL) {
      // 模型没有骨骼，用整身动作表达情绪
      const breathe = 1 + Math.sin(t * 2.2) * 0.018 - (walking ? Math.abs(Math.sin(t * 9)) * 0.03 : 0);
      pivot.scale.set(1 / Math.sqrt(breathe), breathe, 1 / Math.sqrt(breathe));
      pivot.position.y = bounce;
      pivot.rotation.y = lerp(pivot.rotation.y, lookYaw * 0.7, 0.15);
      pivot.rotation.z = lerp(pivot.rotation.z, tilt * 0.6 + (walking ? Math.sin(t * 9) * 0.06 : 0), 0.15);
      pivot.rotation.x = lerp(pivot.rotation.x, nod * 0.45, 0.1);
    }
    head.rotation.z = lerp(head.rotation.z, tilt, 0.1);
    head.rotation.x = lerp(head.rotation.x, nod, 0.1);
    ears.forEach((e, i) => { e.rotation.z = lerp(e.rotation.z, -(0.38 + earRot) * (i ? 1 : -1), 0.15); });
    bodyG.position.y = bounce;
    blushMat.opacity = lerp(blushMat.opacity, blush, 0.08);
    // 眨眼
    let blink = 1;
    if (t > blinkAt) { blink = 0.1; if (t > blinkAt + 0.15) blinkAt = t + rand(2.5, 5); }
    eyes.forEach((e) => (e.scale.y = lerp(e.scale.y, eyeScale * blink, 0.4)));
    // 特效
    for (let i = particles.length - 1; i >= 0; i--) {
      const p = particles[i], u = p.userData;
      u.life += dt;
      const k = u.life - u.delay;
      if (k < 0) { p.material.opacity = 0; continue; }
      p.position.y += dt * 0.5;
      p.position.x += u.vx * dt;
      p.material.opacity = k < 0.2 ? k * 5 : Math.max(0, 1 - (k - 0.2) / 1.6);
      if (k > 1.8) { root.remove(p); particles.splice(i, 1); }
    }
  }
  return {
    root, head: CHAR_MODEL ? headAnchor : head, body: CHAR_MODEL ? pivot : bodyG, update, setEmotion, setName,
    set talking(v) { talking = v; }, set walking(v) { walking = v; },
  };
})();
Cat.root.position.set(0, 0.68, -2.3);
Cat.root.scale.setScalar(1.25);
cabin.add(Cat.root);
const catWorld = new THREE.Vector3();
const catHeadWorld = () => Cat.root.localToWorld(new THREE.Vector3(0, 2.2, 0));
cabin.updateMatrixWorld(true);
Cat.root.getWorldPosition(catWorld);

// ======================= 编织世界：地标、噜噜的装扮、收集物 =======================
const landmarks = [];   // { group, x, z }
const items = [];       // { group, x, y, z, found }

// 可达地图：2 米一格，从出生点出发能走到的格子（不进深水、不爬太陡的坡）。地标和收集物只放在能走到的地方。
const GRID = 2, GN = 210, G0 = -210;
const reach = new Uint8Array(GN * GN);
if (GEN) {
  const hs = new Float32Array(GN * GN);
  for (let i = 0; i < GN; i++) for (let j = 0; j < GN; j++) hs[i * GN + j] = heightAt(G0 + (i + 0.5) * GRID, G0 + (j + 0.5) * GRID);
  const walk = (i, j) => {
    const x = G0 + (i + 0.5) * GRID, z = G0 + (j + 0.5) * GRID;
    return hs[i * GN + j] > WATER - 0.6 && Math.hypot(x, z) < WORLD_R - 4;
  };
  const si = Math.floor((SPAWN.x - G0) / GRID), sj = Math.floor((SPAWN.z - G0) / GRID);
  const queue = [si * GN + sj];
  reach[si * GN + sj] = 1;
  while (queue.length) {
    const c = queue.pop(), i = Math.floor(c / GN), j = c % GN;
    for (const [di, dj] of [[1, 0], [-1, 0], [0, 1], [0, -1]]) {
      const ni = i + di, nj = j + dj;
      if (ni < 0 || nj < 0 || ni >= GN || nj >= GN) continue;
      const nc = ni * GN + nj;
      if (reach[nc] || !walk(ni, nj) || Math.abs(hs[nc] - hs[c]) > 2.5) continue;
      reach[nc] = 1;
      queue.push(nc);
    }
  }
}
const cellOf = (x, z) => {
  const i = Math.floor((x - G0) / GRID), j = Math.floor((z - G0) / GRID);
  return i >= 0 && j >= 0 && i < GN && j < GN ? i * GN + j : -1;
};
const reachable = (x, z) => { const c = cellOf(x, z); return c >= 0 && reach[c] === 1; };
const cellCenter = (c) => new THREE.Vector3(G0 + (Math.floor(c / GN) + 0.5) * GRID, 0, G0 + ((c % GN) + 0.5) * GRID);

// 被树、地标挡住的格子（噜噜带路时绕开它们）
const blocked = new Uint8Array(GN * GN);
function markBlocked() {
  for (const t of treeColliders) {
    const r = t.r + 0.8;
    for (let x = t.x - r; x <= t.x + r; x += GRID / 2) for (let z = t.z - r; z <= t.z + r; z += GRID / 2) {
      if (Math.hypot(x - t.x, z - t.z) > r) continue;
      const c = cellOf(x, z);
      if (c >= 0) blocked[c] = 1;
    }
  }
}
const passable = (c) => reach[c] === 1 && !blocked[c];

// 在格子地图上找一条能走的路（8 方向 BFS），返回一串路点
function gridPath(from, to) {
  const s = cellOf(from.x, from.z), g = cellOf(to.x, to.z);
  if (s < 0 || g < 0) return null;
  const prev = new Int32Array(GN * GN).fill(-1);
  prev[s] = s;
  const queue = [s];
  let head = 0, found = -1;
  while (head < queue.length) {
    const c = queue[head++];
    if (c === g) { found = c; break; }
    const i = Math.floor(c / GN), j = c % GN;
    for (let di = -1; di <= 1; di++) for (let dj = -1; dj <= 1; dj++) {
      if (!di && !dj) continue;
      const ni = i + di, nj = j + dj;
      if (ni < 0 || nj < 0 || ni >= GN || nj >= GN) continue;
      const nc = ni * GN + nj;
      if (prev[nc] !== -1 || (!passable(nc) && nc !== g)) continue;
      if (di && dj && (!passable(i * GN + nj) || !passable(ni * GN + j))) continue; // 斜着走不能穿过两个障碍的缝
      prev[nc] = c;
      queue.push(nc);
    }
  }
  if (found < 0) return null;
  const cells = [];
  for (let c = found; c !== s; c = prev[c]) cells.push(c);
  cells.reverse();
  const pts = cells.filter((_, k) => k % 2 === 1 || k === cells.length - 1).map(cellCenter);
  if (pts.length) pts[pts.length - 1].set(to.x, 0, to.z);
  return pts;
}
const isLand = (x, z) => {
  const h = heightAt(x, z);
  return h > 0.8 && h < 14 && Math.hypot(x, z) < 135 && (!GEN || (reachable(x, z) && !blocked[cellOf(x, z)]));
};
function findSpot(minGap, taken) {
  for (let t = 0; t < 400; t++) {
    let x, z;
    if (SEA) {
      // 海上世界：从小路旁边找能走过去的小岛
      const p = pick(PATH_PTS), a = rand(0, Math.PI * 2), d = rand(5, 20);
      x = p.x + Math.cos(a) * d; z = p.z + Math.sin(a) * d;
      let ok = true;
      for (let k = 1; k <= 6 && ok; k++) ok = heightAt(lerp(p.x, x, k / 6), lerp(p.z, z, k / 6)) > 0.3;
      if (!ok) continue;
    } else {
      const a = rand(0, Math.PI * 2), d = Math.sqrt(Math.random()) * 115;
      x = Math.cos(a) * d + 5; z = Math.sin(a) * d;
    }
    if (!isLand(x, z)) continue;
    if (Math.hypot(x - SPAWN.x, z - SPAWN.z) < 10) continue;
    if (taken.some((s) => Math.hypot(s.x - x, s.z - z) < minGap)) continue;
    return { x, z };
  }
  return null;
}
if (GEN) {
  // 编织世界里没有小木屋：第一个地标放在“家”的位置，噜噜在它前面等你
  cabin.visible = false;
  boxColliders.length = 0;
  const taken = [{ x: CABIN.x, z: CABIN.z }];
  R.landmarks.forEach((lm, i) => {
    const spot = i === 0 ? { x: CABIN.x, z: CABIN.z } : findSpot(30, taken);
    if (!spot) return;
    if (i) taken.push(spot);
    const built = WG.buildLandmark(lm.type, PAL.accent);
    built.group.position.set(spot.x, heightAt(spot.x, spot.z) - 0.1, spot.z);
    built.group.rotation.y = Math.atan2(SPAWN.x - spot.x, SPAWN.z - spot.z);
    const label = WG.textSprite(lm.label);
    label.position.y = built.top + 1.6;
    built.group.add(label);
    scene.add(built.group);
    treeColliders.push({ x: spot.x, z: spot.z, r: built.radius });
    landmarks.push({ group: built.group, x: spot.x, z: spot.z, info: lm });
  });
  // 噜噜：换上这个世界的装扮，站在第一个地标前
  scene.add(Cat.root);
  const front = new THREE.Vector3(SPAWN.x - CABIN.x, 0, SPAWN.z - CABIN.z).normalize();
  const homeR = treeColliders.length ? treeColliders[treeColliders.length - landmarks.length]?.r ?? 3 : 3;
  Cat.root.position.set(CABIN.x + front.x * (homeR + 3), 0, CABIN.z + front.z * (homeR + 3));
  Cat.root.position.y = heightAt(Cat.root.position.x, Cat.root.position.z);
  Cat.root.rotation.y = Math.atan2(front.x, front.z);
  // 3D 资产角色有自己的衣服和包，只加戴在头顶的装扮
  if (!CHAR_MODEL || ["hat", "flower_crown", "bow"].includes(R.cat.outfit)) WG.dressCat(Cat, R.cat.outfit, R.cat.outfit_color);
  catWorld.copy(Cat.root.position);
  markBlocked();
  // 收集物：先在每个地标旁边放一个，剩下的散在世界里
  const itemSpots = [];
  for (const lm of landmarks) {
    if (itemSpots.length >= R.quest.count) break;
    for (let t = 0; t < 60; t++) {
      const a = rand(0, Math.PI * 2), x = lm.x + Math.cos(a) * rand(6, 10), z = lm.z + Math.sin(a) * rand(6, 10);
      if (isLand(x, z)) { itemSpots.push({ x, z }); break; }
    }
  }
  while (itemSpots.length < R.quest.count) {
    const s = findSpot(22, [...taken, ...itemSpots]);
    if (!s) break;
    itemSpots.push(s);
  }
  const pillarMat = new THREE.MeshBasicMaterial({ color: PAL.accent, transparent: true, opacity: 0.22, depthWrite: false, blending: THREE.AdditiveBlending });
  for (const s of itemSpots) {
    const g = new THREE.Group();
    const item = WG.buildItem(R.quest.item_shape, PAL.accent);
    item.position.y = 1.4;
    g.add(item);
    const halo = new THREE.Sprite(new THREE.SpriteMaterial({ map: glowTex(PAL.accent), transparent: true, depthWrite: false, blending: THREE.AdditiveBlending }));
    halo.scale.setScalar(3);
    halo.position.y = 1.4;
    g.add(halo);
    const pillar = new THREE.Mesh(new THREE.CylinderGeometry(0.25, 0.25, 30, 8, 1, true), pillarMat); // 远远就能看到的光柱
    pillar.position.y = 15;
    g.add(pillar);
    const y = heightAt(s.x, s.z);
    g.position.set(s.x, y, s.z);
    scene.add(g);
    items.push({ group: g, item, x: s.x, y, z: s.z, found: false });
  }
}

// ======================= 玩家（第一人称） =======================
const EYE = 1.65, RADIUS = 0.35;
const player = {
  pos: new THREE.Vector3(SPAWN.x, heightAt(SPAWN.x, SPAWN.z), SPAWN.z), vel: new THREE.Vector3(),
  yaw: Math.atan2(-(CABIN.x - SPAWN.x), -(CABIN.z - SPAWN.z)), pitch: -0.05, onGround: true,
};
const keys = {};
let locked = false, chatting = false, started = false;

function groundAt(x, z) {
  let g = heightAt(x, z);
  if (inCabin(x, z) || (Math.abs(x - CABIN.x) < 1.2 && z - CABIN.z > CD / 2 - 0.2 && z - CABIN.z < CD / 2 + 1.5)) g = Math.max(g, FLOOR_Y);
  return g;
}

function collide(p) {
  for (const b of boxColliders) {
    if (b.minY > p.y + 1.9 || b.maxY < p.y + 0.2) continue;
    const cx = clamp(p.x, b.minX, b.maxX), cz = clamp(p.z, b.minZ, b.maxZ);
    const dx = p.x - cx, dz = p.z - cz, d2 = dx * dx + dz * dz;
    if (d2 >= RADIUS * RADIUS) continue;
    if (d2 > 1e-9) {
      const d = Math.sqrt(d2);
      p.x = cx + (dx / d) * RADIUS; p.z = cz + (dz / d) * RADIUS;
    } else {
      const pushes = [[b.minX - RADIUS - p.x, 0], [b.maxX + RADIUS - p.x, 0], [0, b.minZ - RADIUS - p.z], [0, b.maxZ + RADIUS - p.z]];
      pushes.sort((a, c) => Math.abs(a[0] + a[1]) - Math.abs(c[0] + c[1]));
      p.x += pushes[0][0]; p.z += pushes[0][1];
    }
  }
  for (const c of treeColliders) {
    const dx = p.x - c.x, dz = p.z - c.z, r = c.r + RADIUS, d2 = dx * dx + dz * dz;
    if (d2 < r * r && d2 > 1e-9) { const d = Math.sqrt(d2); p.x = c.x + (dx / d) * r; p.z = c.z + (dz / d) * r; }
  }
  if (!(GEN && Q.active)) { // 噜噜本身（冒险中她跟在身边，就不挡路了）
    const dx = p.x - catWorld.x, dz = p.z - catWorld.z, r = 1.25 + RADIUS, d2 = dx * dx + dz * dz;
    if (d2 < r * r && d2 > 1e-9) { const d = Math.sqrt(d2); p.x = catWorld.x + (dx / d) * r; p.z = catWorld.z + (dz / d) * r; }
  }
  const r = Math.hypot(p.x, p.z);
  if (r > WORLD_R) { p.x *= WORLD_R / r; p.z *= WORLD_R / r; }
}

let waterWarned = 0;
function movePlayer(dt) {
  const f = (keys.KeyW ? 1 : 0) - (keys.KeyS ? 1 : 0), s = (keys.KeyD ? 1 : 0) - (keys.KeyA ? 1 : 0);
  const speed = keys.ShiftLeft || keys.ShiftRight ? 11 : 5.5;
  const fx = -Math.sin(player.yaw), fz = -Math.cos(player.yaw), rx = Math.cos(player.yaw), rz = -Math.sin(player.yaw);
  let wx = fx * f + rx * s, wz = fz * f + rz * s;
  const len = Math.hypot(wx, wz) || 1;
  wx = (wx / len) * speed * (f || s ? 1 : 0); wz = (wz / len) * speed * (f || s ? 1 : 0);
  const k = 1 - Math.exp(-dt * 10);
  player.vel.x = lerp(player.vel.x, wx, k);
  player.vel.z = lerp(player.vel.z, wz, k);

  const next = player.pos.clone();
  next.x += player.vel.x * dt; next.z += player.vel.z * dt;
  if (heightAt(next.x, next.z) < WATER - 0.7 && !inCabin(next.x, next.z)) {
    next.x = player.pos.x; next.z = player.pos.z;
    if (performance.now() - waterWarned > 4000) { waterWarned = performance.now(); showHint("湖水太深啦，绕过去吧～", 2000); }
  }
  collide(next);
  // 台阶：可以直接迈上不高的地方
  const g = groundAt(next.x, next.z);
  if (g - player.pos.y > 0.7 && player.onGround) { next.x = player.pos.x; next.z = player.pos.z; }
  player.pos.x = next.x; player.pos.z = next.z;

  player.vel.y -= 24 * dt;
  if (keys.Space && player.onGround) { player.vel.y = 7.5; player.onGround = false; }
  player.pos.y += player.vel.y * dt;
  const ground = groundAt(player.pos.x, player.pos.z);
  if (player.pos.y <= ground || (player.onGround && player.pos.y - ground < 0.4 && player.vel.y <= 0)) {
    player.pos.y = ground; player.vel.y = 0; player.onGround = true;
  } else player.onGround = false;
}

let bobT = 0;
function updateCamera(dt) {
  const moving = Math.hypot(player.vel.x, player.vel.z);
  bobT += dt * moving * 1.6;
  const bob = player.onGround ? Math.sin(bobT) * 0.05 * Math.min(1, moving / 5) : 0;
  camera.position.set(player.pos.x, player.pos.y + EYE + bob, player.pos.z);
  camera.rotation.set(player.pitch, player.yaw, 0);
}

// ======================= 输入 =======================
// 两种操作模式：
// - 锁定模式：鼠标被锁在画面里，直接移动鼠标转视角（普通浏览器）
// - 拖拽模式：浏览器不允许锁鼠标时（内嵌窗口等），按住左键拖动转视角，方向键也能转
let freeMode = false, paused = true, dragging = false;
const J = { state: "none", t: 0 };   // 旅程状态：none（在星球上自由走）/ walkout / beamCat / beamPlayer / ascend / space
const canLook = () => started && !paused && !chatting && (locked || freeMode);
const canControl = () => canLook() && J.state === "none";

// 按键状态：只有收到 keyup 才算松开。如果松手时焦点不在页面上（点了页面外、切窗口、内嵌浏览器丢焦点），
// keyup 会丢失，角色就会一直往一个方向走。所以在各种“可能丢 keyup”的时刻都把按键全部清掉。
const codeOfKey = {};
function releaseAll() {
  for (const k in keys) keys[k] = false;
  dragging = false;
}
addEventListener("keydown", (e) => {
  if (chatting) { if (e.code === "Escape") closeChat(); return; }
  if (e.code === "Escape" && freeMode && !paused) { pause("已暂停"); return; }
  keys[e.code] = true;
  if (e.key) codeOfKey[e.key.toLowerCase()] = e.code;
  if (["Space", "ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight"].includes(e.code)) e.preventDefault();
  if (e.code === "KeyE" && canLook() && (nearCat() || J.state === "space")) openChat();
  if (e.code === "KeyF" && chapter === "voyage" && canControl() && nearCat()) startJourney(true);
  if (e.code === "KeyH" && canLook() && J.state === "space") goHome();
  if (e.code === "KeyV" && canLook() && J.state === "space") { J.cockpit = !J.cockpit; player.yaw = 0; player.pitch = 0; }
});
// 用捕获阶段监听，任何元素都拦不住；同时按 code 和 key 两种方式清除（输入法下 code 偶尔对不上）
addEventListener("keyup", (e) => {
  keys[e.code] = false;
  const c = e.key && codeOfKey[e.key.toLowerCase()];
  if (c) keys[c] = false;
  if (e.key === "Shift") keys.ShiftLeft = keys.ShiftRight = false;
}, true);
addEventListener("blur", releaseAll);
document.addEventListener("visibilitychange", releaseAll);
document.addEventListener("mouseleave", () => { dragging = false; });
function look(dx, dy) {
  player.yaw -= dx * 0.0022;
  player.pitch = clamp(player.pitch - dy * 0.0022, -1.45, 1.45);
}
addEventListener("mousemove", (e) => {
  if ((locked && canLook()) || (freeMode && dragging && canLook())) look(e.movementX, e.movementY);
});
canvas.addEventListener("pointerdown", (e) => {
  if (freeMode && e.button === 0) { dragging = true; canvas.style.cursor = "grabbing"; }
  // 锁定模式下鼠标被释放了（比如关掉对话框后），点一下画面重新锁上
  else if (!freeMode && !locked && started && !paused && !chatting) lock();
});
addEventListener("pointerup", () => { dragging = false; canvas.style.cursor = freeMode ? "grab" : ""; });
document.addEventListener("pointerlockchange", () => {
  const was = locked;
  locked = document.pointerLockElement === canvas;
  if (locked) resume();
  else if (was && !chatting && started) pause("已暂停");
  Object.keys(keys).forEach((k) => (keys[k] = false));
});
function enterFreeMode() {
  if (!freeMode) showHint("这个窗口不能锁定鼠标（在 Chrome / Edge 里打开就可以）：现在先按住左键拖动转视角", 7000);
  freeMode = true;
  canvas.style.cursor = "grab";
  resume();
}
function resume() {
  paused = false;
  $("startScreen").hidden = true;
  $("hud").hidden = false;
  canvas.focus();
}
function lock() {
  if (freeMode) { resume(); return; }
  // 同一次点击里：先锁鼠标（光标隐藏并固定在画面中央，移动鼠标就转头），再进全屏。
  // unadjustedMovement 关掉系统鼠标加速，转头更跟手；不支持的浏览器退回普通锁定。
  try {
    const p = canvas.requestPointerLock({ unadjustedMovement: true });
    if (p && p.catch) p.catch(() => {
      try {
        const p2 = canvas.requestPointerLock();
        if (p2 && p2.catch) p2.catch(enterFreeMode);
      } catch { enterFreeMode(); }
    });
  } catch { enterFreeMode(); }
  if (!document.fullscreenElement && document.documentElement.requestFullscreen) {
    document.documentElement.requestFullscreen({ navigationUI: "hide" }).catch(() => {});
  }
  // 有的环境既不报错也不锁定，稍等一下还没锁上就用拖拽模式
  setTimeout(() => { if (!locked && !chatting && paused) enterFreeMode(); }, 600);
}
document.addEventListener("pointerlockerror", () => { if (!chatting) enterFreeMode(); });
// ======================= 章节 =======================
// 第一章「小木屋」：星球上散步、去小木屋找噜噜（没有 UFO）
// 第二章「星际旅行」：从小木屋出发，噜噜带你坐 UFO 去太空
let chapter = "cabin", chapterApplied = null;
async function loadChapters() {
  let list = [{ id: "cabin", title: "第一章 · 小木屋", desc: "", unlocked: true }];
  try { list = await fetch("/api/chapters").then((r) => r.json()); } catch {}
  const want = BOOT.chapterId;
  chapter = list.some((c) => c.id === want && c.unlocked) ? want : "cabin";
  const box = $("chapters");
  box.innerHTML = "";
  for (const c of list) {
    const b = document.createElement("button");
    b.className = "chapter" + (c.id === chapter ? " on" : "");
    b.disabled = !c.unlocked;
    b.innerHTML = `<b>${c.unlocked ? "" : "🔒 "}${c.title}</b><span>${c.unlocked ? c.desc : c.unlock_hint}</span>`;
    b.addEventListener("click", () => {
      chapter = c.id;
      box.querySelectorAll(".chapter").forEach((el) => el.classList.toggle("on", el === b));
      $("enterBtn").textContent = chapterApplied && chapterApplied !== chapter ? "进入这一章" : started ? "继续" : "进入星球";
    });
    box.appendChild(b);
  }
  // 第二章已解锁的话，在开始界面就把太空准备好（约 0.6 秒），点“进入”时不用再等
  if (!GEN && list.some((c) => c.id === "voyage" && c.unlocked)) {
    $("enterBtn").textContent = "正在准备星际旅行…";
    await new Promise((r) => setTimeout(r, 30));
    prepareSpace();
  }
  $("enterBtn").disabled = false;
  $("enterBtn").textContent = GEN ? `进入「${R.title}」` : "进入星球";
}
function applyChapter(id) {
  // 编织的世界和梦幻星球是两套不同的场景；中途换章节，或者选的章节不是当前搭好的场景，就带着选择重新加载
  const kind = (c) => (/^w\d+$/.test(c) ? c : "planet");
  if ((chapterApplied && chapterApplied !== id) || kind(id) !== kind(BOOT.chapterId)) {
    try { localStorage.setItem("chapter", id); } catch {}
    location.href = `/world?chapter=${id}`;
    return false;
  }
  if (chapterApplied === id) return true;
  chapterApplied = id;
  try { localStorage.setItem("chapter", id); } catch {}
  UFO.group.visible = id === "voyage";
  if (GEN) { startGenWorld(); return true; }
  if (id === "voyage") {
    prepareSpace();
    // 从小木屋里、噜噜面前开始
    player.pos.set(CABIN.x + 0.6, FLOOR_Y, CABIN.z + 0.8);
    player.yaw = Math.atan2(-(catWorld.x - player.pos.x), -(catWorld.z - player.pos.z));
    player.pitch = -0.12;
    visited = true;
    setTimeout(() => {
      caption("第二章 · 星际旅行", 3500);
      stream("/api/event", { note: "今天你悄悄在小木屋门口准备了一架小 UFO，想带对方飞出星球去看星星。神秘又期待地邀请对方跟你出门。" });
    }, 600);
  }
  return true;
}
$("enterBtn").addEventListener("click", () => {
  if (!applyChapter(chapter)) return;
  started = true;
  lock();
});
function pause(sub) {
  paused = true;
  releaseAll();
  showStart(sub);
}
function showStart(sub) {
  $("startSub").textContent = sub || "噜噜在湖边的小木屋里等你";
  $("enterBtn").textContent = started ? "继续" : "进入星球";
  $("startScreen").hidden = false;
}

// ======================= HUD =======================
let hintTimer;
function showHint(text, ms) {
  const el = $("hint");
  el.textContent = text;
  el.hidden = false;
  clearTimeout(hintTimer);
  if (ms) hintTimer = setTimeout(() => (el.hidden = true), ms);
}
const nearCat = () => player.pos.distanceTo(catWorld) < 3.6;

function compassTarget() {
  // 星球上指向小木屋；编织世界里：先指向噜噜，冒险中指向最近的收集物
  if (!GEN) return { x: CABIN.x, z: CABIN.z, label: (d) => (inCabin(player.pos.x, player.pos.z) ? "在噜噜家里" : `噜噜的家 · ${d} 米`) };
  if (!Q.met || Q.done) return Q.done ? null : { x: catWorld.x, z: catWorld.z, label: (d) => `去找噜噜 · ${d} 米` };
  let best = null, bd = Infinity;
  for (const it of items) {
    if (it.found) continue;
    const d = Math.hypot(it.x - player.pos.x, it.z - player.pos.z);
    if (d < bd) { bd = d; best = it; }
  }
  return best && { x: best.x, z: best.z, label: (d) => `最近的${R.quest.item} · ${d} 米` };
}
function updateHud() {
  // 指南针
  const tgt = compassTarget();
  $("compass").hidden = J.state !== "none" || !tgt;
  if (tgt) {
    const dx = tgt.x - player.pos.x, dz = tgt.z - player.pos.z, dist = Math.hypot(dx, dz);
    let rel = Math.atan2(-dx, -dz) - player.yaw;
    rel = Math.atan2(Math.sin(rel), Math.cos(rel));
    $("compassArrow").style.transform = `rotate(${-90 - (rel * 180) / Math.PI}deg)`;
    $("compassText").textContent = tgt.label(Math.round(dist));
  }
  const NEAR_HINT = chapter === "voyage" ? "E 和噜噜说话 · F 跟噜噜出门坐 UFO" : "按 E 和噜噜说话";
  if (!chatting && J.state === "none") {
    if (nearCat()) showHint(NEAR_HINT);
    else if ($("hint").textContent === NEAR_HINT) $("hint").hidden = true;
  }
  // 头顶气泡
  const bubble = $("bubble");
  if (!bubble.hidden) {
    const head = catHeadWorld(), p = head.clone().project(camera);
    const far = head.distanceTo(camera.position) > 22;
    const offscreen = p.z > 1 || Math.abs(p.x) > 0.95 || Math.abs(p.y) > 0.95;
    // 噜噜离得远或者不在画面里时，气泡停靠在屏幕下方（像她在耳边说话）
    bubble.classList.toggle("docked", far || offscreen);
    bubble.style.visibility = "visible";
    if (far || offscreen) { bubble.style.left = ""; bubble.style.top = ""; }
    else {
      bubble.style.left = `${((p.x + 1) / 2) * innerWidth}px`;
      bubble.style.top = `${Math.max(bubble.offsetHeight + 64, ((1 - p.y) / 2) * innerHeight - 10)}px`;
    }
  }
}

// ======================= 和噜噜说话 =======================
let busy = false, bubbleTimer, visited = false;
const LEAD = /^\s*[\[【]\s*([A-Za-z]+)[\s,，:：]*([\d.]+)?\s*[\]】]\s*/;
const visibleText = (raw) => (/^\s*[\[【][^\]】]*$/.test(raw) ? "" : raw.replace(LEAD, "").replace(/<state>[\s\S]*$/, "").trim());

function say(text, keep) {
  const b = $("bubble");
  b.textContent = text;
  b.hidden = !text;
  clearTimeout(bubbleTimer);
  if (text && !keep) bubbleTimer = setTimeout(() => (b.hidden = true), Math.max(12000, text.length * 400));
}
function logLine(role, text) {
  const el = document.createElement("div");
  el.className = `m ${role}`;
  el.textContent = text;
  $("chatLog").appendChild(el);
  $("chatLog").scrollTop = 1e9;
  return el;
}
const SCENES = {
  none: "你们此刻在梦幻星球上你的小木屋里面对面，对方就坐在你的坐垫旁边。",
  space: "你们正一起坐在你的小 UFO 里，在外太空飞行，窗外是星星、彩色星云和各种奇妙的星球。",
};
const sceneNote = () => {
  if (GEN) {
    const lms = R.landmarks.map((l) => l.label).join("、");
    return `你们此刻在你用对方的生活和梦编织的世界「${R.title}」里冒险（${R.inspiration}）。这里有${lms}。` +
      `${R.cat.role ? `你在这里的身份是${R.cat.role}。` : ""}这次的冒险：${R.quest.goal}，已经找到 ${Q.found}/${R.quest.count} 个「${R.quest.item}」。`;
  }
  return SCENES[J.state] || SCENES.none;
};

// 边说边播：服务器每合成好一句就发 audio 事件，排队一句接一句播
const worldAudioQ = [];
let worldQPlaying = false;
function worldEnqueue(url) {
  worldAudioQ.push(url);
  if (!worldQPlaying) worldPlayNext();
}
function worldPlayNext() {
  const url = worldAudioQ.shift();
  if (!url) { worldQPlaying = false; Cat.talking = false; return; }
  worldQPlaying = true;
  const a = new Audio(url);
  bodyWorldAudio = a;
  a.onplay = () => { Cat.talking = true; };
  a.onended = a.onerror = () => { if (bodyWorldAudio === a) worldPlayNext(); };
  a.play().catch(() => { if (bodyWorldAudio === a) worldPlayNext(); });
}

async function stream(url, body) {
  if (busy || window.BodyClient?.busy) return;
  busy = true;
  Cat.talking = true;
  say("…", true);
  let raw = "", result = null, gotLead = false;
  // 开着朗读、且声音不是交给玩偶播时，让服务器边生成边合成
  const wantTts = getVoiceOn() && !window.BodyClient?.routesAudio;
  if (wantTts) {
    if (body) body = { ...body, tts: true };
    else url += (url.includes("?") ? "&" : "?") + "tts=1";
  }
  const showFinal = () => {
    say(result.text);
    if (!gotLead) Cat.setEmotion(result.emotion);
    logLine("assistant", result.text);
    if (!wantTts) speak(result.text);
  };
  try {
    const res = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: body ? JSON.stringify(body) : null });
    if (res.status === 204) { say(""); return; }
    if (!res.ok) throw new Error(res.statusText);
    const reader = res.body.getReader(), dec = new TextDecoder();
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
          const lead = !gotLead && LEAD.exec(raw);
          if (lead) { gotLead = true; Cat.setEmotion(lead[1].toLowerCase()); }
          const vis = visibleText(raw);
          if (vis) say(vis, true);
        } else if (ev === "done") { result = data; showFinal(); }   // 文字一写完就定稿
        else if (ev === "audio") worldEnqueue(data.url);
        else if (ev === "error") throw new Error(data.message);
      }
    }
  } catch (e) {
    say(`（${e.message}）`);
  } finally {
    busy = false;
    Cat.talking = false;
    setTimeout(pumpEvents, 1500); // 排队等着说的话，稍停一下再说
  }
}

// 朗读开关和聊天页共用同一个设置
const getVoiceOn = () => { try { return JSON.parse(localStorage.getItem("voiceOn") || "false"); } catch { return false; } };
const syncVoiceBtn = () => ($("voiceBtn").textContent = getVoiceOn() ? "🔊" : "🔇");
syncVoiceBtn();
$("voiceBtn").addEventListener("click", () => {
  try { localStorage.setItem("voiceOn", JSON.stringify(!getVoiceOn())); } catch {}
  syncVoiceBtn();
});

// 语音输入：录成 16kHz WAV 交给后台识别（本地 SenseVoice 还能听出语气）
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
    const len = chunks.reduce((n, p) => n + p.length, 0), all = new Float32Array(len);
    let o = 0;
    for (const p of chunks) { all.set(p, o); o += p.length; }
    const to = 16000, ratio = rate / to, outLen = Math.floor(len / ratio), pcm = new Int16Array(outLen);
    for (let i = 0; i < outLen; i++) { const s = clamp(all[Math.floor(i * ratio)], -1, 1); pcm[i] = s < 0 ? s * 0x8000 : s * 0x7fff; }
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
let recording = false;
$("micBtn").addEventListener("click", async () => {
  if (busy) return;
  const btn = $("micBtn");
  if (!recording) {
    try { await Recorder.start(); recording = true; btn.classList.add("recording"); say("（在听你说…）", true); }
    catch (e) { say(`（没能打开麦克风：${e.message}）`); }
    return;
  }
  recording = false;
  btn.classList.remove("recording");
  const { blob, seconds } = Recorder.stop();
  if (seconds < 0.5) { say("（说得太短啦）"); return; }
  say("（在听清你说的话…）", true);
  try {
    const fd = new FormData();
    fd.append("file", blob, "speech.wav");
    const res = await fetch("/api/asr", { method: "POST", body: fd });
    if (!res.ok) throw new Error((await res.json()).detail || res.statusText);
    const heard = await res.json();
    if (!heard.text) { say("（没听清，再说一次好吗？）"); return; }
    const el = logLine("user", heard.text);
    const bits = [heard.emotion && heard.emotion !== "平静" ? `听起来${heard.emotion}` : "", heard.event].filter(Boolean);
    const tag = document.createElement("span");
    tag.className = "heard";
    tag.textContent = `🎙 语音${bits.length ? " · " + bits.join(" · ") : ""}`;
    el.appendChild(tag);
    sendToCat(heard.text, { voice_emotion: heard.emotion || "", voice_event: heard.event || "" });
  } catch (e) {
    say(`（语音识别不可用：${e.message}）`);
  }
});

let bodyWorldSpeechGeneration = 0, bodyWorldAudio = null;
function stopWorldSpeaking() {
  bodyWorldSpeechGeneration += 1;
  worldAudioQ.length = 0;
  worldQPlaying = false;
  if (bodyWorldAudio) { bodyWorldAudio.pause(); bodyWorldAudio = null; }
  if (window.speechSynthesis) speechSynthesis.cancel();
  Cat.talking = false;
}

async function speak(text) {
  if (window.BodyClient?.routesAudio) return;
  if (!getVoiceOn()) return;
  stopWorldSpeaking();
  const speechGeneration = bodyWorldSpeechGeneration;
  const speechCancelled = () => speechGeneration !== bodyWorldSpeechGeneration || window.BodyClient?.routesAudio;
  text = text.replace(/[（(][^）)]*[）)]/g, "").replace(/[\p{Extended_Pictographic}]/gu, "").trim();
  try {
    const res = await fetch("/api/tts", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text }) });
    if (speechCancelled()) return;
    if (!res.ok) throw new Error();
    const blob = await res.blob();
    if (speechCancelled()) return;
    const url = URL.createObjectURL(blob);
    const audio = new Audio(url);
    bodyWorldAudio = audio;
    Cat.talking = true;
    audio.onplay = () => { if (speechCancelled()) audio.pause(); };
    audio.onended = audio.onpause = () => {
      Cat.talking = false; URL.revokeObjectURL(url);
      if (bodyWorldAudio === audio) bodyWorldAudio = null;
    };
    await audio.play();
  } catch {
    // 只用选定的声音（晓伊）：这句合成不了就不出声，不换成浏览器自带的声音
    Cat.talking = false;
  }
}

function openChat() {
  chatting = true;
  releaseAll();
  $("chat").hidden = false;
  $("hint").hidden = true;
  document.exitPointerLock();
  setTimeout(() => $("chatInput").focus(), 50);
}
function closeChat() {
  chatting = false;
  releaseAll();
  $("chat").hidden = true;
  if (freeMode) { resume(); return; }
  lock();
  // 用 Esc 关闭时浏览器可能不允许立刻锁鼠标，就显示“继续”让玩家点一下
  setTimeout(() => { if (!locked && !freeMode) pause("点一下继续"); }, 300);
}
$("chatClose").addEventListener("click", closeChat);
$("chatForm").addEventListener("submit", (e) => {
  e.preventDefault();
  const text = $("chatInput").value.trim();
  if (!text || busy) return;
  $("chatInput").value = "";
  logLine("user", text);
  sendToCat(text);
});

// 说“带我出门 / 坐 UFO / 去太空”之类的话，噜噜回完话就会带你出门
const GO_OUT = /出门|出去玩|出去走|带我.{0,4}(走|去|飞|出)|ufo|飞船|太空|宇宙|看星星|兜风/i;
async function sendToCat(text, extra = {}) {
  const wantsOut = chapter === "voyage" && J.state === "none" && GO_OUT.test(text);
  await stream("/api/chat", { text, scene: sceneNote() + (wantsOut ? " 门口停着你的小 UFO，你会马上带对方出门坐 UFO 飞去外太空。" : ""), ...extra });
  if (wantsOut && J.state === "none") {
    // 不调用 closeChat（它会去锁鼠标，而这里不是用户点击触发的，浏览器会拒绝）
    chatting = false;
    $("chat").hidden = true;
    releaseAll();
    resume();
    startJourney(false);
  }
}

// ======================= UFO =======================
const UFO_HOME = new THREE.Vector3(CABIN.x, 0, CABIN.z + 15);
UFO_HOME.y = heightAt(UFO_HOME.x, UFO_HOME.z) + 4.6;
const UFO = (() => {
  const g = new THREE.Group();
  const hull = new THREE.MeshStandardMaterial({ color: 0xd4c8ff, metalness: 0.55, roughness: 0.22 });
  const body = new THREE.Mesh(new THREE.SphereGeometry(6, 56, 20), hull);
  body.scale.set(1, 0.26, 1);
  body.castShadow = true;
  g.add(body);
  const rim = new THREE.Mesh(new THREE.TorusGeometry(6, 0.38, 12, 72), new THREE.MeshStandardMaterial({ color: 0xff9fc8, emissive: 0xff7fb6, emissiveIntensity: 0.6, metalness: 0.4, roughness: 0.3 }));
  rim.rotation.x = Math.PI / 2;
  g.add(rim);
  const bottom = new THREE.Mesh(new THREE.CylinderGeometry(2.4, 3.4, 0.6, 36), new THREE.MeshStandardMaterial({ color: 0xa8f4ff, emissive: 0x6fe8ff, emissiveIntensity: 1.6 }));
  bottom.position.y = -1.45;
  g.add(bottom);
  const lights = [];
  for (let i = 0; i < 16; i++) {
    const a = (i / 16) * Math.PI * 2;
    const m = new THREE.Mesh(new THREE.SphereGeometry(0.3, 12, 8), new THREE.MeshBasicMaterial({ color: new THREE.Color().setHSL(i / 16, 0.85, 0.7) }));
    m.position.set(Math.cos(a) * 5.3, 0.4, Math.sin(a) * 5.3);
    g.add(m);
    lights.push(m);
  }
  const floor = new THREE.Mesh(new THREE.CylinderGeometry(3.25, 3.25, 0.2, 40), new THREE.MeshStandardMaterial({ color: 0xffe9f4 }));
  floor.position.y = 1.2;
  g.add(floor);
  const seat = new THREE.Mesh(new THREE.CylinderGeometry(1.0, 1.1, 0.35, 28), new THREE.MeshStandardMaterial({ color: 0xff9fb1 }));
  seat.position.set(-1.1, 1.45, 0);
  g.add(seat);
  const dome = new THREE.Mesh(new THREE.SphereGeometry(3.4, 44, 20, 0, Math.PI * 2, 0, Math.PI / 2), new THREE.MeshPhysicalMaterial({
    color: 0xc8f4ff, transparent: true, opacity: 0.22, roughness: 0.05, side: THREE.DoubleSide, depthWrite: false,
  }));
  dome.position.y = 1.25;
  g.add(dome);
  const beam = new THREE.Mesh(new THREE.ConeGeometry(4.6, 1, 48, 1, true).translate(0, -0.5, 0), new THREE.MeshBasicMaterial({
    color: 0x9ff3ff, transparent: true, opacity: 0.32, side: THREE.DoubleSide, depthWrite: false, blending: THREE.AdditiveBlending,
  }));
  beam.position.y = -1.6;
  beam.visible = false;
  g.add(beam);
  const glowLight = new THREE.PointLight(0x9ff3ff, 25, 30, 2);
  glowLight.position.y = -2.5;
  g.add(glowLight);
  g.position.copy(UFO_HOME);
  scene.add(g);
  return { group: g, lights, beam, seatPos: new THREE.Vector3(-1.1, 1.65, 0), eyePos: new THREE.Vector3(1.4, 3.0, 0.6) };
})();

// ======================= 旅程：出门 → 坐 UFO → 飞出星球 → 深空 =======================
let space = null, activeScene = scene;
const skyU = sky.material.uniforms;
const SKY_DAY = Object.fromEntries(Object.entries(skyU).map(([k, v]) => [k, v.value.clone()]));
const SKY_SPACE = { top: new THREE.Color("#05030f"), mid: new THREE.Color("#120a2e"), horizon: new THREE.Color("#2a1548"), bottom: new THREE.Color("#3a1d4f") };
const FOG_DAY = FOG.clone(), FOG_SPACE = new THREE.Color("#1a0f33");
const starMat = skyGroup.children.find((c) => c.isPoints).material;
const tmpV = new THREE.Vector3(), tmpV2 = new THREE.Vector3();
let catPath = null;

function caption(text, ms = 3500) {
  const el = $("caption");
  el.textContent = text;
  el.hidden = !text;
  clearTimeout(caption.t);
  if (text && ms) caption.t = setTimeout(() => (el.hidden = true), ms);
}
function flash(then) {
  const el = $("flash");
  el.classList.add("on");
  setTimeout(() => { then(); el.classList.remove("on"); }, 650);
}
function setSkyMix(k) {
  for (const key of Object.keys(skyU)) skyU[key].value.copy(SKY_DAY[key]).lerp(SKY_SPACE[key], k);
  scene.fog.color.copy(FOG_DAY).lerp(FOG_SPACE, k);
  scene.background = scene.fog.color;
  starMat.opacity = 0.65 + k * 0.35;
}

// 太空场景很重（6 张星球贴图要逐像素生成，第一次渲染还要编译着色器、上传贴图），
// 放在开始界面还没进入游戏时就准备好，游戏中就不会卡一下。
function prepareSpace() {
  if (space) return;
  const t0 = performance.now();
  space = createSpace();
  // UFO 和噜噜在太空的灯光下要用另一套着色器，也临时放进去一起预编译，再放回原处
  const catSaved = { parent: Cat.root.parent, p: Cat.root.position.clone(), r: Cat.root.rotation.clone(), s: Cat.root.scale.clone() };
  space.scene.add(UFO.group);
  UFO.group.add(Cat.root);
  const camSaved = { p: camera.position.clone(), q: camera.quaternion.clone(), far: camera.far };
  camera.far = 40000;
  camera.updateProjectionMatrix();
  camera.position.set(0, 400, 900);
  camera.lookAt(0, 0, 0);
  renderer.compile(space.scene, camera);
  renderer.render(space.scene, camera); // 顺便把所有贴图传到显卡
  catSaved.parent.add(Cat.root);
  Cat.root.position.copy(catSaved.p); Cat.root.rotation.copy(catSaved.r); Cat.root.scale.copy(catSaved.s);
  scene.add(UFO.group);
  camera.position.copy(camSaved.p); camera.quaternion.copy(camSaved.q); camera.far = camSaved.far;
  camera.updateProjectionMatrix();
  perf.prepareSpaceMs = Math.round(performance.now() - t0);
}

function startJourney(withLine) {
  if (J.state !== "none") return;
  J.state = "walkout"; J.t = 0; J.said = {};
  releaseAll();
  $("hint").hidden = true;
  caption("噜噜带你出门啦～", 3000);
  prepareSpace();
  if (withLine) stream("/api/event", { note: "对方想跟你一起出去玩。你开心地从坐垫上跳下来，带着对方走出小木屋——门口停着你的小 UFO，你要载对方飞去外太空看星星。" });
  // 噜噜从坐垫走到门口，再走到 UFO 下面
  scene.attach(Cat.root);
  const start = Cat.root.position.clone();
  const doorZ = CABIN.z + CD / 2;
  catPath = new THREE.CatmullRomCurve3([
    start, new THREE.Vector3(CABIN.x, FLOOR_Y, CABIN.z + 1.2), new THREE.Vector3(CABIN.x, FLOOR_Y, doorZ + 0.6),
    new THREE.Vector3(CABIN.x, groundAt(CABIN.x, doorZ + 3), doorZ + 3),
    new THREE.Vector3(UFO_HOME.x, heightAt(UFO_HOME.x, UFO_HOME.z - 1.5), UFO_HOME.z - 1.5),
  ]);
  Cat.walking = true;
  Cat.setEmotion("happy");
}

function updateJourney(dt, t) {
  J.t += dt;
  const ufo = UFO.group;
  if (J.state === "walkout") {
    // 噜噜在前面一蹦一跳地走，你倒退着跟在她前面看着她（像被她牵着出门）
    const u = Math.min(1, J.t / 8), e = u * u * (3 - 2 * u);
    const p = catPath.getPointAt(e), ahead = catPath.getPointAt(Math.min(1, e + 0.02));
    Cat.root.position.copy(p);
    const dir = tmpV.subVectors(ahead, p).setY(0);
    if (dir.lengthSq() > 1e-6) Cat.root.rotation.y = Math.atan2(dir.x, dir.z);
    dir.normalize();
    const target = tmpV2.copy(p).addScaledVector(dir, 3.2);
    player.pos.x = lerp(player.pos.x, target.x, 1 - Math.exp(-dt * 2.5));
    player.pos.z = lerp(player.pos.z, target.z, 1 - Math.exp(-dt * 2.5));
    player.pos.y = groundAt(player.pos.x, player.pos.z);
    lookAtPoint(catHeadWorld(), dt, 4);
    updateCamera(dt);
    if (u >= 1) { J.state = "beamCat"; J.t = 0; Cat.walking = false; UFO.beam.visible = true; caption("UFO 的光把噜噜接上去了～", 2500); }
  } else if (J.state === "beamCat") {
    // 光束把噜噜吸上去，放到座位上
    const u = Math.min(1, J.t / 2.5), e = u * u * (3 - 2 * u);
    const from = catPath.getPointAt(1), to = ufo.localToWorld(UFO.seatPos.clone());
    Cat.root.position.lerpVectors(from, to, e);
    Cat.root.rotation.y += dt * 2;
    UFO.beam.scale.y = ufo.position.y - heightAt(ufo.position.x, ufo.position.z) - 1.6;
    lookAtPoint(catHeadWorld(), dt, 4);
    updateCamera(dt);
    if (u >= 1) {
      ufo.attach(Cat.root);
      Cat.root.position.copy(UFO.seatPos);
      Cat.root.rotation.set(0, 0, 0);
      Cat.root.scale.setScalar(1);
      J.state = "beamPlayer"; J.t = 0;
      J.camFrom = camera.position.clone();
      caption("轮到你啦，抓稳～", 2500);
    }
  } else if (J.state === "beamPlayer") {
    // 你也被吸上去，坐进透明的圆顶舱里
    const u = Math.min(1, J.t / 3), e = u * u * (3 - 2 * u);
    camera.position.lerpVectors(J.camFrom, ufo.localToWorld(UFO.eyePos.clone()), e);
    lookAtPoint(catHeadWorld(), dt, 3, true);
    if (u >= 1) {
      UFO.beam.visible = false;
      J.state = "ascend"; J.t = 0;
      J.base = ufo.position.y;
      caption("UFO 起飞！", 2500);
      stream("/api/event", { note: "你和对方都坐进了 UFO 的透明圆顶舱，UFO 正在起飞，草原、湖和你的小木屋在脚下越变越小。" });
    }
  } else if (J.state === "ascend") {
    // 往上飞：先在舱里，再切到外面看 UFO 越飞越高，草原变小、穿过彩色云、天空变黑
    const T = 13, u = Math.min(1, J.t / T);
    ufo.position.y = J.base + Math.pow(u, 2.2) * 760;
    ufo.rotation.y += dt * (0.3 + u * 1.2);
    const alt = ufo.position.y - J.base;
    setSkyMix(smooth(120, 700, alt));
    const inside = ufo.localToWorld(UFO.eyePos.clone());
    const outside = tmpV.copy(ufo.position).add(new THREE.Vector3(18 + alt * 0.02, -9 - alt * 0.06, 26 + alt * 0.04));
    camera.position.lerpVectors(inside, outside, smooth(1.5, 4, J.t));
    // 一开始从舱里往下看，再慢慢转去看 UFO；全程平滑转头，不会突然跳
    const lookTarget = tmpV2.copy(ufo.position);
    lookTarget.y -= 6 * (1 - smooth(0.8, 3, J.t));
    lookAtPoint(lookTarget, dt, 2.5 + smooth(0, 4, J.t) * 6, true);
    if (J.t > 4 && J.t < 4.1) caption("草原和小木屋越来越小了…", 3000);
    if (J.t > 8 && J.t < 8.1) caption("正在穿过彩色的云和大气层…", 3000);
    if (u >= 1) { J.state = "warping"; flash(enterSpace); }
  } else if (J.state === "space") {
    flySpace(dt, t);
  } else if (J.state === "warping") {
    lookAtPoint(UFO.group.position, dt, 6, true);
  }
  blinkUfo(t);
}
function blinkUfo(t) {
  for (const [i, l] of UFO.lights.entries()) l.material.color.setHSL((i / 16 + t * 0.2) % 1, 0.85, 0.55 + 0.25 * Math.sin(t * 6 + i));
}

// 看向某个点（平滑转头）。direct=true 时直接设置相机朝向（相机不在玩家位置时用）
const lookQ = new THREE.Quaternion(), lookM = new THREE.Matrix4();
function lookAtPoint(target, dt, speed, direct = false) {
  if (direct) {
    lookM.lookAt(camera.position, target, camera.up);
    lookQ.setFromRotationMatrix(lookM);
    camera.quaternion.slerp(lookQ, 1 - Math.exp(-dt * speed));
    return;
  }
  const eye = tmpV.set(player.pos.x, player.pos.y + EYE, player.pos.z);
  const d = target.clone().sub(eye);
  const yaw = Math.atan2(-d.x, -d.z), pitch = Math.atan2(d.y, Math.hypot(d.x, d.z));
  let dy = yaw - player.yaw;
  dy = Math.atan2(Math.sin(dy), Math.cos(dy));
  const k = 1 - Math.exp(-dt * speed);
  player.yaw += dy * k;
  player.pitch = lerp(player.pitch, clamp(pitch, -1.2, 1.2), k);
}

function enterSpace() {
  J.state = "space"; J.t = 0; J.s = 0; J.speed = 30; J.cockpit = false; J.said = {};
  space.scene.add(UFO.group);
  UFO.group.rotation.set(0, 0, 0);
  activeScene = space.scene;
  camera.far = 40000;
  camera.updateProjectionMatrix();
  player.yaw = 0; player.pitch = 0;
  caption("欢迎来到深空 ✦", 3500);
  $("spaceHint").hidden = false;
  stream("/api/event", { note: "UFO 冲出了大气层！回头看，你们的梦幻星球变成了一颗裹着粉色光晕的小星球，眼前是无边的深空、彩色星云和满天星星。" });
}

const routeTan = new THREE.Vector3(), camOffset = new THREE.Vector3(), UP = new THREE.Vector3(0, 1, 0);
function flySpace(dt, t) {
  const ufo = UFO.group;
  J.speed = Math.min(170, J.speed + dt * 20);
  J.s += J.speed * dt;
  if (J.s > space.routeLength) { J.s -= space.routeLength; J.said = {}; }
  const u = J.s / space.routeLength;
  space.route.getPointAt(u, ufo.position);
  ufo.position.y += Math.sin(t * 1.3) * 1.5;
  space.route.getTangentAt(u, routeTan);
  ufo.lookAt(tmpV.copy(ufo.position).add(routeTan));
  ufo.rotateZ(Math.sin(t * 0.7) * 0.06);
  space.update(dt, t, ufo.position);

  if (J.cockpit) {
    // 舱内视角：坐在噜噜旁边往前看
    camera.position.copy(ufo.localToWorld(UFO.eyePos.clone()));
    camera.quaternion.copy(ufo.quaternion).multiply(lookQ.setFromEuler(new THREE.Euler(player.pitch, Math.PI + player.yaw, 0, "YXZ")));
  } else {
    // 外部视角：刚出来的十几秒从前方回头看 UFO 和身后的星球，之后跟在 UFO 后面；鼠标可以绕着转
    const leave = 1 - smooth(9, 16, J.t);
    const back = tmpV.copy(routeTan).multiplyScalar(lerp(-34, 40, leave));
    camOffset.copy(back).add(tmpV2.copy(UP).multiplyScalar(lerp(10, 22, leave)));
    camOffset.applyAxisAngle(UP, player.yaw);
    camOffset.y += player.pitch * -25;
    camera.position.copy(ufo.position).add(camOffset);
    // 刚离开时看向 UFO 和身后星球之间，让两者同框；之后看向 UFO 前方
    const ahead = tmpV.copy(ufo.position).addScaledVector(routeTan, 12);
    const homeView = tmpV2.copy(ufo.position).lerp(space.home.center, 0.3);
    camera.lookAt(ahead.lerp(homeView, leave));
  }

  // 飞近星球时，噜噜会说说她看到了什么
  for (const p of space.planets) {
    if (!p.note || J.said[p.name] || busy) continue;
    if (ufo.position.distanceTo(p.center) < p.radius * 4.2) {
      J.said[p.name] = true;
      caption(`✦ ${p.name}`, 4000);
      stream("/api/event", { note: p.note });
    }
  }
}

function goHome() {
  if (J.state !== "space") return;
  J.state = "warping";
  flash(() => {
    J.state = "none"; J.t = 0;
    scene.add(UFO.group);
    UFO.group.position.copy(UFO_HOME);
    UFO.group.rotation.set(0, 0, 0);
    cabin.attach(Cat.root);
    Cat.root.position.set(0, 0.68, -2.3);
    Cat.root.rotation.set(0, 0, 0);
    Cat.root.scale.setScalar(1.25);
    Cat.walking = false;
    activeScene = scene;
    camera.far = 2500;
    camera.updateProjectionMatrix();
    setSkyMix(0);
    player.pos.set(CABIN.x + 4, 0, CABIN.z + 10);
    player.pos.y = groundAt(player.pos.x, player.pos.z);
    player.vel.set(0, 0, 0);
    player.yaw = Math.atan2(-(CABIN.x - player.pos.x), -(CABIN.z - player.pos.z));
    player.pitch = 0;
    $("spaceHint").hidden = true;
    caption("回到家啦，噜噜已经先跑回屋里了～", 3500);
    stream("/api/event", { note: "你们坐 UFO 从外太空回到了梦幻星球的家门口，你先跑回小木屋的坐垫上了，对方站在门口。" });
  });
}
$("homeBtn").addEventListener("click", () => { if (J.state === "space") goHome(); });

// ======================= 编织世界的冒险 =======================
const Q = { met: false, active: false, found: 0, done: false };
const ITEM_ICON = { star: "⭐", page: "📄", shell: "🐚", heart: "💗", key: "🗝️", feather: "🪶", crystal: "💎", note: "🎵", letter: "✉️", flower: "🌸" };

// 噜噜要说的话排队说：她正在说话时发生的事（比如又捡到一个），等她说完再说
const eventQueue = [];
function catEvent(note) { eventQueue.push(note); pumpEvents(); }
async function pumpEvents() {
  if (busy || !eventQueue.length) return;
  await stream("/api/event", { note: eventQueue.shift() });
}

function startGenWorld() {
  visited = true;
  player.yaw = Math.atan2(-(CABIN.x - player.pos.x), -(CABIN.z - player.pos.z));
  updateQuestHud();
  setTimeout(() => {
    caption(`✦ ${R.title}`, 4500);
    const lm = landmarks[0]?.info.label || "这里";
    catEvent(`对方刚走进你编织的新世界「${R.title}」（灵感来自：${R.inspiration}）。你正在远处的「${lm}」前面等对方` +
      `${R.cat.role ? `，你在这个世界里的身份是${R.cat.role}` : ""}。用这句开场白的意思邀请对方：「${R.intro}」，再让对方顺着小路来${lm}找你。`);
  }, 700);
}

function updateQuestHud() {
  const el = $("quest");
  if (!GEN) { el.hidden = true; return; }
  el.hidden = false;
  el.textContent = Q.done
    ? `✦ 冒险完成 · ${R.quest.item} ${Q.found}/${R.quest.count}`
    : `${ITEM_ICON[R.quest.item_shape] || "✦"} ${R.quest.item} ${Q.found}/${R.quest.count}`;
}

const catTarget = new THREE.Vector3(), catStep = new THREE.Vector3();
function nextItem() {
  let best = null, bd = Infinity;
  for (const it of items) {
    if (it.found) continue;
    const d = Math.hypot(it.x - player.pos.x, it.z - player.pos.z);
    if (d < bd) { bd = d; best = it; }
  }
  return best;
}
let catWaiting = false, guideGoal = null, guidePath = [];
const guideSpot = new THREE.Vector3();
function guideCat(dt) {
  // 冒险中噜噜走在前面带路：朝下一个收集物走，停在它前面一点等你；你落后太多她就停下来回头等你
  const p = Cat.root.position;
  const fx = -Math.sin(player.yaw), fz = -Math.cos(player.yaw);
  const toPlayer = Math.hypot(player.pos.x - p.x, player.pos.z - p.z);
  const goal = Q.done ? null : nextItem();
  let speed = 0;
  if (toPlayer > 45) {
    // 被甩得太远（比如被挡住了），直接出现在你前面
    p.x = player.pos.x + fx * 4; p.z = player.pos.z + fz * 4;
    guideGoal = null; // 位置变了，重新找路
  } else if (goal) {
    // 沿着能走的路，走到收集物旁边（2 米左右）站着等你：你跟着她走过去，就能捡到
    if (goal !== guideGoal) {
      guideGoal = goal;
      // 站到收集物“另一边”（离你最远的那一侧）：你跟着她走，会先经过收集物
      let best = null, bd = -Infinity;
      for (let k = 0; k < 12; k++) {
        const a = (k / 12) * Math.PI * 2, x = goal.x + Math.cos(a) * 2.4, z = goal.z + Math.sin(a) * 2.4, c = cellOf(x, z);
        if (c < 0 || !passable(c)) continue;
        const d = Math.hypot(x - player.pos.x, z - player.pos.z);
        if (d > bd) { bd = d; best = { x, z }; }
      }
      guideSpot.set(best ? best.x : goal.x, 0, best ? best.z : goal.z);
      guidePath = gridPath(p, guideSpot) || [guideSpot.clone()];
    }
    while (guidePath.length > 1 && Math.hypot(guidePath[0].x - p.x, guidePath[0].z - p.z) < 0.9) guidePath.shift();
    catTarget.copy(guidePath[0]);
    if (toPlayer > 11) speed = 0;                                       // 你落后了：停下等你
    else speed = toPlayer < 5 ? 7 : 5.2;                                 // 你跟得近就走快点
  } else {
    // 没有要找的了：站到你面前
    catTarget.set(player.pos.x + fx * 3.2, 0, player.pos.z + fz * 3.2);
    speed = 9;
  }
  const d = Math.hypot(catTarget.x - p.x, catTarget.z - p.z);
  const moving = speed > 0 && d > 0.6;
  if (moving) {
    catStep.set(catTarget.x - p.x, 0, catTarget.z - p.z).normalize().multiplyScalar(Math.min(d, speed * dt));
    p.x += catStep.x; p.z += catStep.z;
    Cat.root.rotation.y = Math.atan2(catStep.x, catStep.z);
  } else {
    // 停着的时候转身看着你
    const want = Math.atan2(player.pos.x - p.x, player.pos.z - p.z);
    let dr = want - Cat.root.rotation.y;
    dr = Math.atan2(Math.sin(dr), Math.cos(dr));
    Cat.root.rotation.y += dr * Math.min(1, dt * 4);
  }
  Cat.walking = moving;
  // 第一次因为你落后而停下来等时，提示一下
  const waitingNow = !!goal && toPlayer > 11;
  if (waitingNow && !catWaiting) showHint("噜噜停下来等你了，跟上她～", 3000);
  catWaiting = waitingNow;
  p.y = Math.max(groundAt(p.x, p.z), WATER);
  catWorld.copy(p);
}

function collect(it) {
  it.found = true;
  Q.found++;
  scene.remove(it.group);
  Cat.setEmotion("happy");
  updateQuestHud();
  const k = Q.found, n = R.quest.count;
  if (k < n) {
    caption(`找到了 ${R.quest.item}（${k}/${n}）`, 2500);
    catEvent(`对方在「${R.title}」里找到了第 ${k} 个「${R.quest.item}」（一共 ${n} 个）。你此刻想说的话大意是：「${R.quest.hints[k - 1]}」，用你自己的口吻自然地说。`);
  } else {
    Q.done = true;
    caption("冒险完成 ✦", 5000);
    catEvent(`对方找齐了全部 ${n} 个「${R.quest.item}」，这次冒险完成了！你想说的结尾大意是：「${R.quest.ending}」，用你自己的口吻温暖地说出来。`);
    fetch(`/api/worlds/${BOOT.worldId}/complete`, { method: "POST" }).catch(() => {});
    updateQuestHud();
  }
}

function updateQuest(dt, t) {
  if (!GEN) return;
  for (const lm of landmarks) WG.animateLandmark(lm.group, t);
  for (const it of items) {
    if (it.found) continue;
    it.item.rotation.y = t * 1.5;
    it.item.position.y = 1.4 + Math.sin(t * 2 + it.x) * 0.2;
  }
  if (!Q.met && Math.hypot(player.pos.x - catWorld.x, player.pos.z - catWorld.z) < 6) {
    Q.met = true;
    Q.active = true;
    caption(`冒险开始：${R.quest.goal}`, 5000);
    setTimeout(() => showHint(`跟着噜噜走，她会带你去找「${R.quest.item}」～`, 5000), 5200);
    catEvent(`对方来到了你身边。用你的话告诉对方这次的冒险：${R.quest.goal}——一共要找 ${R.quest.count} 个「${R.quest.item}」，远处有光柱的地方就是。说你会走在前面带路，让对方跟着你。`);
  }
  if (Q.active) guideCat(dt);
  if (Q.active && !Q.done) {
    for (const it of items) {
      if (it.found || Math.abs(player.pos.y - it.y) > 3) continue;
      const dp = Math.hypot(player.pos.x - it.x, player.pos.z - it.z);
      const catThere = Math.hypot(catWorld.x - it.x, catWorld.z - it.z) < 3.5; // 噜噜已经在旁边等着，就算你站得稍远一点，她也会递给你
      if (dp < 3.2 || (catThere && dp < 4.8)) collect(it);
    }
  }
}

// ======================= 主循环 =======================
const playerHead = new THREE.Vector3();
let hadFocus = document.hasFocus();
// 调试：记录每个阶段最长的一帧（毫秒），用来找卡顿
const perf = (window.__perf = {});
let lastFrame = performance.now();
function tick() {
  const now = performance.now();
  const frameMs = now - lastFrame;
  lastFrame = now;
  const st = J.state;
  perf[st] = perf[st] || { max: 0, frames: 0, over50: 0 };
  perf[st].max = Math.max(perf[st].max, Math.round(frameMs));
  perf[st].frames++;
  if (frameMs > 50) perf[st].over50++;
  const dt = Math.min(clock.getDelta(), 0.05), t = clock.elapsedTime;
  // 内嵌浏览器里点到页面外时不一定触发 blur：每帧看一下焦点，从“有”变成“没有”的那一刻清掉按键
  const focusedNow = document.hasFocus();
  if (hadFocus && !focusedNow) releaseAll();
  hadFocus = focusedNow;
  if (canLook()) {
    // 方向键转视角（两种模式、星球和太空里都能用）
    const turn = (keys.ArrowLeft ? 1 : 0) - (keys.ArrowRight ? 1 : 0), tilt = (keys.ArrowUp ? 1 : 0) - (keys.ArrowDown ? 1 : 0);
    player.yaw += turn * dt * 1.8;
    player.pitch = clamp(player.pitch + tilt * dt * 1.2, -1.45, 1.45);
  }
  if (J.state === "none") {
    if (canControl()) movePlayer(dt);
    updateCamera(dt);
    UFO.group.position.y = UFO_HOME.y + Math.sin(t * 1.2) * 0.35;
    UFO.group.rotation.y += dt * 0.15;
    blinkUfo(t);
  } else {
    updateJourney(dt, t);
  }
  skyGroup.position.copy(camera.position);
  // 阴影跟着玩家（太阳/月亮的数量随世界而变）
  sunLights.forEach((L, i) => {
    L.position.copy(player.pos).addScaledVector(SUNS[i].dir, 120);
    L.target.position.copy(player.pos);
  });

  grassUniforms.uTime.value = t;
  fireflyMat.uniforms.uTime.value = t;
  if (WEATHER_MODE !== 0) weatherPoints.position.set(camera.position.x - BOX / 2 * 0, Math.max(camera.position.y - 14, WATER), camera.position.z);
  updateQuest(dt, t);
  cloudGroup.rotation.y = t * 0.004;
  cloudGroup.children.forEach((c) => (c.position.y += Math.sin(t * 0.3 + c.userData.bob) * 0.01));
  islands.forEach((isl, i) => { isl.position.y = isl.userData.y + Math.sin(t * 0.5 + i) * 1.5; isl.rotation.y = t * 0.03 * (i % 2 ? 1 : -1); });
  water.material.emissiveIntensity = 0.16 + Math.sin(t * 0.8) * 0.04;
  cabinLight.intensity = 12 + Math.sin(t * 7) * 0.6 + Math.sin(t * 13) * 0.4;
  smoke.forEach((s) => {
    const u = (s.userData.t + t * 0.06) % 1;
    s.position.set(2.8 + Math.sin(u * 6 + t) * 0.4 * u, 0.35 + WALL_H + 3.3 + u * 7, -1.7 + u * 1.5);
    s.scale.setScalar(0.8 + u * 3);
    s.material.opacity = Math.sin(u * Math.PI) * 0.55;
  });
  if (J.state === "none") playerHead.set(player.pos.x, player.pos.y + EYE, player.pos.z);
  else playerHead.copy(camera.position);
  Cat.update(dt, t, playerHead);

  // 第一次走进小木屋，噜噜主动打招呼
  if (!visited && inCabin(player.pos.x, player.pos.z)) {
    visited = true;
    stream("/api/visit");
  }
  if (started) updateHud();
  renderer.render(activeScene, camera);
  requestAnimationFrame(tick);
}

// ======================= 启动 =======================
fetch("/api/status").then((r) => r.json()).then((s) => {
  Cat.setName(s.persona.name);
  if (!GEN) $("startSub").textContent = `${s.persona.name}在湖边的小木屋里等你`;
  document.querySelectorAll("#chatInput").forEach((el) => (el.placeholder = `对${s.persona.name}说点什么…`));
  Cat.setEmotion(s.mood?.emotion || "calm");
}).catch(() => {});
if (GEN) {
  document.querySelector(".card h1").textContent = R.title;
  $("startSub").textContent = R.inspiration ? `灵感：${R.inspiration}` : R.intro;
  document.title = R.title;
}
updateCamera(0);
renderer.compile(scene, camera);
loadChapters();
// 调试用：在控制台里 __world.teleport(x, z, 朝向) 可以瞬移
window.__world = {
  player, CABIN, LAKE, keys, J, startJourney, goHome, UFO, Q, items, landmarks, R, cat: Cat.root,
  catOnScreen() { const p = catHeadWorld().project(camera); return p.z < 1 && Math.abs(p.x) < 1 && Math.abs(p.y) < 1; },
  // 不渲染、固定步长地模拟“玩家一直跟着噜噜走”（窗口隐藏时也能测）
  reachableShare() { let n = 0; for (const v of reach) n += v; return { cells: n, items: items.map((i) => reachable(i.x, i.z)) }; },
  simFollow(maxSec = 180) {
    const dt = 1 / 30, log = [];
    let onScreen = 0, n = 0, lastFound = Q.found, t = 0;
    const trail = [];
    for (; t < maxSec && !Q.done; t += dt) {
      // 玩家沿着噜噜走过的脚印跟
      const cp = Cat.root.position, last = trail[trail.length - 1];
      if (!last || Math.hypot(cp.x - last.x, cp.z - last.z) > 0.8) trail.push({ x: cp.x, z: cp.z });
      while (trail.length > 1 && Math.hypot(trail[0].x - player.pos.x, trail[0].z - player.pos.z) < 1.2) trail.shift();
      const aim = trail[0] || cp;
      const dx = aim.x - player.pos.x, dz = aim.z - player.pos.z;
      const d = Math.hypot(cp.x - player.pos.x, cp.z - player.pos.z);
      player.yaw = Math.atan2(-dx, -dz); player.pitch = -0.12;
      keys.KeyW = d > 2;
      movePlayer(dt);
      updateQuest(dt, t);
      updateCamera(dt);
      camera.updateMatrixWorld();
      Cat.root.updateMatrixWorld(true);
      n++; if (this.catOnScreen()) onScreen++;
      if (Q.found !== lastFound) { lastFound = Q.found; log.push(`${t.toFixed(0)}s 找到第 ${lastFound} 个`); }
    }
    keys.KeyW = false;
    return { found: Q.found, done: Q.done, seconds: Math.round(t), catOnScreenPct: Math.round((onScreen / n) * 100), log };
  },
  teleport(x, z, yaw = player.yaw, pitch = 0) { player.pos.set(x, groundAt(x, z), z); player.yaw = yaw; player.pitch = pitch; },
  hideUi(ch = "cabin") { chapter = ch; applyChapter(ch); started = true; enterFreeMode(); },
  skipToSpace() { prepareSpace(); UFO.group.attach(Cat.root); Cat.root.position.copy(UFO.seatPos); Cat.root.rotation.set(0, 0, 0); Cat.root.scale.setScalar(1); setSkyMix(1); enterSpace(); },
  programs: () => renderer.info.programs.length,
  renderNow() { const t0 = performance.now(); renderer.render(activeScene, camera); return Math.round(performance.now() - t0); },
};
tick();

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
