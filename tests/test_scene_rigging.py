"""世界工作室：动物用 Tripo 自动绑骨、套动作；任何失败都保留静态模型，不重发付费请求。"""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'companion'))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from app.scene_plan import ScenePlan, world_recipe
from app.scene_assets import SceneStudio, Providers, UnknownSubmission, task_model_urls
from test_scene_studio import FakeProviders, blueprint, empty_glb


class RigProviders(FakeProviders):
    """模拟 Tripo：rig-check 直接返回类型，rig / retarget 各一个任务，retarget 每个动作一个 GLB。"""

    def __init__(self, riggable=True):
        super().__init__()
        self.riggable = riggable
        self.calls = []

    async def rig_check(self, model_task_id):
        self.calls.append(('check', model_task_id))
        return {'riggable': self.riggable, 'rig_type': 'quadruped' if self.riggable else None}

    async def rig_submit(self, model_task_id, rig_type):
        self.calls.append(('rig', model_task_id, rig_type))
        return 'rig-task'

    async def retarget_submit(self, rig_task_id, animations):
        self.calls.append(('retarget', rig_task_id, tuple(animations)))
        return 'anim-task'

    async def tripo_task(self, task_id):
        if task_id == 'anim-task':
            return {'model_urls': [{'animation': 'preset:idle', 'url': 'https://example.com/idle.glb'},
                                   {'animation': 'preset:walk', 'url': 'https://example.com/walk.glb'}]}
        return {'model_url': 'https://example.com/rigged.glb'}

    async def download(self, url):
        if self.model_active:
            self.model_active -= 1
        return empty_glb()


KEYS = {'OPENAI_API_KEY': 'test', 'RODIN_API_KEY': 'test', 'TRIPO_API_KEY': 'test'}


def make_job(studio):
    value = blueprint(3).model_dump(mode='json')
    value['assets'][0]['kind'] = 'animal'
    value['assets'][1]['kind'] = 'animal'
    plan = ScenePlan.model_validate(value)
    job = {'id': 'rig', 'state': 'planned', 'plan': plan.model_dump(mode='json'), 'recipe': world_recipe(plan),
           'assets': {a.id: {'state': 'planned', 'name': a.name} for a in plan.assets}}
    studio.jobs[job['id']] = job
    studio.save(job)
    return job


class RigPipelineTests(unittest.IsolatedAsyncioTestCase):
    async def test_auto_sends_animals_to_tripo_rigs_them_and_keeps_plants_on_rodin(self):
        provider = RigProviders()
        with tempfile.TemporaryDirectory() as tmp:
            studio = SceneStudio(tmp, dict(KEYS), provider)
            job = make_job(studio)
            studio.start(job, provider='auto')
            await studio.tasks['rig']
            assets = job['assets']
            self.assertEqual([assets[f'asset_{i}']['provider'] for i in range(3)], ['tripo', 'tripo', 'rodin'])
            self.assertTrue(all(a['state'] == 'ready' for a in assets.values()))
            rig = assets['asset_0']['rig']
            self.assertEqual((rig['state'], rig['rig_type']), ('ready', 'quadruped'))
            self.assertEqual([c['name'] for c in rig['clips']], ['idle', 'walk'])
            self.assertTrue((Path(tmp) / 'rig/asset_0.clip1.glb').exists())
            self.assertNotIn('rig', assets['asset_2'])
            self.assertIn(('retarget', 'rig-task', ('preset:idle', 'preset:walk')), provider.calls)

    async def test_animation_presets_can_be_configured(self):
        provider = RigProviders()
        with tempfile.TemporaryDirectory() as tmp:
            studio = SceneStudio(tmp, dict(KEYS, TRIPO_ANIMATIONS='preset:run, preset:jump'), provider)
            studio.start(make_job(studio), provider='auto', asset_ids=['asset_0'])
            await studio.tasks['rig']
            self.assertIn(('retarget', 'rig-task', ('preset:run', 'preset:jump')), provider.calls)

    async def test_auto_needs_both_model_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            studio = SceneStudio(tmp, {'OPENAI_API_KEY': 'test', 'RODIN_API_KEY': 'test'}, RigProviders())
            with self.assertRaises(ValueError):
                studio.start(make_job(studio), provider='auto')

    async def test_unriggable_animal_keeps_static_model(self):
        provider = RigProviders(riggable=False)
        with tempfile.TemporaryDirectory() as tmp:
            studio = SceneStudio(tmp, dict(KEYS), provider)
            job = make_job(studio)
            studio.start(job, provider='auto', asset_ids=['asset_0'])
            await studio.tasks['rig']
            record = job['assets']['asset_0']
            self.assertEqual((record['state'], record['rig']['state']), ('ready', 'skipped'))
            self.assertFalse(any(c[0] == 'rig' for c in provider.calls))

    async def test_rig_failure_keeps_static_model_ready(self):
        provider = RigProviders()
        provider.tripo_task = AsyncMock(side_effect=RuntimeError('Tripo 任务失败：failed'))
        with tempfile.TemporaryDirectory() as tmp:
            studio = SceneStudio(tmp, dict(KEYS), provider)
            job = make_job(studio)
            studio.start(job, provider='auto', asset_ids=['asset_0'])
            await studio.tasks['rig']
            record = job['assets']['asset_0']
            self.assertEqual((record['state'], record['rig']['state']), ('ready', 'failed'))
            self.assertIn('静态模型', record['rig']['message'])

    async def test_unknown_rig_submission_is_not_retried_and_model_stays_ready(self):
        provider = RigProviders()
        provider.rig_submit = AsyncMock(side_effect=UnknownSubmission('unknown'))
        with tempfile.TemporaryDirectory() as tmp:
            studio = SceneStudio(tmp, dict(KEYS), provider)
            job = make_job(studio)
            studio.start(job, provider='auto', asset_ids=['asset_0'])
            await studio.tasks['rig']
            record = job['assets']['asset_0']
            self.assertEqual((record['state'], record['rig']['state']), ('ready', 'unknown'))
            restored = SceneStudio(tmp, studio.settings, provider)
            restored.start(restored.get('rig'), provider='auto', asset_ids=['asset_0'])
            await restored.tasks['rig']
            self.assertEqual(provider.rig_submit.await_count, 1)

    async def test_interrupted_rig_resumes_from_saved_task_without_resubmitting(self):
        provider = RigProviders()
        with tempfile.TemporaryDirectory() as tmp:
            studio = SceneStudio(tmp, dict(KEYS), provider)
            job = make_job(studio)
            record = job['assets']['asset_0']
            record.update(state='ready', provider='tripo', upstream={'id': 'model-task'},
                          rig={'state': 'interrupted', 'rig_type': 'quadruped', 'rig_task': 'rig-task'})
            studio.save(job)
            studio.start(job, provider='auto', asset_ids=['asset_0'])
            await studio.tasks['rig']
            self.assertEqual(record['rig']['state'], 'ready')
            self.assertEqual([c[0] for c in provider.calls], ['retarget'])
            self.assertEqual((provider.images, provider.submits), (0, 0))


class TripoProtocolTests(unittest.IsolatedAsyncioTestCase):
    def test_retarget_output_shapes_are_normalized(self):
        self.assertEqual(task_model_urls({'model_url': 'https://a/x.glb'}), [('model', 'https://a/x.glb')])
        self.assertEqual(task_model_urls({'model_urls': {'preset:walk': 'https://a/w.glb'}}), [('preset:walk', 'https://a/w.glb')])
        self.assertEqual(task_model_urls({'model_urls': ['https://a/0.glb']}), [('0', 'https://a/0.glb')])
        self.assertEqual(task_model_urls({}), [])

    async def test_rig_requests_chain_task_ids_and_running_tasks_return_none(self):
        providers = Providers(dict(KEYS))
        providers.request = AsyncMock(side_effect=[
            {'code': 0, 'data': {'riggable': True, 'rig_type': 'quadruped'}},
            {'code': 0, 'data': {'task_id': 'rig-1'}},
            {'code': 0, 'data': {'task_id': 'anim-1'}},
            {'code': 0, 'data': {'status': 'running', 'output': {'model_url': 'https://a/partial.glb'}}},
            {'code': 0, 'data': {'status': 'success', 'output': {'model_url': 'https://a/done.glb'}}}])
        self.assertEqual(await providers.rig_check('gen-1'), {'riggable': True, 'rig_type': 'quadruped'})
        self.assertEqual(await providers.rig_submit('gen-1', 'quadruped'), 'rig-1')
        self.assertEqual(providers.request.call_args.kwargs['body'],
                         {'input': 'gen-1', 'rig_type': 'quadruped', 'spec': 'tripo', 'out_format': 'glb'})
        self.assertEqual(await providers.retarget_submit('rig-1', ['preset:idle']), 'anim-1')
        self.assertEqual(providers.request.call_args.args[1], '/animations/retarget')
        self.assertIsNone(await providers.tripo_task('anim-1'))
        self.assertEqual(await providers.tripo_task('anim-1'), {'model_url': 'https://a/done.glb'})


if __name__ == '__main__':
    unittest.main()


class DownloadAddressTests(unittest.TestCase):
    def test_proxy_fake_ip_range_is_allowed_but_private_networks_are_not(self):
        from app.scene_assets import download_address_allowed
        self.assertTrue(download_address_allowed('198.18.0.25'))
        self.assertTrue(download_address_allowed('198.19.255.1'))
        self.assertTrue(download_address_allowed('8.8.8.8'))
        for address in ('127.0.0.1', '10.0.0.5', '192.168.137.1', '172.16.0.1', '169.254.1.1', '100.64.0.1', '::1'):
            self.assertFalse(download_address_allowed(address), address)
