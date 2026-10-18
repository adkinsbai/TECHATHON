"""语义布局：展区、步道、入口、小屋、树和布景的结构是否合理。"""
import json
import math
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'companion'))
from app.scene_site import CABIN, SPAWN, build_site

BLUEPRINT = Path(__file__).resolve().parents[1] / 'companion/demos/zoo-blueprint.json'


def zoo():
    return json.loads(BLUEPRINT.read_text(encoding='utf-8-sig'))


def in_zone(site, zone, xz):
    r = math.dist(site['center'], xz)
    a = math.atan2(xz[1] - site['center'][1], xz[0] - site['center'][0])
    while a < zone['a0']:
        a += 2 * math.pi
    return zone['r_in'] <= r <= zone['r_out'] and a <= zone['a1']


class SiteTests(unittest.TestCase):
    def setUp(self):
        self.plan = zoo()
        self.site = build_site(self.plan)

    def test_every_root_instance_is_placed_or_hidden(self):
        roots = {n['id'] for n in self.plan['instances'] if not n.get('parent_id')}
        self.assertEqual(roots, set(self.site['placements']) | set(self.site['hidden']))

    def test_each_animal_species_gets_one_fenced_exhibit_and_stands_inside_it(self):
        animals = {a['id'] for a in self.plan['assets'] if a['kind'] == 'animal'}
        exhibits = {z['asset_id']: z for z in self.site['zones'] if z['kind'] == 'exhibit'}
        perched = {n['asset_id'] for n in self.plan['instances'] if n.get('parent_id')}
        self.assertEqual(set(exhibits), animals - perched)
        for node in self.plan['instances']:
            if node['asset_id'] in exhibits and not node.get('parent_id'):
                p = self.site['placements'][node['id']]['position']
                self.assertTrue(in_zone(self.site, exhibits[node['asset_id']], (p[0], p[2])), node['id'])
        self.assertTrue(all(z['fence'] for z in exhibits.values()))

    def test_zones_do_not_overlap_and_sit_outside_the_path(self):
        zones = sorted(self.site['zones'], key=lambda z: z['a0'])
        for a, b in zip(zones, zones[1:]):
            self.assertLess(a['a1'], b['a0'])
        self.assertLess(zones[-1]['a1'], zones[0]['a0'] + 2 * math.pi)
        edge = self.site['radius'] + self.site['path']['width'] / 2
        self.assertTrue(all(z['r_in'] > edge for z in self.site['zones']))

    def test_entrance_faces_spawn_on_the_spur_and_can_be_walked_through(self):
        gate = next(k for k in self.site['placements'] if 'entrance' in k)
        placed = self.site['placements'][gate]
        self.assertEqual(placed['collision_radius'], 0.0)
        self.assertEqual([placed['position'][0], placed['position'][2]], self.site['gate'])
        self.assertAlmostEqual(placed['yaw'], math.atan2(SPAWN[0] - self.site['gate'][0], SPAWN[1] - self.site['gate'][1]), 3)
        # 支路从入口通到环路，中间不穿过任何展区
        (gx, gz), (sx, sz) = self.site['path']['spur']
        for i in range(21):
            xz = (gx + (sx - gx) * i / 20, gz + (sz - gz) * i / 20)
            self.assertFalse(any(in_zone(self.site, z, xz) for z in self.site['zones']), xz)

    def test_every_exhibit_has_a_shelter_and_tigers_face_each_other(self):
        exhibits = [z for z in self.site['zones'] if z['kind'] == 'exhibit']
        shelters = [k for k in self.site['placements'] if 'shelter' in k] + [e['id'] for e in self.site['extra_instances']]
        self.assertEqual(len(shelters), len(exhibits))
        a, b = (self.site['placements'][i] for i in ('tiger_01', 'tiger_02'))
        towards = math.atan2(b['position'][0] - a['position'][0], b['position'][2] - a['position'][2])
        self.assertAlmostEqual(a['yaw'], round(towards, 4), 3)

    def test_props_keep_clear_of_animals_and_layout_avoids_the_cabin(self):
        animals = [p['position'] for k, p in self.site['placements'].items() if any(s in k for s in ('tiger', 'elephant', 'panda', 'gorilla'))]
        for prop in self.site['props']:
            if prop['type'] != 'bench':
                self.assertGreater(min(math.dist((a[0], a[2]), prop['position']) for a in animals), 2.9)
        farthest = max(math.dist(self.site['center'], (p['position'][0], p['position'][2])) for p in self.site['placements'].values())
        self.assertGreater(math.dist(self.site['center'], CABIN), farthest + 5)

    def test_layout_is_deterministic(self):
        self.assertEqual(json.dumps(build_site(zoo())), json.dumps(self.site))

    def test_scene_without_animals_keeps_original_positions(self):
        plan = zoo()
        plan['assets'] = [a for a in plan['assets'] if a['kind'] != 'animal']
        self.assertIsNone(build_site(plan))


if __name__ == '__main__':
    unittest.main()
