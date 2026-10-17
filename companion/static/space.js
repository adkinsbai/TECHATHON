// 深空场景：刚离开的梦幻星球、星环行星、条纹巨行星、冰星球和它的月亮、糖果星球、小行星带、星云和满天星。
import * as THREE from "three";

const rand = (a, b) => a + Math.random() * (b - a);

function canvasTex(w, h, draw) {
  const c = document.createElement("canvas");
  c.width = w; c.height = h;
  draw(c.getContext("2d"), w, h);
  const t = new THREE.CanvasTexture(c);
  t.colorSpace = THREE.SRGBColorSpace;
  t.anisotropy = 4;
  return t;
}
const glow = (color, alpha = "ff") => canvasTex(256, 256, (g) => {
  const grd = g.createRadialGradient(128, 128, 0, 128, 128, 128);
  grd.addColorStop(0, color + alpha); grd.addColorStop(0.3, color + "88"); grd.addColorStop(1, color + "00");
  g.fillStyle = grd; g.fillRect(0, 0, 256, 256);
});

// 简单的 2D 值噪声，用来画星球表面
function makeNoise(seed) {
  const h = (x, y) => {
    let n = Math.imul((x | 0) + seed * 101, 374761393) ^ Math.imul(y | 0, 668265263);
    n = Math.imul(n ^ (n >>> 13), 1274126177);
    return ((n ^ (n >>> 16)) >>> 0) / 4294967296;
  };
  const vn = (x, y) => {
    const xi = Math.floor(x), yi = Math.floor(y), xf = x - xi, yf = y - yi;
    const u = xf * xf * (3 - 2 * xf), v = yf * yf * (3 - 2 * yf);
    const a = h(xi, yi), b = h(xi + 1, yi), c = h(xi, yi + 1), d = h(xi + 1, yi + 1);
    return a + (b - a) * u + (c - a) * v + (a - b - c + d) * u * v;
  };
  return (x, y, o = 5) => { let s = 0, a = 0.5, f = 1; for (let i = 0; i < o; i++) { s += a * vn(x * f, y * f); f *= 2; a *= 0.5; } return s; };
}

// 等距柱状投影贴图：按经纬度采样噪声（x 方向首尾相接）
function planetTexture(seed, paint, w = 512, h = 256) {
  const nz = makeNoise(seed);
  return canvasTex(w, h, (g) => {
    const img = g.createImageData(w, h);
    for (let y = 0; y < h; y++) {
      const lat = (y / h) * Math.PI;
      for (let x = 0; x < w; x++) {
        const lon = (x / w) * Math.PI * 2;
        const px = Math.cos(lon) * Math.sin(lat), py = Math.cos(lat), pz = Math.sin(lon) * Math.sin(lat);
        const n = nz(px * 2.2 + 10 + pz * 0.7, py * 2.2 + pz * 1.9 + 5);
        const [r, gg, b] = paint(n, y / h, nz, px, py, pz);
        const i = (y * w + x) * 4;
        img.data[i] = r; img.data[i + 1] = gg; img.data[i + 2] = b; img.data[i + 3] = 255;
      }
    }
    g.putImageData(img, 0, 0);
  });
}
const mix = (a, b, t) => a.map((v, i) => v + (b[i] - v) * Math.max(0, Math.min(1, t)));

export function createSpace() {
  const scene = new THREE.Scene();
  scene.background = new THREE.Color("#07051a");

  // ---------- 星空 ----------
  {
    const n = 9000, pos = new Float32Array(n * 3), col = new Float32Array(n * 3), c = new THREE.Color();
    for (let i = 0; i < n; i++) {
      const v = new THREE.Vector3().randomDirection().multiplyScalar(rand(9000, 14000));
      pos.set([v.x, v.y, v.z], i * 3);
      c.setHSL(Math.random() < 0.3 ? rand(0.55, 0.7) : rand(0.0, 0.15), rand(0.2, 0.7), rand(0.7, 1));
      col.set([c.r, c.g, c.b], i * 3);
    }
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.BufferAttribute(pos, 3));
    g.setAttribute("color", new THREE.BufferAttribute(col, 3));
    scene.add(new THREE.Points(g, new THREE.PointsMaterial({ size: 2.2, sizeAttenuation: false, vertexColors: true, transparent: true, opacity: 0.9, depthWrite: false })));
  }
  // 星云：几团大的彩色光雾
  const nebulae = [];
  for (const [color, pos, size] of [
    ["#ff6fb5", [-6000, 2500, -9000], 9000], ["#7b6cff", [5000, -1500, -10000], 10000], ["#3fd6ff", [8000, 3000, -3000], 7000],
    ["#ffb36b", [-8000, -2000, 2000], 8000], ["#c06bff", [0, 6000, -6000], 8000], ["#6bffc9", [-3000, -5000, -7000], 6000],
  ]) {
    const s = new THREE.Sprite(new THREE.SpriteMaterial({ map: glow(color, "60"), transparent: true, opacity: 0.55, depthWrite: false, blending: THREE.AdditiveBlending }));
    s.position.set(...pos);
    s.scale.setScalar(size);
    scene.add(s);
    nebulae.push(s);
  }
  // 远处的螺旋星系
  {
    const tex = canvasTex(256, 256, (g) => {
      g.translate(128, 128);
      for (let i = 0; i < 2400; i++) {
        const arm = i % 2, t = Math.random() * 5, r = t * 22 + rand(-8, 8), a = t * 1.4 + arm * Math.PI + rand(-0.3, 0.3);
        g.fillStyle = `hsla(${rand(260, 330)},80%,${rand(70, 95)}%,${rand(0.2, 0.7)})`;
        g.fillRect(Math.cos(a) * r, Math.sin(a) * r * 0.55, 1.6, 1.6);
      }
      const grd = g.createRadialGradient(0, 0, 0, 0, 0, 40);
      grd.addColorStop(0, "rgba(255,240,220,.95)"); grd.addColorStop(1, "rgba(255,200,230,0)");
      g.fillStyle = grd; g.beginPath(); g.ellipse(0, 0, 40, 24, 0, 0, Math.PI * 2); g.fill();
    });
    const s = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending }));
    s.position.set(4000, 4500, -11000);
    s.scale.setScalar(3200);
    scene.add(s);
  }

  // ---------- 光源：两颗太阳 ----------
  scene.add(new THREE.AmbientLight(0x8a7bb8, 0.55));
  const SUN_DIR = new THREE.Vector3(0.6, 0.35, 0.7).normalize();
  const sunLight = new THREE.DirectionalLight(0xffe6c0, 2.6);
  sunLight.position.copy(SUN_DIR).multiplyScalar(1000);
  scene.add(sunLight);
  const sun2Light = new THREE.DirectionalLight(0xff9fd6, 0.9);
  sun2Light.position.set(-0.8, 0.2, 0.5).multiplyScalar(1000);
  scene.add(sun2Light);
  for (const [dir, color, r, glowSize] of [[SUN_DIR, "#ffd27a", 380, 3600], [sun2Light.position.clone().normalize(), "#ff8fcf", 220, 2400]]) {
    const p = dir.clone().multiplyScalar(11000);
    const disc = new THREE.Mesh(new THREE.SphereGeometry(r, 32, 16), new THREE.MeshBasicMaterial({ color }));
    disc.position.copy(p);
    const halo = new THREE.Sprite(new THREE.SpriteMaterial({ map: glow(color), transparent: true, depthWrite: false, blending: THREE.AdditiveBlending }));
    halo.position.copy(p);
    halo.scale.setScalar(glowSize);
    scene.add(disc, halo);
  }

  const planets = [];
  const atmo = (radius, color, strength = 0.9) => {
    // 大气辉光：背面渲染的稍大球体，边缘亮、中间透
    const m = new THREE.ShaderMaterial({
      uniforms: { c: { value: new THREE.Color(color) }, k: { value: strength } },
      vertexShader: "varying vec3 vN; varying vec3 vV; void main(){ vec4 mv = modelViewMatrix * vec4(position,1.0); vN = normalize(normalMatrix * normal); vV = normalize(-mv.xyz); gl_Position = projectionMatrix * mv; }",
      fragmentShader: "uniform vec3 c; uniform float k; varying vec3 vN; varying vec3 vV; void main(){ float f = pow(1.0 - abs(dot(vN, vV)), 2.5) * k; gl_FragColor = vec4(c * f, f); }",
      side: THREE.BackSide, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
    });
    return new THREE.Mesh(new THREE.SphereGeometry(radius * 1.12, 48, 32), m);
  };
  function addPlanet({ name, radius, pos, tex, atmoColor, spin = 0.02, tilt = 0.2, note }) {
    const g = new THREE.Group();
    g.position.set(...pos);
    g.rotation.z = tilt;
    const body = new THREE.Mesh(new THREE.SphereGeometry(radius, 64, 48), new THREE.MeshStandardMaterial({ map: tex, roughness: 0.9 }));
    g.add(body);
    if (atmoColor) g.add(atmo(radius, atmoColor));
    scene.add(g);
    const p = { name, radius, group: g, body, spin, note, center: g.position };
    planets.push(p);
    return p;
  }

  // ---------- 梦幻星球（刚离开的家） ----------
  const home = addPlanet({
    name: "梦幻星球", radius: 300, pos: [0, 0, 0], atmoColor: "#ff9fd0", spin: 0.01, tilt: 0.15,
    tex: planetTexture(1, (n, v) => {
      if (n < 0.43) return mix([110, 200, 240], [150, 225, 250], n / 0.43);             // 湖海
      if (n < 0.46) return [245, 222, 180];                                             // 沙滩
      const land = mix([140, 215, 135], [95, 185, 120], (n - 0.46) * 4);
      if (n > 0.66) return mix([190, 165, 230], [255, 225, 240], (n - 0.66) * 6);       // 淡紫山
      return Math.abs(v - 0.5) > 0.42 ? [250, 240, 255] : land;                        // 两极
    }),
    note: "",
  });
  { // 彩色云层
    const clouds = new THREE.Mesh(new THREE.SphereGeometry(306, 64, 48), new THREE.MeshStandardMaterial({
      map: canvasTex(1024, 512, (g, w, h) => {
        for (let i = 0; i < 260; i++) {
          g.fillStyle = `hsla(${[330, 280, 30, 190, 150][i % 5]},90%,88%,${rand(0.25, 0.6)})`;
          const x = Math.random() * w, y = h * (0.15 + Math.random() * 0.7);
          g.beginPath(); g.ellipse(x, y, rand(20, 60), rand(6, 14), 0, 0, Math.PI * 2); g.fill();
        }
      }), transparent: true, depthWrite: false,
    }));
    home.group.add(clouds);
    home.clouds = clouds;
  }

  // ---------- 星环行星 ----------
  const ringed = addPlanet({
    name: "星环行星", radius: 260, pos: [2600, 700, -4200], atmoColor: "#ffd6a0", spin: 0.015, tilt: 0.35,
    tex: planetTexture(7, (n, v) => {
      const band = Math.sin(v * 38 + n * 7) * 0.5 + 0.5;
      return mix(mix([255, 214, 170], [235, 170, 200], band), [200, 175, 240], n * 0.6);
    }),
    note: "你们坐着 UFO 正从一颗巨大的星环行星旁边飞过：淡橘和粉紫条纹的星球，外面套着一圈又宽又亮、一层层的彩色星环。",
  });
  {
    const inner = 340, outer = 640;
    const geo = new THREE.RingGeometry(inner, outer, 160, 4);
    const pos = geo.attributes.position, uv = geo.attributes.uv, v3 = new THREE.Vector3();
    for (let i = 0; i < pos.count; i++) { v3.fromBufferAttribute(pos, i); uv.setXY(i, (v3.length() - inner) / (outer - inner), 0.5); }
    const tex = canvasTex(512, 4, (g, w) => {
      for (let x = 0; x < w; x++) {
        const t = x / w, a = (0.35 + 0.65 * Math.abs(Math.sin(t * 40) * Math.sin(t * 7.3))) * (t < 0.04 || t > 0.97 ? 0.2 : 1) * (Math.abs(t - 0.62) < 0.025 ? 0.1 : 1);
        g.fillStyle = `hsla(${20 + t * 300},80%,${75 + 10 * Math.sin(t * 25)}%,${a})`;
        g.fillRect(x, 0, 1, 4);
      }
    });
    const ring = new THREE.Mesh(geo, new THREE.MeshBasicMaterial({ map: tex, side: THREE.DoubleSide, transparent: true, depthWrite: false }));
    ring.rotation.x = Math.PI / 2 - 0.25;
    ringed.group.add(ring);
  }

  // ---------- 条纹巨行星 ----------
  addPlanet({
    name: "条纹巨行星", radius: 420, pos: [-2600, -500, -8200], atmoColor: "#ffb38a", spin: 0.02, tilt: 0.1,
    tex: planetTexture(3, (n, v, nz, px, py, pz) => {
      const swirl = Math.sin(v * 26 + nz(px * 3, pz * 3, 3) * 6);
      let c = mix([255, 190, 150], [240, 140, 160], swirl * 0.5 + 0.5);
      c = mix(c, [255, 240, 215], Math.max(0, Math.sin(v * 9)) * 0.4);
      const spot = Math.hypot(px - 0.6, py + 0.25, pz - 0.5);
      if (spot < 0.22) c = mix([230, 110, 140], c, spot / 0.22);
      return c;
    }),
    note: "你们坐着 UFO 正飞过一颗超级大的条纹巨行星：橘粉色一圈圈的云带，还有一个旋转着的大红斑。",
  });

  // ---------- 小行星带 ----------
  const belt = new THREE.InstancedMesh(new THREE.DodecahedronGeometry(1, 0), new THREE.MeshStandardMaterial({ color: 0xb8a6c9, roughness: 1, flatShading: true }), 900);
  {
    const m = new THREE.Matrix4(), q = new THREE.Quaternion(), s = new THREE.Vector3(), v = new THREE.Vector3(), e = new THREE.Euler(), c = new THREE.Color();
    for (let i = 0; i < belt.count; i++) {
      const a = Math.random() * Math.PI * 2, r = rand(500, 1100);
      v.set(Math.cos(a) * r, rand(-60, 60), Math.sin(a) * r).add(new THREE.Vector3(200, 150, -6000));
      const sc = Math.pow(Math.random(), 3) * 26 + 3;
      m.compose(v, q.setFromEuler(e.set(rand(0, 6), rand(0, 6), rand(0, 6))), s.set(sc, sc * rand(0.6, 1), sc * rand(0.7, 1.2)));
      belt.setMatrixAt(i, m);
      belt.setColorAt(i, c.setHSL(rand(0.7, 0.95), 0.25, rand(0.55, 0.75)));
    }
    scene.add(belt);
  }

  // ---------- 冰星球 + 月亮 ----------
  const ice = addPlanet({
    name: "冰晶星球", radius: 170, pos: [1800, -200, -10600], atmoColor: "#9fe6ff", spin: 0.03, tilt: 0.4,
    tex: planetTexture(11, (n) => (n > 0.55 ? mix([235, 248, 255], [255, 255, 255], (n - 0.55) * 4) : mix([110, 170, 235], [170, 220, 250], n * 1.6))),
    note: "你们坐着 UFO 正飞过一颗冰晶星球：整颗星球是冰蓝色和白色的，亮晶晶的，旁边还有一个小月亮在绕着它转。",
  });
  const moon = new THREE.Mesh(new THREE.SphereGeometry(40, 32, 24), new THREE.MeshStandardMaterial({
    map: planetTexture(12, (n) => mix([170, 165, 185], [235, 230, 240], n), 256, 128), roughness: 1,
  }));
  ice.group.add(moon);

  // ---------- 糖果星球 ----------
  addPlanet({
    name: "糖果星球", radius: 210, pos: [-1500, 900, -13400], atmoColor: "#ffc4e6", spin: 0.025, tilt: -0.3,
    tex: planetTexture(21, (n, v, nz, px, py, pz) => {
      const s = Math.sin((px + pz) * 9 + py * 5 + n * 8);
      return s > 0.3 ? [255, 190, 220] : s > -0.3 ? [190, 250, 220] : [255, 245, 200];
    }),
    note: "你们坐着 UFO 正飞过一颗糖果星球：粉色、薄荷绿、奶黄色的条纹像棉花糖一样一圈圈卷着。",
  });

  // ---------- 飞行路线（闭环） ----------
  const route = new THREE.CatmullRomCurve3([
    new THREE.Vector3(0, 330, 0), new THREE.Vector3(200, 900, -900), new THREE.Vector3(1300, 1100, -2800),
    new THREE.Vector3(2400, 1150, -4900), new THREE.Vector3(1100, 600, -6100), new THREE.Vector3(-1500, 200, -7200),
    new THREE.Vector3(-1700, 300, -9300), new THREE.Vector3(1300, 200, -10100), new THREE.Vector3(1200, 700, -12000),
    new THREE.Vector3(-1100, 1400, -12600), new THREE.Vector3(-2500, 1600, -9000), new THREE.Vector3(-1800, 1400, -3500),
    new THREE.Vector3(-500, 800, -900),
  ], true, "catmullrom", 0.4);
  const routeLength = route.getLength();

  // 流星
  const meteors = [];
  const meteorTex = glow("#ffffff");
  function spawnMeteor(around) {
    const s = new THREE.Sprite(new THREE.SpriteMaterial({ map: meteorTex, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, color: new THREE.Color().setHSL(Math.random(), 0.6, 0.8) }));
    s.position.copy(around).add(new THREE.Vector3(rand(-1500, 1500), rand(300, 900), rand(-1500, 1500)));
    s.scale.set(60, 60, 1);
    s.userData = { v: new THREE.Vector3(rand(-1, 1), -0.5, rand(-1, 1)).normalize().multiplyScalar(rand(500, 900)), life: 0 };
    scene.add(s);
    meteors.push(s);
  }

  function update(dt, t, near) {
    for (const p of planets) p.body.rotation.y += p.spin * dt;
    if (home.clouds) home.clouds.rotation.y += 0.015 * dt;
    moon.position.set(Math.cos(t * 0.15) * 320, Math.sin(t * 0.15) * 60, Math.sin(t * 0.15) * 320);
    belt.rotation.y = t * 0.004;
    nebulae.forEach((n, i) => (n.material.opacity = 0.45 + Math.sin(t * 0.2 + i) * 0.1));
    if (Math.random() < dt * 0.4) spawnMeteor(near);
    for (let i = meteors.length - 1; i >= 0; i--) {
      const m = meteors[i];
      m.userData.life += dt;
      m.position.addScaledVector(m.userData.v, dt);
      m.material.opacity = Math.max(0, 1 - m.userData.life / 2.5);
      if (m.userData.life > 2.5) { scene.remove(m); meteors.splice(i, 1); }
    }
  }

  return { scene, planets, home, route, routeLength, update };
}
