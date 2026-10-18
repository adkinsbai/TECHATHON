// 语义布局的场地：步道、小广场、展区地面、围栏、指示牌和小布景。数据来自后端 scene_site.py。
// 都用绘本卡通材质并加描边，和生成的模型、噜噜同一套风格。
import * as THREE from 'three';
import {toonify} from '/static/toonify.js?v=5';

const GROUND_COLORS = {
  mud: '#b98d5f', rock: '#cbbfa9', savanna: '#e3cf8f',
  bamboo: '#9fca78', jungle: '#88bd6c', garden: '#b6e09a', meadow: '#a9d887',
};
const BARE = new Set(['mud', 'rock', 'savanna']);   // 这些地面上不长草
const PAVING = '#ecdcbc', PLAZA = '#f3e6c8', WOOD = '#b98055', WOOD_DARK = '#8f5e3c';

const mat = (color) => new THREE.MeshStandardMaterial({color, roughness: .9});
const angleIn = (a, a0, a1) => { let t = a; while (t < a0) t += Math.PI * 2; return t <= a1; };

export function createSite(site) {
  const [cx, cz] = site.center, R = site.radius, W = site.path.width;
  const [gx, gz] = site.gate, [sx, sz] = site.path.spur[1];
  const spurLen = Math.hypot(sx - gx, sz - gz);
  const distToSpur = (x, z) => {
    const t = Math.max(0, Math.min(1, ((x - gx) * (sx - gx) + (z - gz) * (sz - gz)) / (spurLen * spurLen)));
    return Math.hypot(x - (gx + (sx - gx) * t), z - (gz + (sz - gz) * t));
  };
  const zoneAt = (x, z) => {
    const r = Math.hypot(x - cx, z - cz), a = Math.atan2(z - cz, x - cx);
    return site.zones.find((zone) => r >= zone.r_in && r <= zone.r_out && angleIn(a, zone.a0, zone.a1)) || null;
  };
  const onPath = (x, z) => Math.abs(Math.hypot(x - cx, z - cz) - R) < W / 2 + .3 || distToSpur(x, z) < W / 2 + .3
    || Math.hypot(x - cx, z - cz) < site.plaza.radius + .3;
  const pathPoints = [...site.path.loop, ...site.path.spur].map(([x, z]) => new THREE.Vector3(x, 0, z));

  function build({scene, heightAt, colliders}) {
    const group = new THREE.Group();
    group.name = 'semantic-site';
    const lift = (x, z, dy) => heightAt(x, z) + dy;

    // 一块贴地的扇环（展区地面 / 环形步道），按网格采样地形高度。
    const sector = (r0, r1, a0, a1, color, dy, radial = 6, around = 48) => {
      const pos = [], idx = [];
      for (let i = 0; i <= radial; i++) for (let j = 0; j <= around; j++) {
        const r = r0 + (r1 - r0) * i / radial, a = a0 + (a1 - a0) * j / around;
        const x = cx + Math.cos(a) * r, z = cz + Math.sin(a) * r;
        pos.push(x, lift(x, z, dy), z);
      }
      for (let i = 0; i < radial; i++) for (let j = 0; j < around; j++) {
        const p = i * (around + 1) + j;
        idx.push(p, p + 1, p + around + 1, p + 1, p + around + 2, p + around + 1);
      }
      const g = new THREE.BufferGeometry();
      g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
      g.setIndex(idx); g.computeVertexNormals();
      const mesh = new THREE.Mesh(g, mat(color));
      mesh.receiveShadow = true; mesh.userData.flat = true;
      group.add(mesh);
      return mesh;
    };
    // 环形步道、小广场、入口支路
    sector(R - W / 2, R + W / 2, 0, Math.PI * 2, PAVING, .06, 2, 120);
    sector(0, site.plaza.radius, 0, Math.PI * 2, PLAZA, .07, 4, 64);
    {
      const steps = Math.ceil(spurLen / 1.5), pos = [], idx = [];
      const nx = -(sz - gz) / spurLen, nz = (sx - gx) / spurLen;
      for (let i = 0; i <= steps; i++) {
        const t = i / steps, x = gx + (sx - gx) * t, z = gz + (sz - gz) * t;
        for (const s of [-1, 1]) { const px = x + nx * s * W / 2, pz = z + nz * s * W / 2; pos.push(px, lift(px, pz, .06), pz); }
      }
      for (let i = 0; i < steps; i++) { const p = i * 2; idx.push(p, p + 1, p + 2, p + 1, p + 3, p + 2); }
      const g = new THREE.BufferGeometry();
      g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3)); g.setIndex(idx); g.computeVertexNormals();
      const spur = new THREE.Mesh(g, mat(PAVING)); spur.receiveShadow = true; spur.userData.flat = true; group.add(spur);
    }

    // 展区地面
    for (const zone of site.zones) sector(zone.r_in, zone.r_out, zone.a0, zone.a1, GROUND_COLORS[zone.ground] || GROUND_COLORS.meadow, .045);

    // 围栏：沿展区四周，每 1.6 米一根柱子、两道横杆；柱子同时是碰撞体，游客进不去。
    const fence = new THREE.Group();
    const postGeo = new THREE.CylinderGeometry(.09, .11, 1.15, 6), railGeo = new THREE.BoxGeometry(1, .09, .07);
    const postMat = mat(WOOD), railMat = mat(WOOD_DARK);
    const addPost = (x, z) => {
      const p = new THREE.Mesh(postGeo, postMat); p.position.set(x, lift(x, z, .57), z); fence.add(p);
      colliders.push({x, z, r: .55});
    };
    const addRail = (x0, z0, x1, z1) => {
      const len = Math.hypot(x1 - x0, z1 - z0);
      for (const h of [.45, .9]) {
        const r = new THREE.Mesh(railGeo, railMat);
        r.scale.x = len; r.position.set((x0 + x1) / 2, (lift(x0, z0, h) + lift(x1, z1, h)) / 2, (z0 + z1) / 2);
        r.rotation.y = -Math.atan2(z1 - z0, x1 - x0); fence.add(r);
      }
    };
    for (const zone of site.zones.filter((z) => z.fence)) {
      const outline = [];
      const arc = (r, a0, a1) => { const n = Math.max(2, Math.ceil(Math.abs(a1 - a0) * r / 1.6)); for (let i = 0; i <= n; i++) { const a = a0 + (a1 - a0) * i / n; outline.push([cx + Math.cos(a) * r, cz + Math.sin(a) * r]); } };
      const side = (a, r0, r1) => { const n = Math.max(1, Math.ceil((r1 - r0) / 1.6)); for (let i = 1; i < n; i++) { const r = r0 + (r1 - r0) * i / n; outline.push([cx + Math.cos(a) * r, cz + Math.sin(a) * r]); } };
      arc(zone.r_in, zone.a0, zone.a1); side(zone.a1, zone.r_in, zone.r_out);
      arc(zone.r_out, zone.a1, zone.a0); side(zone.a0, zone.r_out, zone.r_in);
      outline.forEach(([x, z], i) => { addPost(x, z); const [x1, z1] = outline[(i + 1) % outline.length]; addRail(x, z, x1, z1); });
    }
    group.add(fence);

    // 指示牌：立在展区面向步道的一侧
    for (const zone of site.zones) {
      const [x, z] = zone.sign.position, sign = new THREE.Group();
      const post = new THREE.Mesh(new THREE.CylinderGeometry(.07, .08, 1.6, 6), mat(WOOD_DARK)); post.position.y = .8; sign.add(post);
      const c = document.createElement('canvas'); c.width = 384; c.height = 128;
      const g = c.getContext('2d');
      g.fillStyle = '#fff6e4'; g.beginPath(); g.roundRect(6, 6, 372, 116, 26); g.fill();
      g.strokeStyle = '#8f5e3c'; g.lineWidth = 8; g.stroke();
      g.fillStyle = '#6b4632'; g.font = "bold 50px 'LXGW WenKai Screen','Microsoft YaHei'"; g.textAlign = 'center'; g.textBaseline = 'middle';
      g.fillText(zone.sign.text, 192, 66);
      const tex = new THREE.CanvasTexture(c); tex.colorSpace = THREE.SRGBColorSpace;
      const board = new THREE.Mesh(new THREE.BoxGeometry(1.8, .6, .08), [mat(WOOD), mat(WOOD), mat(WOOD), mat(WOOD), Object.assign(new THREE.MeshStandardMaterial({map: tex, roughness: .9}), {userData: {keepTexture: true}}), mat(WOOD)]);
      board.position.y = 1.75; sign.add(board);
      sign.position.set(x, heightAt(x, z), z); sign.rotation.y = zone.sign.yaw;
      group.add(sign);
    }

    // 小布景
    const propBuilders = {
      rock: (s) => { const m = new THREE.Mesh(new THREE.DodecahedronGeometry(.6 * s, 0), mat('#b9b1a6')); m.position.y = .35 * s; m.scale.y = .7; m.rotation.y = s * 7; return [m, .6 * s]; },
      bush: (s) => { const g = new THREE.Group(); for (let i = 0; i < 3; i++) { const b = new THREE.Mesh(new THREE.IcosahedronGeometry(.55 * s * (1 - i * .15), 1), mat('#6fae5c')); b.position.set((i - 1) * .45 * s, .45 * s, (i % 2) * .3 * s); g.add(b); } return [g, .8 * s]; },
      bamboo: (s) => { const g = new THREE.Group(); for (let i = 0; i < 6; i++) { const h = (3 + (i % 3)) * s, c = new THREE.Mesh(new THREE.CylinderGeometry(.06, .07, h, 6), mat(i % 2 ? '#8fc46a' : '#a6d27c')); c.position.set(Math.cos(i * 2.4) * .4, h / 2, Math.sin(i * 2.4) * .4); g.add(c); for (let k = 0; k < 3; k++) { const leaf = new THREE.Mesh(new THREE.IcosahedronGeometry(.28, 0), mat(k % 2 ? '#7fbf5e' : '#94cc6e')); leaf.scale.set(1.4, .45, .8); leaf.position.set(c.position.x + Math.cos(k * 2.1 + i) * .3, h - .2 - k * .45, c.position.z + Math.sin(k * 2.1 + i) * .3); leaf.rotation.y = k * 2.1 + i; g.add(leaf); } } return [g, .5]; },
      pool: (s) => { const g = new THREE.Group(); const w = new THREE.Mesh(new THREE.CircleGeometry(s, 24).rotateX(-Math.PI / 2), new THREE.MeshStandardMaterial({color: '#8fd0e8', roughness: .3})); w.position.y = .08; g.add(w); for (let i = 0; i < 10; i++) { const a = i / 10 * Math.PI * 2, r = new THREE.Mesh(new THREE.DodecahedronGeometry(.35, 0), mat('#c9bfae')); r.position.set(Math.cos(a) * s, .15, Math.sin(a) * s); g.add(r); } return [g, 0]; },
      log: (s) => { const m = new THREE.Mesh(new THREE.CylinderGeometry(.28, .32, 2.4 * s, 8), mat(WOOD)); m.rotation.z = Math.PI / 2; m.position.y = .3; return [m, .9]; },
      flowerbed: (s) => { const g = new THREE.Group(); const mound = new THREE.Mesh(new THREE.SphereGeometry(.9 * s, 12, 6, 0, Math.PI * 2, 0, Math.PI / 2), mat('#7fbf5e')); mound.scale.y = .35; g.add(mound); const cols = ['#ffb3c7', '#ffe08a', '#ffffff', '#c9b3ff']; for (let i = 0; i < 9; i++) { const f = new THREE.Mesh(new THREE.SphereGeometry(.12, 8, 6), mat(cols[i % cols.length])); const a = i * 2.3, r = .25 + (i % 3) * .22; f.position.set(Math.cos(a) * r * s, .32, Math.sin(a) * r * s); g.add(f); } return [g, 0]; },
      bench: () => { const g = new THREE.Group(); const seat = new THREE.Mesh(new THREE.BoxGeometry(1.6, .1, .45), mat(WOOD)); seat.position.y = .45; g.add(seat); const back = new THREE.Mesh(new THREE.BoxGeometry(1.6, .45, .08), mat(WOOD)); back.position.set(0, .75, -.2); g.add(back); for (const x of [-.65, .65]) { const leg = new THREE.Mesh(new THREE.BoxGeometry(.1, .45, .4), mat(WOOD_DARK)); leg.position.set(x, .22, 0); g.add(leg); } return [g, .7]; },
    };
    for (const prop of site.props) {
      const make = propBuilders[prop.type];
      if (!make) continue;
      const [x, z] = prop.position, [obj, radius] = make(prop.scale || 1);
      const holder = new THREE.Group(); holder.add(obj);
      holder.position.set(x, heightAt(x, z), z); holder.rotation.y = prop.yaw ?? (x * 13.7 + z) % 6.28;
      group.add(holder);
      if (radius > 0) colliders.push({x, z, r: radius});
    }

    // 统一卡通化（地面和路面平铺，不加描边；其余加描边）
    const flat = [], rest = [];
    group.children.forEach((c) => (c.userData.flat ? flat : rest).push(c));
    flat.forEach((m) => toonify(m, {heightM: 1, outline: false}));
    rest.forEach((c) => toonify(c, {heightM: 1}));
    group.traverse((o) => { if (o.isMesh && !o.userData.flat) o.castShadow = true; });
    scene.add(group);
    return group;
  }

  return {
    data: site, pathPoints, zoneAt, onPath,
    // 草和花不长在步道、广场和泥地 / 碎石地上
    bare: (x, z) => onPath(x, z) || BARE.has(zoneAt(x, z)?.ground),
    build,
  };
}
