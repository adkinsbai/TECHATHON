import asyncio
import base64
import copy
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'companion'))
from app.scene_plan import ScenePlan, plan_conversation, world_recipe, enforce_layout, ZOO_CONVERSATION
from app.scene_assets import SceneStudio, Providers, UnknownSubmission, validate_glb


def blueprint(count=6):
    return ScenePlan.model_validate({
        'schema_version': '1.0', 'title': '场景', 'summary': '来自对话', 'style': 'naturalistic PBR',
        'quotes': ['许多树和动物'], 'layout_notes': '留出走道', 'relations': [],
        'assets': [{'id': f'asset_{i}', 'name': f'资产{i}', 'kind': 'plant',
                    'description': '一棵自然的树', 'image_prompt': 'One isolated realistic tree',
                    'height_m': 4, 'collision_radius_m': .5, 'source_quotes': [0]} for i in range(count)],
        'instances': [{'id': f'node_{i}', 'asset_id': f'asset_{i}', 'position': [i * 4, 0, 20]}
                      for i in range(count)]})


def empty_glb():
    payload = json.dumps({'asset': {'version': '2.0'}, 'scenes': [{}], 'scene': 0}).encode()
    payload += b' ' * (-len(payload) % 4)
    return b'glTF' + struct.pack('<IIII', 2, 20 + len(payload), len(payload), 0x4e4f534a) + payload


class GraphTests(unittest.TestCase):
    def test_actual_zoo_plan_has_one_small_parrot_two_tigers_and_architecture(self):
        path = Path(__file__).resolve().parents[1] / 'companion/demos/zoo-blueprint.json'
        plan = ScenePlan.model_validate_json(path.read_text(encoding='utf-8-sig'))
        self.assertEqual(plan.quotes, ZOO_CONVERSATION)
        counts = {a.id: sum(n.asset_id == a.id for n in plan.instances) for a in plan.assets}
        self.assertEqual(counts['parrot'], 1)
        self.assertEqual(counts['tiger'], 2)
        self.assertGreaterEqual(counts['tree'], 18)
        self.assertEqual({a.id for a in plan.assets if a.kind == 'structure'},
                         {'entrance_gate', 'rest_pavilion', 'animal_shelter'})
        bird = next(a for a in plan.assets if a.id == 'parrot')
        self.assertLessEqual(bird.height_m, .8)
        self.assertIsNotNone(next(n for n in plan.instances if n.asset_id == 'parrot').parent_id)

    def test_spawn_clearance_keeps_buildings_outside_initial_camera(self):
        value = blueprint(1).model_dump(mode='json')
        value['assets'][0]['kind'] = 'structure'
        value['instances'][0]['position'] = [22, 0, 68]
        plan = enforce_layout(ScenePlan.model_validate(value))
        x, _, z = plan.instances[0].position
        self.assertGreater((x - 22)**2 + (z - 70)**2, 12**2)

    def test_structure_is_moved_off_the_visitor_path(self):
        value = blueprint(1).model_dump(mode='json')
        value['assets'][0].update(kind='structure', collision_radius_m=3)
        value['instances'][0]['position'] = [8, 0, 44]
        plan = enforce_layout(ScenePlan.model_validate(value))
        x, _, z = plan.instances[0].position
        self.assertGreaterEqual((x - 8)**2 + (z - 44)**2, 5.9**2)

    def test_rejects_missing_assets_cycles_and_invalid_evidence(self):
        original = blueprint(2).model_dump(mode='json')
        for change in ('missing', 'cycle', 'quote'):
            value = copy.deepcopy(original)
            if change == 'missing':
                value['instances'][0]['asset_id'] = 'unknown'
            elif change == 'cycle':
                value['instances'][0]['parent_id'] = 'node_1'
                value['instances'][1]['parent_id'] = 'node_0'
            else:
                value['assets'][0]['source_quotes'] = [12]
            with self.assertRaises(ValidationError):
                ScenePlan.model_validate(value)

    def test_perched_relation_requires_matching_parent_and_distinct_subjects(self):
        plan = blueprint(2).model_dump(mode='json')
        plan['relations'] = [{'kind': 'perched_on', 'subjects': ['node_0', 'node_1'], 'description': '停在树上'}]
        with self.assertRaises(ValidationError):
            ScenePlan.model_validate(plan)
        plan['instances'][0]['parent_id'] = 'node_1'
        self.assertEqual(ScenePlan.model_validate(plan).instances[0].parent_id, 'node_1')

    def test_glb_must_be_complete_and_self_contained(self):
        self.assertEqual(validate_glb(empty_glb())['asset']['version'], '2.0')
        with self.assertRaises(ValueError):
            validate_glb(empty_glb()[:-1])
        data = json.dumps({'asset': {'version': '2.0'}, 'images': [{'uri': 'https://example.com/image.png'}]}).encode()
        data += b' ' * (-len(data) % 4)
        with self.assertRaises(ValueError):
            validate_glb(b'glTF' + struct.pack('<IIII', 2, 20 + len(data), len(data), 0x4e4f534a) + data)


class FakeProviders:
    def __init__(self):
        self.image_active = self.model_active = self.image_peak = self.model_peak = 0
        self.images = self.submits = 0
        self.overlap = False

    async def image(self, asset, style, reference):
        self.images += 1
        self.image_active += 1
        self.image_peak = max(self.image_peak, self.image_active)
        await asyncio.sleep(.02)
        self.overlap |= self.model_active > 0
        self.image_active -= 1
        return b'\xff\xd8\xffimage'

    async def submit(self, provider, asset, image):
        self.submits += 1
        self.model_active += 1
        self.model_peak = max(self.model_peak, self.model_active)
        return {'id': asset.id, 'subscription': 'private-subscription'}

    async def poll(self, provider, upstream):
        await asyncio.sleep(.04)
        return 'https://example.com/model.glb'

    async def download(self, url):
        self.model_active -= 1
        return empty_glb()


class PipelineTests(unittest.IsolatedAsyncioTestCase):
    def job(self, studio):
        plan = blueprint()
        job = {'id': 'test', 'state': 'planned', 'plan': plan.model_dump(mode='json'),
               'recipe': world_recipe(plan), 'assets': {a.id: {'state': 'planned', 'name': a.name}
                                                       for a in plan.assets}}
        studio.jobs[job['id']] = job
        studio.save(job)
        return job

    async def test_bounded_parallel_stages_and_ready_assets_are_not_resubmitted(self):
        provider = FakeProviders()
        with tempfile.TemporaryDirectory() as tmp:
            studio = SceneStudio(tmp, {'OPENAI_API_KEY': 'test', 'RODIN_API_KEY': 'test'}, provider)
            job = self.job(studio)
            studio.start(job)
            with self.assertRaises(ValueError):
                studio.start(job)
            await studio.tasks['test']
            self.assertEqual(job['state'], 'ready')
            self.assertEqual((provider.image_peak, provider.model_peak), (2, 3))
            self.assertTrue(provider.overlap, 'modeling must overlap later image generation')
            self.assertEqual(provider.submits, 6)
            self.assertNotIn('private-subscription', json.dumps(studio.public(job)))
            restored = SceneStudio(tmp, studio.settings, provider)
            restored.start(restored.get('test'))
            await restored.tasks['test']
            self.assertEqual((provider.images, provider.submits), (6, 6))

    async def test_unknown_paid_submission_is_never_automatically_retried(self):
        provider = FakeProviders()
        provider.submit = AsyncMock(side_effect=UnknownSubmission('unknown'))
        with tempfile.TemporaryDirectory() as tmp:
            studio = SceneStudio(tmp, {'OPENAI_API_KEY': 'test', 'RODIN_API_KEY': 'test'}, provider)
            job = self.job(studio)
            studio.start(job, asset_ids=['asset_0'])
            await studio.tasks['test']
            self.assertEqual(job['assets']['asset_0']['state'], 'unknown')
            restored = SceneStudio(tmp, studio.settings, provider)
            restored.start(restored.get('test'), asset_ids=['asset_0'])
            await restored.tasks['test']
            self.assertEqual(provider.submit.await_count, 1)

    async def test_ready_assets_can_be_reused_when_new_assets_use_another_provider(self):
        provider = FakeProviders()
        with tempfile.TemporaryDirectory() as tmp:
            studio = SceneStudio(tmp, {'OPENAI_API_KEY': 'test', 'RODIN_API_KEY': 'test', 'TRIPO_API_KEY': 'test'}, provider)
            job = self.job(studio)
            studio.start(job, asset_ids=['asset_0'])
            await studio.tasks['test']
            studio.start(job, provider='tripo')
            await studio.tasks['test']
            self.assertEqual(provider.submits, 6)
            self.assertEqual(job['assets']['asset_0']['provider'], 'rodin')
            self.assertEqual(job['assets']['asset_1']['provider'], 'tripo')

    async def test_resume_queries_existing_task_without_regenerating_image_or_model(self):
        provider = FakeProviders()
        with tempfile.TemporaryDirectory() as tmp:
            studio = SceneStudio(tmp, {'OPENAI_API_KEY': 'test', 'RODIN_API_KEY': 'test'}, provider)
            job = self.job(studio)
            record = job['assets']['asset_0']
            record.update(state='interrupted', provider='rodin', upstream={'id': 'existing'})
            (Path(tmp) / 'test/asset_0.image').write_bytes(b'\xff\xd8\xffimage')
            studio.start(job, asset_ids=['asset_0'])
            await studio.tasks['test']
            self.assertEqual(record['state'], 'ready')
            self.assertEqual((provider.images, provider.submits), (0, 0))

    async def test_reference_uses_image_edits_and_pbr_model_providers(self):
        providers = Providers({'OPENAI_API_KEY': 'test', 'RODIN_API_KEY': 'test', 'TRIPO_API_KEY': 'test'})
        providers.request = AsyncMock(return_value={'data': [{'b64_json': base64.b64encode(b'\xff\xd8\xffimage').decode()}]})
        await providers.image(blueprint().assets[0], 'style', b'\xff\xd8\xffref')
        self.assertEqual(providers.request.call_args.args[1], '/images/edits')
        self.assertEqual(providers.request.call_args.kwargs['files'][0][0], 'image[]')
        prompt = providers.request.call_args.kwargs['data']['prompt']
        self.assertIn('Absolutely no birds', prompt)
        providers.request = AsyncMock(side_effect=[{'code': 0, 'data': {'file_token': 'file_a'}},
                                                  {'code': 0, 'data': {'task_id': 'task_a'}}])
        result = await providers.submit('tripo', blueprint().assets[0], b'\xff\xd8\xffimage')
        self.assertEqual(result['id'], 'task_a')
        self.assertEqual(providers.request.call_args.args[1], '/generation/image-to-model')
        self.assertTrue(providers.request.call_args.kwargs['body']['pbr'])

    async def test_planner_must_preserve_original_quotes(self):
        import httpx
        plan = blueprint().model_dump(mode='json')
        transport = httpx.MockTransport(lambda request: httpx.Response(200, json={
            'choices': [{'message': {'content': json.dumps(plan)}}]}))
        async with httpx.AsyncClient(transport=transport) as client:
            with self.assertRaises(ValueError):
                await plan_conversation(['different original input'], {'SCENE_PLANNER_API_KEY': 'test'}, client)
