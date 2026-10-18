"""语义布局：从场景规划推导出“有结构的场地”，代替规划模型直接给的零散坐标。

不调用模型、结果确定：同一份规划每次得到同一个布局，已生成的模型直接复用。
动物园的结构：入口门楼 → 支路 → 环形步道（中间是有休息亭的小广场）；
每种动物一个围栏展区，排在环路外侧、动物面朝步道、动物小屋在展区后侧；
停栖在树上的鸟单独一个花园；树做外圈树带和展区之间的隔离。
世界坐标：米，x 向右、z 向前；出生点固定在 (22, 70)。
"""
import math
import random
import re

SPAWN = (22.0, 70.0)
CABIN = (-24.0, -16.0)          # 噜噜的小木屋，布局要避开
PATH_WIDTH = 3.6
GAP = 4.0                       # 相邻展区之间留出的弧长（米），种隔离树

ROLE_PATTERNS = {
    'entrance': r'entrance|gate|入口|大门|门楼',
    'shelter': r'shelter|house|hut|barn|棚|舍|小屋|庇护|窝',
    'pavilion': r'pavilion|rest|kiosk|gazebo|亭|休息|长椅',
}
GROUNDS = [  # (物种关键词, 地面类型)
    (r'elephant|rhino|hippo|象|犀|河马', 'mud'),
    (r'panda|熊猫|bamboo', 'bamboo'),
    (r'tiger|lion|leopard|cheetah|虎|狮|豹', 'rock'),
    (r'gorilla|monkey|ape|chimp|orangutan|猩|猴|猿', 'jungle'),
    (r'giraffe|zebra|deer|antelope|鹿|斑马|长颈', 'savanna'),
    (r'penguin|seal|bear|企鹅|海豹|熊', 'rock'),
]


def _text(asset):
    return f"{asset['id']} {asset.get('name', '')}".lower()


def _role(asset):
    if asset['kind'] == 'plant':
        return 'tree'
    if asset['kind'] == 'animal':
        return 'animal'
    for role, pattern in ROLE_PATTERNS.items():
        if re.search(pattern, _text(asset)):
            return role
    return 'structure'


def _ground(asset):
    for pattern, ground in GROUNDS:
        if re.search(pattern, _text(asset)):
            return ground
    return 'meadow'


def _polar(center, radius, angle):
    return [round(center[0] + math.cos(angle) * radius, 2), round(center[1] + math.sin(angle) * radius, 2)]


def _facing(frm, to):
    """模型正面朝 +z；返回让它面向 to 的绕 y 旋转。"""
    return round(math.atan2(to[0] - frm[0], to[1] - frm[1]), 4)


def build_site(plan):
    """plan：ScenePlan 的 dict 形式。没有动物时返回 None（沿用原来的摆放）。"""
    assets = {a['id']: a for a in plan.get('assets', [])}
    instances = plan.get('instances', [])
    roles = {aid: _role(a) for aid, a in assets.items()}
    roots = [n for n in instances if not n.get('parent_id')]
    animals = [aid for aid in assets if roles[aid] == 'animal']
    if not animals:
        return None
    rng = random.Random(plan.get('title', '') + str(len(instances)))

    # 停栖关系：鸟和它的树组成“鸟园”，不进围栏展区。
    perched = {}
    for rel in plan.get('relations', []):
        if rel.get('kind') == 'perched_on' and len(rel.get('subjects', [])) == 2:
            perched[rel['subjects'][1]] = rel['subjects'][0]
    child_assets = {n['asset_id'] for n in instances if n.get('parent_id')}
    exhibit_assets = [aid for aid in animals if any(n['asset_id'] == aid for n in roots)]
    fights = [r['subjects'] for r in plan.get('relations', []) if r.get('kind') == 'fighting']

    # ---------- 展区尺寸 ----------
    zones = []
    for aid in exhibit_assets:
        a = assets[aid]
        count = sum(n['asset_id'] == aid for n in roots)
        h = float(a.get('height_m', 1.5))
        depth = min(18.0, max(10.0, 8 + h * 3.5))
        width = min(24.0, max(12.0, 10 + h * 3) + (count - 1) * 3.5)
        zones.append({'id': 'exhibit_' + aid, 'asset_id': aid, 'name': a.get('name', aid) + '展区',
                      'kind': 'exhibit', 'ground': _ground(a), 'fence': True, 'depth': depth, 'width': width})
    perch_trees = [n for n in roots if n['id'] in perched]
    if perch_trees:
        bird = assets.get(next((n['asset_id'] for n in instances if n['id'] in perched.values()), ''), {})
        zones.append({'id': 'garden_birds', 'asset_id': None, 'name': (bird.get('name') or '小鸟') + '花园',
                      'kind': 'garden', 'ground': 'garden', 'fence': False, 'depth': 10.0, 'width': 12.0})

    # ---------- 环路半径与圆心 ----------
    spur_gap = PATH_WIDTH + 8.0
    need = sum(z['width'] for z in zones) + GAP * len(zones) + spur_gap
    max_depth = max(z['depth'] for z in zones)
    radius = max(16.0, need / (2 * math.pi) - (PATH_WIDTH / 2 + 0.8) - max_depth / 2)
    r_in = radius + PATH_WIDTH / 2 + 0.8
    gate = (SPAWN[0], SPAWN[1] - 9.0)
    center = (SPAWN[0] + 4.0, gate[1] - (max_depth + 7.0) - radius)
    spur_angle = math.atan2(gate[1] - center[1], gate[0] - center[0])

    # ---------- 沿环路分配角度：从支路右侧开始顺序排，留出支路缺口 ----------
    angle = spur_angle + (spur_gap / 2) / (r_in + 4)
    for z in zones:
        mid_r = r_in + z['depth'] / 2
        span = z['width'] / mid_r
        z.update(a0=round(angle, 4), a1=round(angle + span, 4), r_in=round(r_in, 2), r_out=round(r_in + z['depth'], 2))
        z['mid'] = angle + span / 2
        angle += span + GAP / mid_r
    # 剩余的角度均匀分给各个缺口，看起来不会一边挤一边空
    slack = (spur_angle + 2 * math.pi - (spur_gap / 2) / (r_in + 4)) - angle
    if slack > 0:
        for i, z in enumerate(zones):
            shift = slack * (i + 0.5) / len(zones)
            z['a0'] = round(z['a0'] + shift, 4); z['a1'] = round(z['a1'] + shift, 4); z['mid'] += shift

    placements, extra, props, hidden = {}, [], [], []

    def place(node_id, xz, yaw):
        placements[node_id] = {'position': [xz[0], 0.0, xz[1]], 'yaw': yaw}

    # ---------- 动物：展区中前部，面朝环路圆心（也就是游客） ----------
    for z in zones:
        mid, inner = z['mid'], z['r_in']
        # 指示牌立在展区正面靠一侧，不挡住看动物的视线
        sign_xz = _polar(center, inner - 0.5, z['a0'] + (z['a1'] - z['a0']) * 0.16)
        z['sign'] = {'position': sign_xz, 'yaw': _facing(sign_xz, center), 'text': z['name']}
        if z['kind'] != 'exhibit':
            continue
        members = [n for n in roots if n['asset_id'] == z['asset_id']]
        spot_r = inner + z['depth'] * 0.3   # 靠前一些，站在步道上看得清
        tangent_step = 3.0 / spot_r
        for i, node in enumerate(members):
            offset = (i - (len(members) - 1) / 2) * tangent_step
            xz = _polar(center, spot_r, mid + offset)
            place(node['id'], xz, _facing(xz, center))
        # 打斗的一对：相向站立
        for pair in fights:
            if all(any(m['id'] == p for m in members) for p in pair):
                a, b = (placements[p]['position'] for p in pair)
                placements[pair[0]]['yaw'] = _facing((a[0], a[2]), (b[0], b[2]))
                placements[pair[1]]['yaw'] = _facing((b[0], b[2]), (a[0], a[2]))

    # ---------- 小屋：每个展区一间，放在后侧偏一边；规划里只有一间时其余复制 ----------
    shelter_assets = [aid for aid in assets if roles[aid] == 'shelter']
    if shelter_assets:
        sid = shelter_assets[0]
        originals = [n for n in roots if n['asset_id'] == sid]
        for i, z in enumerate(zs for zs in zones if zs['kind'] == 'exhibit'):
            back = z['r_out'] - 3.0
            xz = _polar(center, back, z['mid'] + (z['a1'] - z['a0']) * 0.28)
            yaw = _facing(xz, center)
            if i < len(originals):
                place(originals[i]['id'], xz, yaw)
            else:
                extra.append({'id': f'{sid}__{z["id"]}', 'asset_id': sid, 'position': [xz[0], 0.0, xz[1]],
                              'yaw': yaw, 'scale': 1.0, 'parent_id': None})
        for node in originals[len([z for z in zones if z['kind'] == 'exhibit']):]:
            hidden.append(node['id'])   # 比展区多出来的小屋不摆

    # ---------- 入口、休息亭和其他建筑 ----------
    for aid, role in roles.items():
        nodes = [n for n in roots if n['asset_id'] == aid]
        if role == 'entrance':
            for node in nodes[:1]:
                place(node['id'], [gate[0], gate[1]], _facing(gate, SPAWN))
                placements[node['id']]['collision_radius'] = 0.0   # 门洞可以穿过去
        elif role == 'pavilion':
            for i, node in enumerate(nodes):
                xz = list(center) if i == 0 else _polar(center, 6.0, i * 2.1)
                place(node['id'], xz, _facing(xz, gate))
        elif role == 'structure':
            for i, node in enumerate(nodes):
                xz = _polar(center, radius - PATH_WIDTH - 4.0, spur_angle + math.pi + (i - len(nodes) / 2) * 0.6)
                place(node['id'], xz, _facing(xz, center))

    # ---------- 树：鸟园的停栖树 → 展区之间的隔离树 → 外圈树带 ----------
    trees = [n for n in roots if roles.get(n['asset_id']) == 'tree' and n['id'] not in placements]
    garden = next((z for z in zones if z['kind'] == 'garden'), None)
    for node in perch_trees:
        if garden:
            xz = _polar(center, garden['r_in'] + 3.5, garden['mid'])
            place(node['id'], xz, round(rng.uniform(0, 6.28), 3))
            trees = [t for t in trees if t['id'] != node['id']]
    slots = []
    ordered = sorted(zones, key=lambda z: z['a0'])
    for i, z in enumerate(ordered):
        nxt = ordered[(i + 1) % len(ordered)]
        if i + 1 < len(ordered):
            gap_angle = (z['a1'] + nxt['a0']) / 2
            slots.append(_polar(center, (z['r_in'] + z['r_out']) / 2 + 1.0, gap_angle))
    belt_r = r_in + max_depth + 5.0
    belt_gap = (spur_gap + 6) / belt_r
    remaining = max(0, len(trees) - len(slots))
    for k in range(remaining):
        a = spur_angle + belt_gap / 2 + (2 * math.pi - belt_gap) * (k + 0.5) / max(1, remaining)
        slots.append(_polar(center, belt_r + rng.uniform(-1.5, 2.5), a))
    for node, xz in zip(trees, slots):
        place(node['id'], xz, round(rng.uniform(0, 6.28), 3))

    # ---------- 展区里的布景（程序生成的小物件，不花钱） ----------
    occupied = ([(p['position'][0], p['position'][2]) for p in placements.values()]
                + [(e['position'][0], e['position'][2]) for e in extra])
    for z in zones:
        a0, a1, ri, ro = z['a0'], z['a1'], z['r_in'], z['r_out']
        def spot(fr=(0.15, 0.85), fa=(0.1, 0.9)):
            # 布景避开动物、小屋和停栖树（3 米内不放），也避开已经放下的布景（1.5 米）。
            best = None
            for _ in range(40):
                xz = _polar(center, ri + (ro - ri) * rng.uniform(*fr), a0 + (a1 - a0) * rng.uniform(*fa))
                clear = min([math.dist(xz, o) - 3.0 for o in occupied] + [math.dist(xz, q['position']) - 1.5 for q in props] + [99])
                if best is None or clear > best[0]:
                    best = (clear, xz)
                if clear > 0:
                    break
            return best[1]
        ground = z['ground']
        if ground == 'rock':
            props += [{'type': 'rock', 'position': spot(), 'scale': round(rng.uniform(0.8, 1.8), 2)} for _ in range(6)]
        elif ground == 'bamboo':
            props += [{'type': 'bamboo', 'position': spot((0.55, 0.95)), 'scale': round(rng.uniform(0.9, 1.3), 2)} for _ in range(7)]
        elif ground == 'mud':
            props.append({'type': 'pool', 'position': spot((0.6, 0.75), (0.6, 0.8)), 'scale': 2.6})
            props += [{'type': 'rock', 'position': spot((0.7, 0.95)), 'scale': round(rng.uniform(0.6, 1.1), 2)} for _ in range(3)]
        elif ground == 'jungle':
            props += [{'type': 'log', 'position': spot(), 'yaw': round(rng.uniform(0, 3.14), 2), 'scale': 1.0} for _ in range(2)]
            props += [{'type': 'bush', 'position': spot((0.6, 0.95)), 'scale': round(rng.uniform(0.8, 1.3), 2)} for _ in range(5)]
        elif ground == 'garden':
            props += [{'type': 'flowerbed', 'position': spot((0.1, 0.9)), 'scale': round(rng.uniform(0.8, 1.2), 2)} for _ in range(5)]
        else:
            props += [{'type': 'bush', 'position': spot((0.6, 0.95)), 'scale': round(rng.uniform(0.8, 1.2), 2)} for _ in range(4)]
    for k in range(6):   # 小广场四周的长椅，面朝中心
        xz = _polar(center, 7.5, spur_angle + math.pi / 6 + k * math.pi / 3)
        props.append({'type': 'bench', 'position': xz, 'yaw': _facing(xz, center), 'scale': 1.0})

    for z in zones:
        z.pop('mid', None)
    path_pts = [_polar(center, radius, spur_angle + 2 * math.pi * k / 72) for k in range(72)]
    return {
        'version': 1, 'kind': 'zoo', 'center': [round(center[0], 2), round(center[1], 2)],
        'spawn': list(SPAWN), 'gate': list(gate), 'radius': round(radius, 2),
        'path': {'loop': path_pts, 'spur': [list(gate), _polar(center, radius, spur_angle)], 'width': PATH_WIDTH},
        'plaza': {'radius': 9.0},
        'zones': zones, 'placements': placements, 'extra_instances': extra, 'hidden': hidden, 'props': props,
    }
