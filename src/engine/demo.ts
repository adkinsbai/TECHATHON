import * as THREE from 'three';
import type { ActionName, Appearance, Region } from '../types';

export type DemoRig = {
  root: THREE.Group; head: THREE.Group; leftArm: THREE.Group; rightArm: THREE.Group;
  leftEar: THREE.Group; rightEar: THREE.Group; eyes: THREE.Mesh[];
  bodyMaterial: THREE.MeshStandardMaterial; accentMaterial: THREE.MeshStandardMaterial; eyeMaterial: THREE.MeshStandardMaterial;
};

export function createDemo(appearance: Appearance): DemoRig {
  const root = new THREE.Group(); root.name = 'Mori';
  const bodyMaterial = new THREE.MeshStandardMaterial({ color: appearance.body, roughness: 0.87 }); bodyMaterial.name = '身体与耳朵';
  const accentMaterial = new THREE.MeshStandardMaterial({ color: appearance.accent, roughness: 0.95 }); accentMaterial.name = '围兜与耳内';
  const eyeMaterial = new THREE.MeshStandardMaterial({ color: appearance.eyes, roughness: 0.26 }); eyeMaterial.name = '眼睛';
  const cream = new THREE.MeshStandardMaterial({ color: '#f9f4e8', roughness: 0.9 }); cream.name = '奶油白';
  const blush = new THREE.MeshStandardMaterial({ color: '#dfa99d', roughness: 1 }); blush.name = '脸颊';
  const dark = new THREE.MeshStandardMaterial({ color: '#4c6259', roughness: 0.8 }); dark.name = '嘴巴';
  const sphere = new THREE.SphereGeometry(1, 48, 40);
  function part(name: string, parent: THREE.Object3D, xyz: number[], scale: number[], mat: THREE.Material, region: Region) {
    const mesh = new THREE.Mesh(sphere, mat); mesh.name = name;
    mesh.position.set(xyz[0], xyz[1], xyz[2]); mesh.scale.set(scale[0], scale[1], scale[2]);
    mesh.castShadow = true; mesh.receiveShadow = true; mesh.userData.region = region; parent.add(mesh); return mesh;
  }
  part('Body', root, [0, 1.15, 0], [.65, .79, .48], bodyMaterial, 'body');
  part('LeftFoot', root, [.36, .28, .12], [.32, .25, .43], cream, 'body');
  part('RightFoot', root, [-.36, .28, .12], [.32, .25, .43], cream, 'body');
  part('Bib', root, [0, 1.14, .42], [.43, .5, .12], accentMaterial, 'body');
  const starShape = new THREE.Shape();
  for (let i = 0; i < 10; i++) { const angle = Math.PI / 2 + i * Math.PI / 5; const r = i % 2 ? .066 : .14; const x = Math.cos(angle) * r; const y = Math.sin(angle) * r; if (!i) starShape.moveTo(x, y); else starShape.lineTo(x, y); }
  starShape.closePath();
  const star = new THREE.Mesh(new THREE.ExtrudeGeometry(starShape, { depth: .025, bevelEnabled: true, bevelSize: .008, bevelThickness: .008, bevelSegments: 3, steps: 1 }), cream);
  star.name = 'LittleStar'; star.position.set(0, 1.2, .535); star.userData.region = 'body'; root.add(star);
  const head = new THREE.Group(); head.name = 'HeadPivot'; head.position.set(0, 2.18, 0); root.add(head);
  part('Head', head, [0, 0, 0], [.86, .72, .65], bodyMaterial, 'head');
  const ears = [-1, 1].map((sign) => {
    const ear = new THREE.Group(); ear.name = sign < 0 ? 'RightEarPivot' : 'LeftEarPivot'; ear.position.set(sign * .46, .5, -.02); ear.rotation.z = sign * -.16; head.add(ear);
    part(`${ear.name}Outer`, ear, [0, .42, 0], [.235, .61, .23], bodyMaterial, 'head');
    part(`${ear.name}Inner`, ear, [0, .43, .174], [.123, .43, .075], accentMaterial, 'head'); return ear;
  });
  const eyes = [-1, 1].map(sign => {
    const eye = part(sign < 0 ? 'RightEye' : 'LeftEye', head, [sign * .285, .055, .595], [.059, .09, .035], eyeMaterial, 'head');
    part(`${eye.name}Glint`, eye, [-.19, .26, .7], [.24, .2, .28], cream, 'head'); return eye;
  });
  for (const sign of [-1, 1]) part('Blush', head, [sign * .47, -.14, .53], [.105, .05, .025], blush, 'head');
  part('Nose', head, [0, -.035, .653], [.045, .029, .025], dark, 'head');
  const smileCurve = new THREE.QuadraticBezierCurve3(new THREE.Vector3(-.085, -.16, .644), new THREE.Vector3(0, -.225, .664), new THREE.Vector3(.085, -.16, .644));
  const smile = new THREE.Mesh(new THREE.TubeGeometry(smileCurve, 20, .013, 8, false), dark); smile.name = 'Smile'; smile.userData.region = 'head'; head.add(smile);
  const arms = [-1, 1].map(sign => {
    const arm = new THREE.Group(); arm.name = sign < 0 ? 'RightArmPivot' : 'LeftArmPivot'; arm.position.set(sign * .55, 1.53, 0); arm.rotation.z = sign * .3; root.add(arm);
    part(`${arm.name}Mesh`, arm, [sign * .1, -.3, .025], [.23, .44, .26], bodyMaterial, sign < 0 ? 'right_hand' : 'left_hand'); return arm;
  });
  return { root, head, leftArm: arms[1], rightArm: arms[0], leftEar: ears[1], rightEar: ears[0], eyes, bodyMaterial, accentMaterial, eyeMaterial };
}

export function animateDemo(rig: DemoRig, time: number, action: ActionName, elapsed: number, intensity: number, duration: number) {
  const { root, head, leftArm, rightArm, leftEar, rightEar, eyes } = rig;
  const envelope = action === 'idle' ? 0 : Math.sin(Math.PI * Math.min(elapsed / duration, 1));
  const power = envelope * (.35 + intensity * .65);
  root.position.y = Math.sin(time * 2) * .012;
  root.rotation.set(0, 0, 0); root.scale.setScalar(1);
  head.rotation.set(Math.sin(time * .8) * .015, Math.sin(time * .7) * .035, 0);
  leftArm.rotation.set(0, 0, .3 + Math.sin(time * 1.7) * .035);
  rightArm.rotation.set(0, 0, -.3 - Math.sin(time * 1.7) * .035);
  leftEar.rotation.z = -.16 + Math.sin(time * 1.5) * .025; rightEar.rotation.z = .16 - Math.sin(time * 1.5) * .025;
  const blinkPhase = time % 5.4; const blink = blinkPhase < .15 ? Math.max(.09, Math.abs(blinkPhase - .075) / .075) : 1;
  let eyeScale = blink;
  if (action === 'greet') {
    leftArm.rotation.z += power * (2.15 + Math.sin(elapsed * 13) * .35); root.rotation.z = Math.sin(elapsed * 6) * .06 * power;
  } else if (action === 'enjoy_head_pat') {
    head.rotation.z = -.23 * power; head.rotation.x = -.12 * power; eyeScale = Math.max(.15, 1 - power * .9);
    leftEar.rotation.z -= .2 * power; rightEar.rotation.z += .2 * power;
  } else if (action === 'hug') {
    leftArm.rotation.z = .3 + power * .95; rightArm.rotation.z = -.3 - power * .95;
    leftArm.rotation.x = -power * .7; rightArm.rotation.x = -power * .7; head.rotation.x = .12 * power; eyeScale = Math.max(.2, 1 - power * .8);
  } else if (action === 'react_to_shake') {
    root.rotation.z = Math.sin(elapsed * 16) * .13 * power; head.rotation.z = Math.sin(elapsed * 13 + 1) * .16 * power;
    leftEar.rotation.z -= Math.sin(elapsed * 18) * .15 * power; rightEar.rotation.z -= Math.sin(elapsed * 18) * .15 * power;
  } else if (action === 'listen') { head.rotation.z = .2 * power; head.rotation.x = .13 * power; head.rotation.y = -.1 * power; }
  root.scale.y = 1 + Math.sin(time * 2) * .008;
  for (const eye of eyes) eye.scale.y = .09 * eyeScale;
}
