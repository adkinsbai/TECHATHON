"""仓库自带的“由对话生成的世界”示例：完整、只读、不含私密字段，别人克隆后不需要密钥就能进入。"""
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'companion'))
from app.scene_assets import SceneStudio, validate_glb
from app.scene_plan import ScenePlan

DEMOS = ROOT / 'companion' / 'demos' / 'scenes'


class DemoSceneTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.studio = SceneStudio(self.tmp.name, settings={}, providers=object(), demo_directory=DEMOS)
        self.job = self.studio.get('demo-zoo')

    def tearDown(self):
        self.tmp.cleanup()

    def test_zoo_demo_is_complete_with_conversation_plan_and_models(self):
        ScenePlan.model_validate(self.job['plan'])
        self.assertEqual(len(self.job['conversation']), 3)
        self.assertIn('老虎', self.job['conversation'][-1])
        public = self.studio.public(self.job)
        self.assertTrue(public['demo'])
        self.assertEqual(public['ready_count'], public['asset_count'])
        self.assertEqual(public['world_url'], '/world?scene=demo-zoo')
        self.assertEqual(public['site']['kind'], 'zoo')
        folder = self.studio.folder('demo-zoo')
        for asset_id, record in self.job['assets'].items():
            self.assertEqual(record['model_url'], f'/api/scene-studio/demo-zoo/assets/{asset_id}/model')
            validate_glb((folder / f'{asset_id}.glb').read_bytes())

    def test_demo_has_no_provider_tokens_or_download_urls(self):
        text = (DEMOS / 'zoo' / 'job.json').read_text(encoding='utf-8')
        for private in ('upstream', 'subscription', 'download_url', 'signature', 'Bearer'):
            self.assertNotIn(private, text)

    def test_demo_is_read_only(self):
        with self.assertRaises(ValueError):
            self.studio.start(self.job, provider='rodin')
        with self.assertRaises(ValueError):
            self.studio.revise(self.job, '再加一只长颈鹿', [])
        before = (DEMOS / 'zoo' / 'job.json').stat().st_mtime_ns
        self.studio.save(self.job)
        self.assertEqual((DEMOS / 'zoo' / 'job.json').stat().st_mtime_ns, before)
        self.assertFalse((Path(self.tmp.name) / 'demo-zoo').exists())

    def test_own_scene_with_the_same_id_is_not_replaced_by_a_demo(self):
        own = Path(self.tmp.name) / 'demo-zoo'
        own.mkdir()
        (own / 'job.json').write_text(json.dumps({'id': 'demo-zoo', 'state': 'planned', 'assets': {}}), encoding='utf-8')
        studio = SceneStudio(self.tmp.name, settings={}, providers=object(), demo_directory=DEMOS)
        self.assertFalse(studio.get('demo-zoo').get('demo'))
        self.assertEqual(studio.folder('demo-zoo'), own)


if __name__ == '__main__':
    unittest.main()
