// 角色资产：所有页面都从这里加载伙伴的 3D 模型。换角色只改这里（模型来自 3D 资产生成平台导出的 GLB）。
import * as THREE from "three";
// 放在 vendor/ 下的短路径：Windows 打包应用的镜像目录路径很长，深层路径会超过 260 字符限制而同步失败
import { GLTFLoader } from "/static/vendor/GLTFLoader.js";

export const CHARACTER = {
  id: "lulu",
  name: "噜噜",
  url: "/static/assets/lulu/character.glb",
  // 平台导出时朝向未确认（manifest.coordinates.sourceOrientationVerified=false），需要时在这里转
  yawOffset: 0,
};

let cache = null;

// 返回一个新的模型实例：已缩放到指定高度、脚底在 y=0、水平居中
export async function loadCharacter(height = 1.9) {
  cache ||= new GLTFLoader().loadAsync(CHARACTER.url).then((g) => g.scene);
  const src = await cache;
  const model = src.clone(true);
  model.traverse((o) => {
    if (o.isMesh) {
      o.castShadow = true;
      o.receiveShadow = true;
    }
  });
  const box = new THREE.Box3().setFromObject(model);
  const size = box.getSize(new THREE.Vector3());
  model.scale.multiplyScalar(height / (size.y || 1));
  box.setFromObject(model);
  const center = box.getCenter(new THREE.Vector3());
  model.position.x -= center.x;
  model.position.z -= center.z;
  model.position.y -= box.min.y;
  const wrap = new THREE.Group();
  wrap.rotation.y = CHARACTER.yawOffset;
  wrap.add(model);
  wrap.userData.height = height;
  return wrap;
}
