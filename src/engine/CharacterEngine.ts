import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { GLTFExporter } from 'three/addons/exporters/GLTFExporter.js';
import { DRACOLoader } from 'three/addons/loaders/DRACOLoader.js';
import { MeshoptDecoder } from 'three/addons/libs/meshopt_decoder.module.js';
import { animateDemo, createDemo } from './demo';
import type { DemoRig } from './demo';
import { ACTIONS } from '../types';
import type { ActionName, Appearance, AssetInfo, Mapping, MaterialInfo, Region } from '../types';
import { RIG_BONES } from '../lib/rig';
import type { RigSettings } from '../lib/rig';

export class CharacterEngine {
  private renderer: THREE.WebGLRenderer;
  private scene = new THREE.Scene();
  private camera = new THREE.PerspectiveCamera(36, 1, .1, 100);
  private controls: OrbitControls;
  private model = new THREE.Group();
  private demo?: DemoRig;
  private mixer?: THREE.AnimationMixer;
  private clips: THREE.AnimationClip[] = [];
  private currentClip?: THREE.AnimationAction;
  private clock = new THREE.Clock();
  private elapsed = 0;
  private actionStarted = 0;
  private action: ActionName = 'idle';
  private intensity = .65;
  private mapping: Mapping = { idle: '', greet: '', enjoy_head_pat: '', hug: '', react_to_shake: '', listen: '' };
  private skeleton?: THREE.Group;
  private rigGuides?: THREE.Group;
  onRigPoint?: (name: string) => void;
  private observer: ResizeObserver;
  private frame = 0;
  private paused = false;
  private disposed = false;
  private materialMap = new Map<string, THREE.MeshStandardMaterial>();
  private pointerDown = { x: 0, y: 0 };
  private appearance: Appearance;
  private draco = new DRACOLoader();
  info!: AssetInfo;
  onRegion?: (region: Region) => void;
  onActionEnd?: () => void;
  onInfo?: (info: AssetInfo) => void;

  constructor(private container: HTMLElement, appearance: Appearance) {
    this.appearance = appearance;
    this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false, preserveDrawingBuffer: true });
    this.renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
    this.renderer.shadowMap.enabled = true; this.renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping; this.renderer.toneMappingExposure = 1.25;
    this.renderer.domElement.setAttribute('aria-label', '可旋转的 3D 模型预览，拖动旋转，滚轮缩放；骨架定位模式可点击关节');
    this.renderer.domElement.setAttribute('role', 'img');
    container.appendChild(this.renderer.domElement);
    this.scene.background = new THREE.Color('#edf2ee'); this.scene.fog = new THREE.Fog('#edf2ee', 12, 25);
    this.scene.add(new THREE.HemisphereLight('#fffdf0', '#c1cfc4', 2.7));
    const key = new THREE.DirectionalLight('#fff8e8', 4); key.position.set(-3, 6, 5); key.castShadow = true;
    key.shadow.mapSize.set(2048, 2048); key.shadow.camera.left = -5; key.shadow.camera.right = 5; key.shadow.camera.top = 6; key.shadow.camera.bottom = -4; key.shadow.normalBias = .025; key.shadow.bias = -.0001; key.shadow.radius = 5; this.scene.add(key);
    const fill = new THREE.DirectionalLight('#d5e9e1', 1.7); fill.position.set(4, 3, -3); this.scene.add(fill);
    const floor = new THREE.Mesh(new THREE.PlaneGeometry(200, 200), new THREE.MeshStandardMaterial({ color: '#edf2ee', roughness: 1 })); floor.rotation.x = -Math.PI / 2; floor.position.y = -.16; floor.receiveShadow = true; this.scene.add(floor);
    const plinth = new THREE.Mesh(new THREE.CylinderGeometry(1.24, 1.24, .12, 96), new THREE.MeshStandardMaterial({ color: '#f9faf4', roughness: .83 })); plinth.position.y = -.08; plinth.receiveShadow = true; this.scene.add(plinth);
    const ring = new THREE.Mesh(new THREE.RingGeometry(1.48, 1.488, 128), new THREE.MeshBasicMaterial({ color: '#b9cdc2', transparent: true, opacity: .65 })); ring.rotation.x = -Math.PI / 2; ring.position.y = -.145; this.scene.add(ring);
    this.scene.add(this.model);
    this.camera.position.set(4, 2.9, 7.8);
    this.controls = new OrbitControls(this.camera, this.renderer.domElement); this.controls.target.set(0, 1.28, 0);
    this.controls.enableDamping = true; this.controls.dampingFactor = .08; this.controls.minDistance = 3; this.controls.maxDistance = 13; this.controls.maxPolarAngle = Math.PI * .51;
    this.draco.setDecoderPath('/decoders/draco/');
    this.renderer.domElement.addEventListener('pointerdown', this.onPointerDown);
    this.renderer.domElement.addEventListener('pointerup', this.onPointerUp);
    this.observer = new ResizeObserver(() => this.resize()); this.observer.observe(container);
    this.loadDemo(); this.resize(); this.tick();
  }
  private resize() { const { width, height } = this.container.getBoundingClientRect(); if (!width || !height) return; this.camera.aspect = width / height; this.camera.updateProjectionMatrix(); this.renderer.setSize(width, height); }
  private onPointerDown = (e: PointerEvent) => { this.pointerDown = { x: e.clientX, y: e.clientY }; };
  private onPointerUp = (e: PointerEvent) => {
    if (Math.hypot(e.clientX - this.pointerDown.x, e.clientY - this.pointerDown.y) > 5 || e.button !== 0) return;
    const rect = this.renderer.domElement.getBoundingClientRect();
    const ray = new THREE.Raycaster(); ray.setFromCamera(new THREE.Vector2((e.clientX - rect.left) / rect.width * 2 - 1, -(e.clientY - rect.top) / rect.height * 2 + 1), this.camera);
    if (this.rigGuides) { const joint = ray.intersectObject(this.rigGuides, true).find(hit => hit.object.userData.joint); if (joint) this.onRigPoint?.(joint.object.userData.joint); return; }
    const hit = ray.intersectObject(this.model, true)[0];
    if (hit) { const region = hit.object.userData.region; this.onRegion?.(['head', 'body', 'left_hand', 'right_hand'].includes(region) ? region as Region : 'body'); }
  };
  private releaseModel() {
    this.setRigGuides(null);
    this.mixer?.stopAllAction(); if (this.mixer) this.mixer.uncacheRoot(this.model);
    this.mixer = undefined; this.clips = []; this.currentClip = undefined;
    this.removeSkeleton();
    const geometries = new Set<THREE.BufferGeometry>(); const materials = new Set<THREE.Material>(); const textures = new Set<THREE.Texture>();
    this.model.traverse(obj => { if (obj instanceof THREE.Mesh) { geometries.add(obj.geometry); const mats = Array.isArray(obj.material) ? obj.material : [obj.material]; for (const mat of mats) { materials.add(mat); for (const value of Object.values(mat)) if (value instanceof THREE.Texture) textures.add(value); } } });
    geometries.forEach(g => g.dispose()); materials.forEach(m => m.dispose()); textures.forEach(t => { t.dispose(); const image = t.source?.data; if (typeof ImageBitmap !== 'undefined' && image instanceof ImageBitmap) image.close(); });
    this.model.clear(); this.materialMap.clear(); this.demo = undefined; this.action = 'idle';
  }
  private normalize(object: THREE.Object3D) {
    object.updateMatrixWorld(true); const box = new THREE.Box3().setFromObject(object); const size = box.getSize(new THREE.Vector3());
    if (!Number.isFinite(size.y) || size.y < .00001) throw new Error('模型没有可显示的有效几何体。');
    const scale = 2.6 / size.y; const center = box.getCenter(new THREE.Vector3());
    const wrapper = new THREE.Group(); wrapper.name = 'NormalizedCharacter'; wrapper.scale.setScalar(scale);
    wrapper.position.set(-center.x * scale, -box.min.y * scale, -center.z * scale); wrapper.add(object); return wrapper;
  }
  loadDemo() {
    this.releaseModel(); this.demo = createDemo(this.appearance); this.model.add(this.normalize(this.demo.root));
    this.model.scale.setScalar(this.appearance.scale);
    this.info = this.inspect('demo', 'mori-demo.glb', 0); this.onInfo?.(this.info); this.resetView(); return this.info;
  }
  async loadCharacter(bytes: ArrayBuffer, fileName: string, source: 'import' | 'rodin' = 'import') {
    if (bytes.byteLength > 200 * 1024 * 1024) throw new Error('GLB 文件不能超过 200 MB。');
    const view = new DataView(bytes);
    if (bytes.byteLength < 20 || view.getUint32(0, true) !== 0x46546c67) throw new Error('请选择有效的 .glb 文件。');
    const jsonLength = view.getUint32(12, true);
    if (20 + jsonLength > bytes.byteLength) throw new Error('GLB 文件结构不完整。');
    const document = JSON.parse(new TextDecoder().decode(new Uint8Array(bytes, 20, jsonLength)));
    for (const resource of [...(document.images || []), ...(document.buffers || [])]) if (resource.uri && !resource.uri.startsWith('data:')) throw new Error('请导出包含所有贴图和数据的单文件 GLB；暂不支持外部资源。');
    const loader = new GLTFLoader().setDRACOLoader(this.draco).setMeshoptDecoder(MeshoptDecoder);
    const gltf = await loader.parseAsync(bytes, '');
    if (this.disposed) return this.info;
    const normalized = this.normalize(gltf.scene);
    this.releaseModel(); this.model.add(normalized); this.model.scale.setScalar(1); this.clips = gltf.animations;
    this.mixer = new THREE.AnimationMixer(this.model);
    this.info = this.inspect(source, fileName, bytes.byteLength); this.onInfo?.(this.info); this.resetView(); return this.info;
  }
  private inspect(source: AssetInfo['source'], fileName: string, size: number): AssetInfo {
    const info: AssetInfo = { source, fileName, size, meshes: 0, triangles: 0, bones: [], skinnedMeshes: 0, clips: this.clips.map(c => ({ name: c.name, duration: c.duration })), morphTargets: [], materials: [], regions: source === 'demo' ? ['head', 'body', 'left_hand', 'right_hand'] : ['body'] };
    this.model.traverse(obj => {
      const region = obj.userData.region;
      if (['head', 'body', 'left_hand', 'right_hand'].includes(region) && !info.regions.includes(region)) info.regions.push(region);
      if (obj instanceof THREE.Bone) info.bones.push({ name: obj.name, parent: obj.parent?.name || null });
      if (obj instanceof THREE.SkinnedMesh) info.skinnedMeshes++;
      if (obj instanceof THREE.Mesh) {
        info.meshes++; info.triangles += (obj.geometry.index?.count ?? obj.geometry.attributes.position?.count ?? 0) / 3;
        info.morphTargets.push(...Object.keys(obj.morphTargetDictionary || {}));
        for (const material of Array.isArray(obj.material) ? obj.material : [obj.material]) {
          if (!info.materials.includes(material.name || material.uuid)) info.materials.push(material.name || material.uuid);
          if (material instanceof THREE.MeshStandardMaterial) this.materialMap.set(material.uuid, material);
        }
        obj.castShadow = true; obj.receiveShadow = true;
      }
    });
    info.triangles = Math.round(info.triangles); info.morphTargets = [...new Set(info.morphTargets)]; return info;
  }
  getMaterials(): MaterialInfo[] { return [...this.materialMap.values()].map((m, i) => ({ id: String(i), name: m.name || `材质 ${i + 1}`, color: `#${m.color.getHexString()}` })); }
  setMaterial(id: string, color: string) { [...this.materialMap.values()][Number(id)]?.color.set(color); }
  setAppearance(appearance: Appearance) {
    this.appearance = appearance; if (!this.demo) return;
    this.demo.bodyMaterial.color.set(appearance.body); this.demo.accentMaterial.color.set(appearance.accent); this.demo.eyeMaterial.color.set(appearance.eyes);
    this.model.scale.setScalar(appearance.scale);
  }
  setMapping(mapping: Mapping) { this.mapping = mapping; }
  playAction(action: ActionName, intensity = .65): { played: boolean; message: string } {
    this.intensity = intensity;
    if (this.demo) { this.action = action; this.actionStarted = this.elapsed; return { played: true, message: '示范程序动作' }; }
    const clipName = this.mapping[action]; const clip = this.clips.find(c => c.name === clipName);
    if (!clip || !this.mixer) return { played: false, message: '尚未映射动作，请在动作联调中选择模型自带的动画。' };
    this.startClip(clip, action === 'idle'); this.action = action; this.actionStarted = this.elapsed;
    return { played: true, message: `播放动画：${clipName}` };
  }
  private startClip(clip: THREE.AnimationClip, loop: boolean) {
    const next = this.mixer!.clipAction(clip); const previous = this.currentClip;
    next.reset().setLoop(loop ? THREE.LoopRepeat : THREE.LoopOnce, loop ? Infinity : 1); next.clampWhenFinished = !loop;
    next.enabled = true; next.setEffectiveWeight(1); next.setEffectiveTimeScale(1); next.play();
    if (previous && previous !== next) next.crossFadeFrom(previous, .25, false);
    this.currentClip = next;
  }
  playClip(name: string) { const clip = this.clips.find(c => c.name === name); if (!clip || !this.mixer) return; this.paused = false; this.startClip(clip, true); this.action = 'idle'; }
  resetPose() { this.mixer?.stopAllAction(); this.currentClip = undefined; this.action = 'idle'; this.paused = true; if (this.demo) animateDemo(this.demo, 0, 'idle', 0, 0, 3); }
  setPaused(paused: boolean) { this.paused = paused; }
  resetView() { this.camera.position.set(2.5, 2.4, 6); this.controls.target.set(0, 1.25, 0); this.controls.update(); }
  setFront() { this.camera.position.set(0, 1.9, 6.5); this.controls.target.set(0, 1.25, 0); this.controls.update(); }
  setSide() { this.camera.position.set(6.5, 1.9, 0); this.controls.target.set(0, 1.25, 0); this.controls.update(); }
  setRigGuides(settings: RigSettings | null, selected = '') {
    if (this.rigGuides) { this.scene.remove(this.rigGuides); this.rigGuides.traverse(o => { if (o instanceof THREE.Mesh || o instanceof THREE.Line) { o.geometry.dispose(); for (const m of Array.isArray(o.material) ? o.material : [o.material]) m.dispose(); } }); this.rigGuides = undefined; }
    this.model.rotation.y = settings ? settings.yaw * Math.PI / 180 : 0;
    if (!settings) return;
    const height = new THREE.Box3().setFromObject(this.model).getSize(new THREE.Vector3()).y;
    this.rigGuides = new THREE.Group();
    const point = (key: string) => new THREE.Vector3(...settings.points[key]).multiplyScalar(height);
    for (const [, start, end] of RIG_BONES) { const line = new THREE.Line(new THREE.BufferGeometry().setFromPoints([point(start!), point(end!)]), new THREE.LineBasicMaterial({ color: '#497eeb', depthTest: false, transparent: true, opacity: .8 })); line.renderOrder = 20; this.rigGuides.add(line); }
    for (const key of Object.keys(settings.points)) { const dot = new THREE.Mesh(new THREE.SphereGeometry(height * (key === selected ? .017 : .010), 10, 8), new THREE.MeshBasicMaterial({ color: key === selected ? '#dc8b42' : '#4d84df', depthTest: false })); dot.position.copy(point(key)); dot.userData.joint = key; dot.renderOrder = 21; this.rigGuides.add(dot); }
    this.scene.add(this.rigGuides);
  }
  setWireframe(enabled: boolean) { this.model.traverse(obj => { if (obj instanceof THREE.Mesh) for (const material of Array.isArray(obj.material) ? obj.material : [obj.material]) if ('wireframe' in material) (material as THREE.MeshStandardMaterial).wireframe = enabled; }); }
  private removeSkeleton() { if (!this.skeleton) return; this.scene.remove(this.skeleton); this.skeleton.traverse(obj => { if (obj instanceof THREE.LineSegments) { obj.geometry.dispose(); (obj.material as THREE.Material).dispose(); } }); this.skeleton = undefined; }
  showSkeleton(enabled: boolean) {
    this.removeSkeleton(); if (!enabled || !this.info.bones.length) return;
    this.skeleton = new THREE.Group(); const helper = new THREE.SkeletonHelper(this.model); for (const material of Array.isArray(helper.material) ? helper.material : [helper.material]) material.depthTest = false; helper.renderOrder = 10; this.skeleton.add(helper); this.scene.add(this.skeleton);
  }
  screenshot() { this.renderer.render(this.scene, this.camera); return this.renderer.domElement.toDataURL('image/png'); }
  async exportModel() {
    const wireframes = [...this.materialMap.values()].map(m => [m, m.wireframe] as const); wireframes.forEach(([m]) => m.wireframe = false);
    const paused = this.paused; this.paused = true; const yaw = this.model.rotation.y; this.model.rotation.y = 0;
    try {
      if (this.demo) animateDemo(this.demo, 0, 'idle', 0, 0, 3);
      const result = await new GLTFExporter().parseAsync(this.model, { binary: true, animations: this.demo ? [] : this.clips, onlyVisible: true });
      if (!(result instanceof ArrayBuffer)) throw new Error('模型导出失败。'); return result;
    } finally { this.paused = paused; this.model.rotation.y = yaw; wireframes.forEach(([m, value]) => m.wireframe = value); }
  }
  private tick = () => {
    if (this.disposed) return; this.frame = requestAnimationFrame(this.tick);
    const delta = Math.min(this.clock.getDelta(), .05);
    if (!this.paused) {
      this.elapsed += delta; const duration = ACTIONS.find(a => a.id === this.action)!.duration;
      if (this.demo) animateDemo(this.demo, this.elapsed, this.action, this.elapsed - this.actionStarted, this.intensity, duration);
      this.mixer?.update(delta);
      const complete = this.demo ? this.elapsed - this.actionStarted > duration : this.currentClip?.time === this.currentClip?.getClip().duration;
      if (this.action !== 'idle' && complete) { this.action = 'idle'; this.onActionEnd?.(); if (!this.demo) { const idleClip = this.clips.find(c => c.name === this.mapping.idle); if (idleClip) this.startClip(idleClip, true); } }
    }
    this.controls.update(); this.renderer.render(this.scene, this.camera);
  };
  dispose() {
    this.disposed = true; cancelAnimationFrame(this.frame); this.observer.disconnect();
    this.renderer.domElement.removeEventListener('pointerdown', this.onPointerDown); this.renderer.domElement.removeEventListener('pointerup', this.onPointerUp);
    this.releaseModel(); this.controls.dispose(); this.draco.dispose();
    this.scene.traverse(obj => { if (obj instanceof THREE.Mesh) { obj.geometry.dispose(); for (const mat of Array.isArray(obj.material) ? obj.material : [obj.material]) mat.dispose(); } });
    this.renderer.dispose(); this.renderer.domElement.remove();
  }
}
