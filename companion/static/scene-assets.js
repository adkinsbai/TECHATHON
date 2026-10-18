import * as THREE from 'three';
import {GLTFLoader} from '/static/vendor/GLTFLoader.js';
import {textSprite} from '/static/worldgen.js?v=2';
import {toonify, contactShadow} from '/static/toonify.js?v=3';

// 默认按绘本卡通风格处理生成的模型；地址加 ?style=pbr 可看原始写实材质做对比。
const TOON_ON = new URLSearchParams(location.search).get('style') !== 'pbr';

// 绑骨模型不能用普通 clone：骨骼要换成克隆出来的那一套，否则所有实例共用一副骨骼。
function cloneWithSkeletons(source) {
  const clone = source.clone(true), map = new Map();
  const walk = (a, b) => { map.set(a, b); for (let i = 0; i < a.children.length; i++) walk(a.children[i], b.children[i]); };
  walk(source, clone);
  for (const [from, to] of map) {
    if (from.isSkinnedMesh) to.bind(new THREE.Skeleton(from.skeleton.bones.map(b => map.get(b) || b), from.skeleton.boneInverses), from.bindMatrix);
  }
  return clone;
}

// Tripo 动作文件：可能一个文件里有全部动作，也可能每个动作一个文件；统一收集成带名字的动作片段。
async function loadRigged(loader, clips) {
  const files = await Promise.all(clips.map(c => loader.loadAsync(c.url + '?v=' + c.sha256)));
  const animations = [];
  files.forEach((gltf, i) => gltf.animations.forEach(a => {
    const clip = a.clone();
    clip.name = (gltf.animations.length > 1 && a.name ? a.name : clips[i].name).toLowerCase();
    animations.push(clip);
  }));
  return {gltf: files[0], animations};
}

// Asset normalization and scene instances are separate. Parent-relative meters
// (e.g. a parrot on a tree) never inherit the imported file's arbitrary units.
export async function mountGeneratedScene({scene, job, heightAt, colliders}) {
  const loader = new GLTFLoader(), nodes = new Map(), templates = new Map(), errors = [], mixers = [];
  const group = new THREE.Group();group.name='generated-scene-'+job.id;scene.add(group);
  const panel=document.createElement('div');panel.id='generated-scene-status';
  Object.assign(panel.style,{position:'fixed',left:'20px',bottom:'20px',zIndex:9,padding:'10px 16px',borderRadius:'8px',background:'rgba(250,247,235,.93)',color:'#344632',font:'12px/1.7 system-ui',maxWidth:'300px'});
  panel.textContent='正在导入场景资产…';document.body.append(panel);
  let loaded=0;
  await Promise.all(job.plan.assets.map(async asset=>{
    const record=job.assets[asset.id];
    if(record.state!=='ready'){errors.push(asset.name+'：尚未生成');return;}
    try{
      let gltf=null,animations=[];
      if(record.rig?.state==='ready'&&record.rig.clips?.length){
        try{({gltf,animations}=await loadRigged(loader,record.rig.clips));}
        catch(e){console.warn('Rigged asset failed, using static model',asset.id,e);}
      }
      gltf=gltf||await loader.loadAsync(record.model_url+'?v='+record.model_sha256);
      const source=gltf.scene;source.updateMatrixWorld(true);
      const box=new THREE.Box3().setFromObject(source),size=box.getSize(new THREE.Vector3()),center=box.getCenter(new THREE.Vector3());
      if(!Number.isFinite(size.y)||size.y<1e-6)throw new Error('模型尺寸无效');
      const normalized=new THREE.Group();normalized.name=asset.id;
      source.position.sub(new THREE.Vector3(center.x,box.min.y,center.z));
      normalized.add(source);normalized.scale.setScalar(asset.height_m/size.y);
      source.traverse(o=>{if(o.isMesh){o.castShadow=o.receiveShadow=true;}});
      if(TOON_ON)toonify(normalized,{heightM:asset.height_m,tintHex:job.recipe?.palette?.accent});
      normalized.userData.animations=animations;
      templates.set(asset.id,normalized);loaded++;
      panel.textContent=`已导入 ${loaded}/${job.plan.assets.length} 类资产`;
    }catch(e){errors.push(asset.name+'：加载失败');console.error('Scene asset failed',asset.id,e);}
  }));
  const attach=node=>{
    if(nodes.has(node.id))return nodes.get(node.id);
    const definition=job.plan.assets.find(a=>a.id===node.asset_id);
    const root=new THREE.Group();root.name=node.id;root.userData.assetId=node.asset_id;
    nodes.set(node.id,root);
    const parent=node.parent_id?attach(job.plan.instances.find(n=>n.id===node.parent_id)):group;
    parent.add(root);
    root.position.fromArray(node.position);root.rotation.y=node.yaw;root.scale.setScalar(node.scale);
    if(!node.parent_id)root.position.y+=heightAt(root.position.x,root.position.z);
    const template=templates.get(node.asset_id);
    if(template){
      const body=cloneWithSkeletons(template);root.add(body);
      const clips=template.userData.animations||[];
      if(clips.length){
        // 有动作就一直播：默认待机，移动时切到走路（打斗时由下面的时间线控制权重）。
        const mixer=new THREE.AnimationMixer(body),find=re=>clips.find(c=>re.test(c.name));
        const idleClip=find(/idle|stand|breath/)||clips[0],walkClip=find(/walk|run|move/);
        const idle=mixer.clipAction(idleClip).play();idle.time=Math.random()*idleClip.duration;
        const walk=walkClip&&walkClip!==idleClip?mixer.clipAction(walkClip).play():null;
        if(walk)walk.setEffectiveWeight(0);
        root.userData.anim={mixer,idle,walk};mixers.push(mixer);
      }
    }
    else{const label=textSprite(definition.name+' · 待制作');label.position.y=2;root.add(label);}
    root.userData.base=root.position.clone();root.userData.definition=definition;
    if(!node.parent_id&&TOON_ON){
      const r=Math.min(4,Math.max(.3,definition.collision_radius_m*1.4,definition.height_m*.25));
      root.add(contactShadow(r/Math.max(.01,node.scale)));
    }
    if(!node.parent_id&&definition.collision_radius_m>0){
      const collider={x:root.position.x,z:root.position.z,r:definition.collision_radius_m*node.scale};colliders.push(collider);root.userData.collider=collider;
    }
    return root;
  };
  for(const node of job.plan.instances)attach(node);
  // Labels belong to exhibits, rather than repeating over every tree instance.
  const labeled=new Set();
  for(const node of job.plan.instances){
    const root=nodes.get(node.id),asset=root.userData.definition;
    if(asset.kind==='plant'||labeled.has(asset.id))continue;labeled.add(asset.id);
    const label=textSprite(asset.name);label.position.y=asset.height_m+1.2;root.add(label);
  }
  const fights=job.plan.relations.filter(r=>r.kind==='fighting');
  const setMoving=(root,amount)=>{const a=root.userData.anim;if(!a?.walk)return;a.walk.setEffectiveWeight(amount);a.idle.setEffectiveWeight(1-amount);};
  let motionSample=-1;
  function update(dt,t){
    for(const mixer of mixers)mixer.update(dt);
    for(const relation of fights){
      const pair=relation.subjects.map(id=>nodes.get(id));
      const [a,b]=pair.map(n=>n.userData.base);
      const toward=new THREE.Vector3(b.x-a.x,0,b.z-a.z).normalize();
      const phase=t%7,approach=phase>2&&phase<4?Math.sin((phase-2)/2*Math.PI)*Math.min(1.6,a.distanceTo(b)*.25):0;
      pair.forEach((root,i)=>{
        const sign=i===0?1:-1,base=root.userData.base;
        root.position.copy(base).addScaledVector(toward,approach*sign);
        root.position.x+=Math.cos(t*1.3+i*Math.PI)*.18;
        root.position.y=heightAt(root.position.x,root.position.z)+Math.max(0,Math.sin((phase-2)*Math.PI))*approach*.1;
        root.rotation.y=Math.atan2(toward.x*sign,toward.z*sign);
        setMoving(root,approach>.05?1:0);
        const c=root.userData.collider;if(c){c.x=root.position.x;c.z=root.position.z;}
      });
    }
    if(Math.floor(t*2)!==motionSample){
      motionSample=Math.floor(t*2);
      panel.dataset.motionSample=JSON.stringify(fights.flatMap(r=>r.subjects.map(id=>({id,position:nodes.get(id).position.toArray()}))));
    }
  }
  panel.replaceChildren();const name=document.createElement('strong');name.textContent=job.plan.title;panel.append(name,document.createElement('br'));
  const info=document.createElement('span');info.textContent=`${loaded}/${job.plan.assets.length} 类真实 3D 资产 · ${nodes.size} 个实例`;panel.append(info);
  if(errors.length){const line=document.createElement('div');line.textContent=errors.join('；');panel.append(line);}
  const link=document.createElement('a');link.href='/world-studio?scene='+job.id;link.textContent='返回世界工作室 ↗';Object.assign(link.style,{display:'block',color:'#7b6844'});panel.append(link);
  function summary(){let meshes=0,triangles=0;group.traverse(o=>{if(o.isMesh){meshes++;triangles+=(o.geometry.index?.count||o.geometry.attributes.position?.count||0)/3;}});return {animatedInstances:mixers.length,loadedAssetTypes:loaded,assetTypes:job.plan.assets.length,instances:nodes.size,meshes,triangles:Math.round(triangles),errors,assetInstances:Object.fromEntries(job.plan.assets.map(a=>[a.id,job.plan.instances.filter(n=>n.asset_id===a.id).length])),heights:Object.fromEntries(job.plan.assets.map(a=>[a.id,a.height_m])),relations:job.plan.relations};}
  panel.dataset.sceneReport=JSON.stringify(summary());
  return {group,nodes,update,summary};
}
