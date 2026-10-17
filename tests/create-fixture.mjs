// Original local test asset: a skinned column with two bones, one morph target,
// and a nod animation. No external assets or generation credits are needed.
import * as THREE from 'three';
import { GLTFExporter } from 'three/addons/exporters/GLTFExporter.js';
import { mkdir, writeFile } from 'node:fs/promises';

globalThis.FileReader = class {
  readAsArrayBuffer(blob) { blob.arrayBuffer().then(value => { this.result = value; this.onloadend?.(); }); }
  readAsDataURL(blob) { blob.arrayBuffer().then(value => { this.result = `data:${blob.type};base64,${Buffer.from(value).toString('base64')}`; this.onloadend?.(); }); }
};
const geometry = new THREE.CylinderGeometry(.4, .5, 2, 16, 8);
geometry.translate(0, 1, 0);
const skinIndices = []; const skinWeights = [];
for (let i = 0; i < geometry.attributes.position.count; i++) {
  const y = geometry.attributes.position.getY(i); const upper = THREE.MathUtils.clamp(y - .5, 0, 1);
  skinIndices.push(0, 1, 0, 0); skinWeights.push(1 - upper, upper, 0, 0);
}
geometry.setAttribute('skinIndex', new THREE.Uint16BufferAttribute(skinIndices, 4));
geometry.setAttribute('skinWeight', new THREE.Float32BufferAttribute(skinWeights, 4));
const morph = geometry.attributes.position.clone();
for (let i = 0; i < morph.count; i++) { morph.setX(i, morph.getX(i) * 1.15); }
geometry.morphAttributes.position = [morph];
const material = new THREE.MeshStandardMaterial({ color: '#8eb4a4' }); material.name = 'TestBody';
const mesh = new THREE.SkinnedMesh(geometry, material); mesh.name = 'TestCharacter';
mesh.morphTargetDictionary = { puff: 0 };
const rootBone = new THREE.Bone(); rootBone.name = 'hips';
const upperBone = new THREE.Bone(); upperBone.name = 'head'; upperBone.position.y = 1; rootBone.add(upperBone);
mesh.add(rootBone); mesh.bind(new THREE.Skeleton([rootBone, upperBone]));
const quaternion = new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 0, 1), .4);
const track = new THREE.QuaternionKeyframeTrack('head.quaternion', [0, .5, 1], [0, 0, 0, 1, ...quaternion.toArray(), 0, 0, 0, 1]);
const clip = new THREE.AnimationClip('greet', 1, [track]);
const scene = new THREE.Scene(); scene.add(mesh);
const bytes = await new GLTFExporter().parseAsync(scene, { binary: true, animations: [clip] });
await mkdir('.local/qa', { recursive: true });
await writeFile('.local/qa/rigged-fixture.glb', Buffer.from(bytes));
console.log('Created .local/qa/rigged-fixture.glb (2 bones, 1 skinned mesh, 1 animation, 1 morph target).');
