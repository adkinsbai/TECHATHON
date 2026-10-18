// 绘本卡通化：把生成的写实 GLB 处理成和梦幻世界、噜噜一致的卡通风格。
// 1) 材质换成和噜噜同一套三档色阶的 MeshToonMaterial；去掉法线/粗糙度/金属度这些写实细节。
// 2) 贴图“绘本化”：缩小再放大抹掉细碎纹理，提亮暗部（生成贴图常带烘焙阴影），略提饱和，向场景主色轻微靠拢。
// 3) 暖棕色描边（法线外扩的背面壳），粗细按真实米数，远近一致。
// 4) 脚下一块柔和的接地阴影，避免“浮在草上”。
import * as THREE from 'three';
import {mergeVertices} from '/static/vendor/BGUtils.js';

// 与 world.js 里噜噜的色阶一致：暗、中、亮三档。
const gradient = new THREE.DataTexture(new Uint8Array([110, 190, 255]), 3, 1, THREE.RedFormat);
gradient.minFilter = gradient.magFilter = THREE.NearestFilter;
gradient.needsUpdate = true;

export const TOON = {
  outlineColor: 0x5b4337,   // 暖棕，比纯黑柔和
  outlineRatio: 0.012,      // 描边粗细 = 资产高度 × 比例，限制在下面的范围
  outlineMin: 0.02, outlineMax: 0.07,
  textureSize: 192,         // 贴图缩到这么大再用，抹掉写实细节
  lift: 0.16,               // 暗部提亮（0 不变，1 全白）
  saturation: 1.12,
  tint: 0.08,               // 向场景主色靠拢的程度
  maxOutlineTriangles: 400000,
};

const textureCache = new WeakMap();

function storybookTexture(source, tint) {
  if (!source?.image) return source;
  const cached = textureCache.get(source);
  if (cached) return cached;
  const image = source.image, w0 = image.width || image.videoWidth, h0 = image.height || image.videoHeight;
  if (!w0 || !h0) return source;
  const k = Math.min(1, TOON.textureSize / Math.max(w0, h0));
  const w = Math.max(8, Math.round(w0 * k)), h = Math.max(8, Math.round(h0 * k));
  const canvas = document.createElement('canvas');
  canvas.width = w; canvas.height = h;
  const g = canvas.getContext('2d', {willReadFrequently: true});
  g.imageSmoothingQuality = 'high';
  g.drawImage(image, 0, 0, w, h);
  const data = g.getImageData(0, 0, w, h), px = data.data;
  const tr = tint.r * 255, tg = tint.g * 255, tb = tint.b * 255;
  for (let i = 0; i < px.length; i += 4) {
    let r = px[i], gg = px[i + 1], b = px[i + 2];
    const l = 0.299 * r + 0.587 * gg + 0.114 * b;
    r = l + (r - l) * TOON.saturation; gg = l + (gg - l) * TOON.saturation; b = l + (b - l) * TOON.saturation;
    r = r * (1 - TOON.lift) + 255 * TOON.lift; gg = gg * (1 - TOON.lift) + 255 * TOON.lift; b = b * (1 - TOON.lift) + 255 * TOON.lift;
    r += (tr - r) * TOON.tint; gg += (tg - gg) * TOON.tint; b += (tb - b) * TOON.tint;
    px[i] = r; px[i + 1] = gg; px[i + 2] = b;
  }
  g.putImageData(data, 0, 0);
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.flipY = source.flipY;
  texture.wrapS = source.wrapS; texture.wrapT = source.wrapT;
  texture.offset.copy(source.offset); texture.repeat.copy(source.repeat);
  texture.rotation = source.rotation; texture.center.copy(source.center);
  texture.channel = source.channel;
  texture.anisotropy = 4;
  textureCache.set(source, texture);
  return texture;
}

function storybookColor(color, tint) {
  const c = color.clone();
  const hsl = {};
  c.getHSL(hsl);
  c.setHSL(hsl.h, Math.min(1, hsl.s * TOON.saturation), hsl.l * (1 - TOON.lift) + TOON.lift);
  return c.lerp(tint, TOON.tint);
}

function toonMaterial(source, tint) {
  const material = new THREE.MeshToonMaterial({
    gradientMap: gradient,
    color: source.map ? new THREE.Color(0xffffff) : storybookColor(source.color || new THREE.Color(0xdddddd), tint),
    map: source.map ? storybookTexture(source.map, tint) : null,
    alphaMap: source.alphaMap || null,
    transparent: source.transparent, opacity: source.opacity, alphaTest: source.alphaTest,
    side: source.side, vertexColors: source.vertexColors,
  });
  if (source.emissive && source.emissiveIntensity > 0 && source.emissive.getHex() !== 0) {
    material.emissive = source.emissive.clone();
    material.emissiveMap = source.emissiveMap || null;
    material.emissiveIntensity = source.emissiveIntensity;
  }
  material.name = (source.name || 'material') + '-toon';
  return material;
}

function outlineMaterial(thickness) {
  const material = new THREE.MeshBasicMaterial({color: TOON.outlineColor, side: THREE.BackSide});
  material.onBeforeCompile = (shader) => {
    shader.uniforms.uOutline = {value: thickness};
    shader.vertexShader = 'uniform float uOutline;\n' + shader.vertexShader.replace(
      '#include <begin_vertex>', '#include <begin_vertex>\ntransformed += normalize(normal) * uOutline;');
  };
  // 每个描边粗细不同，避免共用同一个编译后的程序时串值。
  material.customProgramCacheKey = () => 'toon-outline-' + thickness.toFixed(5);
  return material;
}

function outlineGeometry(geometry, skinned) {
  // 只用位置（绑骨模型再加蒙皮权重）做描边壳；合并重合顶点后算平滑法线，硬边处才不会裂缝。
  const shell = new THREE.BufferGeometry();
  shell.setAttribute('position', geometry.getAttribute('position'));
  if (skinned) {
    shell.setAttribute('skinIndex', geometry.getAttribute('skinIndex'));
    shell.setAttribute('skinWeight', geometry.getAttribute('skinWeight'));
  }
  if (geometry.index) shell.setIndex(geometry.index);
  const merged = mergeVertices(shell, 1e-4);
  merged.computeVertexNormals();
  return merged;
}

/**
 * 原地把一个已归一化（米制、落地）的模板处理成卡通风格。
 * root：模板根节点（已设置好缩放）；heightM：资产真实高度；tintHex：场景主色。
 */
export function toonify(root, {heightM, tintHex = '#f2a65a', outline = true} = {}) {
  const tint = new THREE.Color(tintHex);
  const materials = new Map();
  const convert = (m) => {
    if (!materials.has(m)) materials.set(m, toonMaterial(m, tint));
    return materials.get(m);
  };
  root.updateMatrixWorld(true);
  const thicknessM = THREE.MathUtils.clamp(heightM * TOON.outlineRatio, TOON.outlineMin, TOON.outlineMax);
  const meshes = [];
  root.traverse((o) => { if (o.isMesh && !o.userData.toonOutline) meshes.push(o); });
  let triangles = 0;
  for (const mesh of meshes) {
    mesh.material = Array.isArray(mesh.material) ? mesh.material.map(convert) : convert(mesh.material);
    mesh.castShadow = mesh.receiveShadow = true;
    triangles += (mesh.geometry.index ? mesh.geometry.index.count : mesh.geometry.getAttribute('position').count) / 3;
  }
  if (!outline || triangles > TOON.maxOutlineTriangles) return {triangles, outlined: false};
  const scale = new THREE.Vector3();
  for (const mesh of meshes) {
    if (mesh.isInstancedMesh) continue;
    const skinned = mesh.isSkinnedMesh && mesh.geometry.getAttribute('skinIndex') && mesh.geometry.getAttribute('skinWeight');
    mesh.getWorldScale(scale);
    const local = thicknessM / Math.max(1e-6, (Math.abs(scale.x) + Math.abs(scale.y) + Math.abs(scale.z)) / 3);
    const geometry = outlineGeometry(mesh.geometry, skinned), material = outlineMaterial(local);
    // 绑骨模型：描边壳也是蒙皮网格，绑到同一副骨骼，动作时跟着一起变形。
    const shell = skinned ? new THREE.SkinnedMesh(geometry, material) : new THREE.Mesh(geometry, material);
    if (skinned) { shell.bindMode = mesh.bindMode; shell.bind(mesh.skeleton, mesh.bindMatrix); shell.frustumCulled = false; }
    shell.userData.toonOutline = true;
    shell.castShadow = false; shell.receiveShadow = false;
    shell.raycast = () => {};
    mesh.add(shell);
  }
  return {triangles, outlined: true};
}

let blobTexture = null;
/** 脚下的柔和接地阴影（平放在地面上的径向渐变圆片）。 */
export function contactShadow(radiusM, opacity = 0.35) {
  if (!blobTexture) {
    const c = document.createElement('canvas');
    c.width = c.height = 128;
    const g = c.getContext('2d'), grad = g.createRadialGradient(64, 64, 0, 64, 64, 64);
    grad.addColorStop(0, 'rgba(70,52,60,1)');
    grad.addColorStop(0.55, 'rgba(70,52,60,.55)');
    grad.addColorStop(1, 'rgba(70,52,60,0)');
    g.fillStyle = grad; g.fillRect(0, 0, 128, 128);
    blobTexture = new THREE.CanvasTexture(c);
    blobTexture.colorSpace = THREE.SRGBColorSpace;
  }
  const disc = new THREE.Mesh(new THREE.CircleGeometry(radiusM, 32).rotateX(-Math.PI / 2),
    new THREE.MeshBasicMaterial({map: blobTexture, transparent: true, opacity, depthWrite: false,
      polygonOffset: true, polygonOffsetFactor: -2, polygonOffsetUnits: -2}));
  disc.position.y = 0.04;
  disc.renderOrder = 1;
  disc.userData.contactShadow = true;
  disc.raycast = () => {};
  return disc;
}
