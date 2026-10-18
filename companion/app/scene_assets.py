"""Durable, bounded parallel GPT image -> Rodin/Tripo -> local GLB pipeline."""
import asyncio
import base64
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import socket
import struct
import time
from urllib.parse import urlparse
import uuid

import httpx

from . import config
from .scene_plan import ScenePlan, plan_conversation, world_recipe


TRIPO_BASE = 'https://openapi.tripo3d.ai/v3'
# v2.5 绑骨对非人形生物提供一套通用动作；默认取待机和走路。可用 TRIPO_ANIMATIONS=preset:idle,preset:walk 覆盖。
DEFAULT_ANIMATIONS = ('preset:idle', 'preset:walk')
RIG_TERMINAL = ('ready', 'failed', 'skipped', 'unknown')


# Clash / Surge 等代理的 TUN“fake-ip”模式把所有域名解析到 198.18.0.0/15（RFC 2544 测试保留段，
# 不会是真实内网）。开着这种代理的电脑上，服务商的下载域名也会落在这里；只额外放行这一段，其余非公网地址仍拒绝。
PROXY_FAKE_IP = ipaddress.ip_network('198.18.0.0/15')


def download_address_allowed(address):
    ip = ipaddress.ip_address(address)
    return ip.is_global or ip in PROXY_FAKE_IP


def task_model_urls(output):
    """retarget 可能返回一个含全部动作的 GLB，也可能每个动作一个；统一成 [(名字, 地址)]。"""
    urls = output.get('model_urls')
    if isinstance(urls, dict):
        return [(str(k), v) for k, v in urls.items() if isinstance(v, str)]
    if isinstance(urls, list):
        result = []
        for index, item in enumerate(urls):
            if isinstance(item, str):
                result.append((str(index), item))
            elif isinstance(item, dict) and (item.get('url') or item.get('model_url')):
                result.append((str(item.get('animation') or item.get('name') or index),
                               item.get('url') or item.get('model_url')))
        return result
    return [('model', output['model_url'])] if isinstance(output.get('model_url'), str) else []


def clip_name(name):
    return str(name).split(':')[-1].strip() or 'clip'


def settings_from_local():
    settings = {}
    # Only an ignored local pointer is stored in the checkout; credentials stay
    # in their existing backend .env. Never return settings through the API.
    pointer = config.ROOT.parent / '.scene-local.json'
    if pointer.exists():
        location = json.loads(pointer.read_text(encoding='utf-8-sig')).get('asset_env_file')
        if location:
            for line in Path(location).read_text(encoding='utf-8-sig').splitlines():
                key, sep, value = line.strip().partition('=')
                if sep and not key.startswith('#'):
                    settings[key] = value.strip().strip('\"\'')
    for key in ('OPENAI_API_KEY', 'OPENAI_BASE_URL', 'OPENAI_IMAGE_MODEL', 'RODIN_API_KEY',
                'TRIPO_API_KEY', 'TRIPO_PROXY_URL', 'TRIPO_ANIMATIONS', 'SCENE_PLANNER_API_KEY',
                'SCENE_PLANNER_BASE_URL', 'SCENE_PLANNER_MODEL'):
        if key in os.environ:
            settings[key] = os.environ[key]
        elif key not in settings and key in config.ENV:
            settings[key] = config.ENV[key]
    return settings


def image_mime(data):
    if data.startswith(b'\x89PNG\r\n\x1a\n'):
        return 'image/png'
    if data.startswith(b'\xff\xd8\xff'):
        return 'image/jpeg'
    if data[:4] == b'RIFF' and data[8:12] == b'WEBP':
        return 'image/webp'
    raise ValueError('图片必须是 PNG、JPEG 或 WebP。')


def validate_glb(data):
    if len(data) < 20 or data[:4] != b'glTF' or struct.unpack_from('<II', data, 4) != (2, len(data)):
        raise ValueError('服务未返回完整的 GLB 2.0 模型。')
    size, kind = struct.unpack_from('<II', data, 12)
    if kind != 0x4e4f534a or size > len(data) - 20:
        raise ValueError('GLB 缺少有效 JSON 数据。')
    document = json.loads(data[20:20 + size])
    for item in document.get('buffers', []) + document.get('images', []):
        uri = item.get('uri')
        if uri and not uri.startswith('data:'):
            raise ValueError('场景资产需使用内嵌贴图和缓冲区的独立 GLB。')
    return document


class UnknownSubmission(RuntimeError):
    """A paid POST may have succeeded; never automatically resubmit it."""


class Providers:
    def __init__(self, settings):
        self.settings = settings

    async def request(self, base, endpoint, key, *, method='POST', data=None, files=None, body=None, proxy=None):
        if not key:
            raise RuntimeError('所选生成服务未配置密钥。')
        if urlparse(base).scheme != 'https':
            raise RuntimeError('生成服务必须使用 HTTPS。')
        try:
            async with httpx.AsyncClient(trust_env=False, proxy=proxy) as client:
                response = await client.request(method, base.rstrip('/') + endpoint,
                    headers={'Authorization': 'Bearer ' + key}, json=body, data=data, files=files,
                    timeout=600 if endpoint.startswith('/images/') else 120)
        except httpx.HTTPError:
            if method == 'POST':
                raise UnknownSubmission('提交结果未知，请先检查服务商任务记录；未自动重复提交。') from None
            raise RuntimeError('任务查询暂时无法连接，已有任务编号仍保留。') from None
        if response.status_code >= 400:
            raise RuntimeError(f'生成服务返回 HTTP {response.status_code}；请检查额度、权限或参数。')
        return response.json()

    async def image(self, asset, style, reference=None):
        base = self.settings.get('OPENAI_BASE_URL', 'https://api.openai.com/v1')
        prompt = (f'Create a single isolated 3D reconstruction reference. Shared art direction: {style}.\n'
                  f'{asset.image_prompt}\n'
                  'Complete subject, all limbs and tail visible, neutral pose, pale plain background, '
                  'even lighting, no text, no scene, no ground plane, no pedestal, no other subjects. '
                  'If an image is supplied, preserve its subject identity while applying this art direction.')
        if asset.kind == 'plant':
            prompt += '\nONLY THE PLANT. Absolutely no birds, animals, people, ornaments, pots or other objects, even if the scene will later put a bird on this plant.'
        elif asset.kind == 'structure':
            prompt += '\nONLY THE BUILDING/STRUCTURE. No people or animals. All walls, roof and entrance fully visible, complete structure.'
        parameters = {'model': self.settings.get('OPENAI_IMAGE_MODEL', 'gpt-image-2'),
                      'prompt': prompt, 'size': '1024x1024', 'quality': 'medium',
                      'output_format': 'jpeg', 'output_compression': 90, 'n': 1}
        if reference:
            mime = image_mime(reference)
            extension = {'image/png': 'png', 'image/jpeg': 'jpg', 'image/webp': 'webp'}[mime]
            result = await self.request(base, '/images/edits', self.settings.get('OPENAI_API_KEY'),
                data={k: str(v) for k, v in parameters.items()},
                files=[('image[]', ('reference.' + extension, reference, mime))])
        else:
            result = await self.request(base, '/images/generations', self.settings.get('OPENAI_API_KEY'), body=parameters)
        encoded = result.get('data', [{}])[0].get('b64_json', '')
        if not encoded or len(encoded) > 16 * 1024 * 1024:
            raise RuntimeError('图像服务没有返回可用的内嵌图片。')
        image = base64.b64decode(encoded, validate=True)
        image_mime(image)
        return image

    async def submit(self, provider, asset, image):
        if provider == 'rodin':
            data = await self.request('https://api.hyper3d.com/api/v2', '/rodin', self.settings.get('RODIN_API_KEY'),
                data={'tier': 'Gen-2.5-Medium', 'mesh_mode': 'Raw', 'geometry_file_format': 'glb',
                      'quality_override': '20000', 'material': 'PBR', 'TAPose': 'false'},
                files=[('images', ('reference.jpg', image, image_mime(image)))])
            if data.get('error') not in (None, 'OK') or not data.get('uuid') or not data.get('jobs', {}).get('subscription_key'):
                raise UnknownSubmission('Rodin 未返回完整任务编号；请先检查服务商记录。')
            return {'id': data['uuid'], 'subscription': data['jobs']['subscription_key']}
        base = TRIPO_BASE
        proxy = self.settings.get('TRIPO_PROXY_URL') or None
        upload = await self.request(base, '/files', self.settings.get('TRIPO_API_KEY'), proxy=proxy,
                                   files=[('file', ('reference.jpg', image, image_mime(image)))])
        token = upload.get('data', {}).get('file_token')
        if upload.get('code') != 0 or not token:
            raise RuntimeError('Tripo 上传失败。')
        data = await self.request(base, '/generation/image-to-model', self.settings.get('TRIPO_API_KEY'), proxy=proxy,
            body={'input': token, 'model': 'v3.1-20260211', 'texture': True, 'pbr': True,
                  'texture_quality': 'detailed', 'orientation': 'align_image'})
        task = data.get('data', {}).get('task_id')
        if data.get('code') != 0 or not task:
            raise UnknownSubmission('Tripo 未返回任务编号；请先检查服务商记录。')
        return {'id': task}

    async def poll(self, provider, upstream):
        if provider == 'rodin':
            base, key = 'https://api.hyper3d.com/api/v2', self.settings.get('RODIN_API_KEY')
            data = await self.request(base, '/status', key, body={'subscription_key': upstream['subscription']})
            states = [job.get('status') for job in data.get('jobs', [])]
            if any(state in ('Failed', 'Canceled', 'Cancelled') for state in states):
                raise RuntimeError('Rodin 任务失败。')
            if states and all(state == 'Done' for state in states):
                result = await self.request(base, '/download', key, body={'task_uuid': upstream['id']})
                file = next((f for f in result.get('list', []) if f.get('name', '').lower().endswith('.glb')), None)
                if not file:
                    raise RuntimeError('Rodin 任务完成，但没有 GLB 文件。')
                return file['url']
            return None
        data = await self.request(TRIPO_BASE, '/tasks/' + upstream['id'],
            self.settings.get('TRIPO_API_KEY'), method='GET', proxy=self.settings.get('TRIPO_PROXY_URL') or None)
        task = data.get('data', {})
        if task.get('status') in ('failed', 'cancelled', 'expired'):
            raise RuntimeError('Tripo 任务失败。')
        if task.get('status') == 'success':
            url = task.get('output', {}).get('model_url')
            if not url:
                raise RuntimeError('Tripo 任务缺少 GLB 结果。')
            return url
        return None

    # ---------- Tripo 绑骨与动作：rig-check → rig → retarget，每步用上一步的任务编号作 input ----------
    async def tripo(self, path, body=None, method='POST'):
        return await self.request(TRIPO_BASE, path, self.settings.get('TRIPO_API_KEY'), method=method, body=body,
                                  proxy=self.settings.get('TRIPO_PROXY_URL') or None)

    async def tripo_task(self, task_id):
        """进行中返回 None；成功返回 output；失败抛错。"""
        data = await self.tripo('/tasks/' + task_id, method='GET')
        task = data.get('data', {})
        if task.get('status') in ('failed', 'cancelled', 'expired', 'banned'):
            raise RuntimeError('Tripo 任务失败：' + str(task.get('status')))
        return (task.get('output') or {}) if task.get('status') == 'success' else None

    async def rig_check(self, model_task_id):
        """免费检查。文档示例是直接返回 rig_type；若返回任务编号则交给调用方轮询。"""
        data = await self.tripo('/animations/rig-check', {'input': model_task_id})
        if data.get('code') != 0:
            raise RuntimeError('Tripo 绑骨检查失败：' + str(data.get('message') or data.get('code')))
        result = data.get('data', {})
        if 'rig_type' in result or 'riggable' in result:
            return {'riggable': result.get('riggable', True), 'rig_type': result.get('rig_type')}
        if result.get('task_id'):
            return {'task_id': result['task_id']}
        raise RuntimeError('Tripo 绑骨检查没有返回结果。')

    async def rig_submit(self, model_task_id, rig_type):
        data = await self.tripo('/animations/rig', {'input': model_task_id, 'rig_type': rig_type,
                                                    'spec': 'tripo', 'out_format': 'glb'})
        task = data.get('data', {}).get('task_id')
        if data.get('code') != 0 or not task:
            raise UnknownSubmission('Tripo 绑骨未返回任务编号；请先检查服务商记录。')
        return task

    async def retarget_submit(self, rig_task_id, animations):
        data = await self.tripo('/animations/retarget', {'input': rig_task_id, 'animations': animations,
                                                         'out_format': 'glb'})
        task = data.get('data', {}).get('task_id')
        if data.get('code') != 0 or not task:
            raise UnknownSubmission('Tripo 动作重定向未返回任务编号；请先检查服务商记录。')
        return task

    async def download(self, url):
        # Use a fresh client without provider Authorization on signed CDN URLs.
        async with httpx.AsyncClient(trust_env=False) as client:
            for _ in range(5):
                parsed = urlparse(url)
                if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
                    raise RuntimeError('模型下载地址无效。')
                addresses = await asyncio.get_running_loop().getaddrinfo(parsed.hostname, 443, type=socket.SOCK_STREAM)
                if not addresses or any(not download_address_allowed(a[4][0]) for a in addresses):
                    raise RuntimeError('拒绝从非公网地址下载模型。')
                async with client.stream('GET', url, timeout=180) as response:
                    if response.is_redirect:
                        from urllib.parse import urljoin
                        url = urljoin(url, response.headers['location'])
                        continue
                    response.raise_for_status()
                    chunks, size = [], 0
                    async for block in response.aiter_bytes():
                        size += len(block)
                        if size > 200 * 1024 * 1024:
                            raise RuntimeError('模型超过 200 MB。')
                        chunks.append(block)
                    data = b''.join(chunks)
                    validate_glb(data)
                    return data
        raise RuntimeError('模型下载重定向过多。')


class SceneStudio:
    def __init__(self, directory, settings=None, providers=None):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.settings = settings if settings is not None else settings_from_local()
        self.providers = providers or Providers(self.settings)
        self.jobs, self.tasks = {}, {}
        self.image_slots, self.model_slots = asyncio.Semaphore(2), asyncio.Semaphore(3)
        self.poll_seconds = 10
        for file in self.directory.glob('*/job.json'):
            job = json.loads(file.read_text(encoding='utf-8'))
            for asset in job.get('assets', {}).values():
                if asset['state'] in ('image_running', 'model_submitting'):
                    asset.update(state='unknown', message='应用曾在提交过程中退出，请检查服务商任务记录。')
                elif asset['state'] not in ('ready', 'planned', 'failed', 'unknown'):
                    asset.update(state='interrupted', message='任务已保留，点击继续只查询原任务。')
            if job.get('state') == 'planning':
                job.update(state='failed', error='规划曾被中断，请重新规划。')
            elif job.get('state') == 'generating':
                job['state'] = 'partial'
            self.jobs[job['id']] = job

    def save(self, job):
        folder = self.directory / job['id']
        folder.mkdir(exist_ok=True)
        temporary = folder / 'job.tmp'
        temporary.write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding='utf-8')
        os.replace(temporary, folder / 'job.json')

    def get(self, job_id):
        if job_id not in self.jobs:
            raise KeyError('未找到场景。')
        return self.jobs[job_id]

    def public(self, job):
        # Upstream subscription keys/signed URLs are intentionally private.
        assets = {key: {k: v for k, v in value.items() if k not in ('upstream', 'download_url')}
                  for key, value in job.get('assets', {}).items()}
        ready = sum(a['state'] == 'ready' for a in assets.values())
        return {k: v for k, v in job.items() if k != 'assets'} | {
            'assets': assets, 'ready_count': ready, 'asset_count': len(assets),
            'running': job['id'] in self.tasks, 'world_url': '/world?scene=' + job['id']}

    def track(self, job, coroutine):
        async def run():
            try:
                await coroutine
            finally:
                self.tasks.pop(job['id'], None)
        self.tasks[job['id']] = asyncio.create_task(run())

    def create(self, quotes):
        job = {'id': uuid.uuid4().hex, 'created_at': time.time(), 'state': 'planning',
               'conversation': quotes, 'assets': {}}
        self.jobs[job['id']] = job
        self.save(job)
        self.track(job, self.plan(job))
        return job

    async def plan(self, job):
        try:
            plan, model = await plan_conversation(job['conversation'], self.settings)
            job.update(state='planned', plan=plan.model_dump(mode='json'), planner_model=model,
                       recipe=world_recipe(plan))
            job['assets'] = {a.id: {'state': 'planned', 'message': '等待生成', 'name': a.name}
                             for a in plan.assets}
        except Exception as exc:
            job.update(state='failed', error=str(exc) if isinstance(exc, RuntimeError) else '规划结果不符合场景结构，请重新规划。')
        self.save(job)

    def revise(self, job, changes, regenerate_ids):
        if job['id'] in self.tasks or not job.get('plan'):
            raise ValueError('请等待当前任务完成后修订。')
        if any(i not in job['assets'] for i in regenerate_ids):
            raise ValueError('待重做的资产编号无效。')
        job['state'] = 'planning'
        self.save(job)
        self.track(job, self.plan_revision(job, changes, regenerate_ids))

    async def plan_revision(self, job, changes, regenerate_ids):
        try:
            old_plan = job['plan']
            plan, model = await plan_conversation(job['conversation'], self.settings, revision={
                'previous_plan': old_plan, 'requested_changes': changes,
                'constraint': 'Keep existing animal asset IDs and exactly one parrot instance. Preserve existing animal locations unless requested. Add entrance_gate, rest_pavilion, animal_shelter assets with instances along visitor paths. Only one pure tree asset. Keep buildings away from the spawn at (22,0,70) and keep the walking path clear. Write a short evocative title, not a technical plan title.'})
            old_assets = job['assets']
            if not set(old_assets).issubset({a.id for a in plan.assets}):
                raise ValueError('修订不能丢弃已有资产。')
            folder = self.directory / job['id']
            revision = folder / 'revisions' / str(time.time_ns())
            revision.mkdir(parents=True)
            (revision / 'plan.json').write_text(json.dumps(old_plan, ensure_ascii=False), encoding='utf-8')
            for asset_id in regenerate_ids:
                (revision / (asset_id + '.record.json')).write_text(json.dumps(old_assets[asset_id]), encoding='utf-8')
                for suffix in ('.image', '.glb', '.reference'):
                    file = folder / (asset_id + suffix)
                    if file.exists():
                        file.rename(revision / file.name)
            job.update(plan=plan.model_dump(mode='json'), recipe=world_recipe(plan), planner_model=model,
                       state='planned', revision=job.get('revision', 0) + 1)
            job['assets'] = {a.id: old_assets[a.id] if a.id in old_assets and a.id not in regenerate_ids
                             else {'name': a.name, 'state': 'planned', 'message': '等待生成'} for a in plan.assets}
            job.pop('error', None)
        except Exception as exc:
            job.update(state='partial', error=str(exc) if isinstance(exc, RuntimeError) else '修订结构无效，已有场景保留。')
        self.save(job)

    @staticmethod
    def provider_for(kind, provider):
        # auto：动物用 Tripo（之后能自动绑骨、加动作），植物和建筑用 Rodin。
        return ('tripo' if kind == 'animal' else 'rodin') if provider == 'auto' else provider

    def needs_rig(self, kind, record):
        return (kind == 'animal' and record.get('provider') == 'tripo' and record.get('upstream')
                and self.settings.get('TRIPO_API_KEY') and self.settings.get('TRIPO_RIG', '1') != '0')

    def start(self, job, provider='rodin', asset_ids=None):
        if job['id'] in self.tasks:
            raise ValueError('场景已有任务运行。')
        if not job.get('plan'):
            raise ValueError('请先完成场景规划。')
        ids = list(job['assets']) if asset_ids is None else list(dict.fromkeys(asset_ids))
        if any(i not in job['assets'] for i in ids):
            raise ValueError('资产编号无效。')
        kinds = {a['id']: a['kind'] for a in job['plan']['assets']}
        wanted = {self.provider_for(kinds.get(i), provider) for i in ids
                  if job['assets'][i]['state'] not in ('ready', 'unknown') and not job['assets'][i].get('upstream')}
        missing = [p for p in wanted if not self.settings.get('RODIN_API_KEY' if p == 'rodin' else 'TRIPO_API_KEY')]
        if missing or (wanted and not self.settings.get('OPENAI_API_KEY')):
            raise ValueError('请先配置图像服务和所选 3D 服务密钥（' + '、'.join(sorted(missing) or ['图像服务']) + '）。')
        for asset_id in ids:
            asset = job['assets'][asset_id]
            if asset['state'] in ('ready', 'unknown'):
                continue  # Never resubmit an ambiguous paid request.
            chosen = self.provider_for(kinds.get(asset_id), provider)
            if asset.get('provider') and asset['provider'] != chosen and asset.get('upstream'):
                raise ValueError('已有上游任务不能切换服务商；请继续查询原任务。')
            if not asset.get('upstream'):
                asset['provider'] = chosen
        job['state'] = 'generating'
        self.save(job)
        self.track(job, self.produce(job, ids))

    async def produce(self, job, ids):
        await asyncio.gather(*(self.produce_asset(job, asset_id) for asset_id in ids))
        states = [a['state'] for a in job['assets'].values()]
        job['state'] = 'ready' if all(s == 'ready' for s in states) else 'partial'
        self.save(job)

    async def produce_asset(self, job, asset_id):
        record = job['assets'][asset_id]
        asset = next(a for a in ScenePlan.model_validate(job['plan']).assets if a.id == asset_id)
        folder = self.directory / job['id']
        if record['state'] == 'ready':
            # 静态模型已就绪；动物的绑骨/动作若中断过，只继续查询原任务。
            if self.needs_rig(asset.kind, record) and record.get('rig', {}).get('state') not in RIG_TERMINAL:
                await self.rig_asset(job, asset_id, record, folder)
            return
        if record['state'] == 'unknown':
            return
        image_file = folder / (asset_id + '.image')
        try:
            if not image_file.exists():
                async with self.image_slots:
                    record.update(state='image_running', message='GPT 正在生成统一风格参考图', image_started_at=time.time())
                    self.save(job)
                    reference = folder / (asset_id + '.reference')
                    image = await self.providers.image(asset, job['plan']['style'], reference.read_bytes() if reference.exists() else None)
                    image_file.write_bytes(image)
                    record.update(image_url=f'/api/scene-studio/{job["id"]}/assets/{asset_id}/image',
                                  image_sha256=hashlib.sha256(image).hexdigest(), image_finished_at=time.time(),
                                  image_model=self.settings.get('OPENAI_IMAGE_MODEL', 'gpt-image-2'))
                    self.save(job)
            async with self.model_slots:
                if not record.get('upstream'):
                    record.update(state='model_submitting', message='正在提交 3D 建模', model_started_at=time.time())
                    self.save(job)
                    record['upstream'] = await self.providers.submit(record['provider'], asset, image_file.read_bytes())
                    self.save(job)
                record.update(state='model_running', message='正在生成网格与 PBR 材质')
                self.save(job)
                deadline = time.monotonic() + 3600
                failures = 0
                while True:
                    try:
                        url = await self.providers.poll(record['provider'], record['upstream'])
                        failures = 0
                    except (RuntimeError, httpx.HTTPError):
                        failures += 1
                        if failures >= 5:
                            raise RuntimeError('查询暂不可用，任务编号已保存；点击继续查询，不会重新建模。') from None
                        url = None
                    if url:
                        break
                    if time.monotonic() > deadline:
                        raise RuntimeError('任务仍未完成，已保留编号；稍后继续查询。')
                    await asyncio.sleep(10)
                record.update(state='downloading', message='正在保存 GLB 并检查完整性')
                self.save(job)
                model = await self.providers.download(url)
                validate_glb(model)
                (folder / (asset_id + '.glb')).write_bytes(model)
                record.update(state='ready', message='资产已就绪，可导入世界', model_finished_at=time.time(),
                    model_sha256=hashlib.sha256(model).hexdigest(), model_bytes=len(model),
                    model_url=f'/api/scene-studio/{job["id"]}/assets/{asset_id}/model')
                self.save(job)
            if self.needs_rig(asset.kind, record):
                await self.rig_asset(job, asset_id, record, folder)
        except asyncio.CancelledError:
            if record.get('state') != 'ready':   # 绑骨阶段退出时静态模型仍然可用
                record.update(state='interrupted' if record.get('upstream') else 'unknown', message='应用退出，任务状态已保留。')
            raise
        except UnknownSubmission as exc:
            record.update(state='unknown', message=str(exc))
        except Exception as exc:
            record.update(state='interrupted' if record.get('upstream') else 'failed',
                          message=str(exc) if isinstance(exc, (RuntimeError, ValueError)) else '生成失败，已有结果已保留。')
        finally:
            self.save(job)

    async def wait_tripo(self, task_id):
        deadline, failures = time.monotonic() + 3600, 0
        while True:
            try:
                output = await self.providers.tripo_task(task_id)
                failures = 0
            except httpx.HTTPError:
                failures += 1
                if failures >= 5:
                    raise RuntimeError('查询暂不可用，任务编号已保存；点击继续查询，不会重新提交。') from None
                output = None
            if output is not None:
                return output
            if time.monotonic() > deadline:
                raise RuntimeError('任务仍未完成，已保留编号；稍后继续查询。')
            await asyncio.sleep(self.poll_seconds)

    async def rig_asset(self, job, asset_id, record, folder):
        """Tripo：检查 → 绑骨 → 套动作 → 下载带骨骼动画的 GLB。失败只影响动作，静态模型照常可用。
        每一步的任务编号都先存盘；提交结果不明时标记 unknown，绝不自动重发付费请求。"""
        rig = record.setdefault('rig', {'state': 'pending'})
        if rig.get('state') in RIG_TERMINAL:
            return
        configured = self.settings.get('TRIPO_ANIMATIONS', '')
        animations = [a.strip() for a in configured.split(',') if a.strip()] or list(DEFAULT_ANIMATIONS)
        try:
            async with self.model_slots:
                if not rig.get('rig_type'):
                    rig.update(state='checking', message='Tripo 正在检查能否绑骨')
                    self.save(job)
                    check = await self.providers.rig_check(record['upstream']['id'])
                    if 'task_id' in check:
                        check = await self.wait_tripo(check['task_id'])
                    if check.get('riggable') is False or not check.get('rig_type'):
                        rig.update(state='skipped', message='Tripo 判断这个模型不适合绑骨，使用静态模型。')
                        return
                    rig['rig_type'] = check['rig_type']
                    self.save(job)
                if not rig.get('rig_task'):
                    rig.update(state='rigging', message=f'正在自动绑骨（{rig["rig_type"]}）')
                    self.save(job)
                    rig['rig_task'] = await self.providers.rig_submit(record['upstream']['id'], rig['rig_type'])
                    self.save(job)
                rig.update(state='rigging', message=f'正在自动绑骨（{rig["rig_type"]}）')
                self.save(job)
                await self.wait_tripo(rig['rig_task'])
                if not rig.get('retarget_task'):
                    rig.update(state='animating', message='正在套用动作：' + '、'.join(map(clip_name, animations)))
                    self.save(job)
                    rig['animations'] = animations
                    rig['retarget_task'] = await self.providers.retarget_submit(rig['rig_task'], animations)
                    self.save(job)
                rig.update(state='animating', message='正在套用动作：' + '、'.join(map(clip_name, rig['animations'])))
                self.save(job)
                output = await self.wait_tripo(rig['retarget_task'])
                files = task_model_urls(output)
                if not files:
                    raise RuntimeError('动作任务完成，但没有返回 GLB。')
                rig.update(state='downloading', message='正在保存带动作的模型')
                self.save(job)
                clips = []
                for index, (name, url) in enumerate(files[:8]):
                    model = await self.providers.download(url)
                    validate_glb(model)
                    (folder / f'{asset_id}.clip{index}.glb').write_bytes(model)
                    label = name if not name.isdigit() else (rig['animations'][index] if index < len(rig['animations']) else name)
                    clips.append({'name': clip_name(label), 'sha256': hashlib.sha256(model).hexdigest(),
                                  'url': f'/api/scene-studio/{job["id"]}/assets/{asset_id}/clip/{index}'})
                rig.update(state='ready', clips=clips, message='已绑骨并带动作：' + '、'.join(c['name'] for c in clips))
        except asyncio.CancelledError:
            rig.update(state='interrupted', message='应用退出，绑骨任务编号已保留。')
            raise
        except UnknownSubmission as exc:
            rig.update(state='unknown', message=str(exc))
        except Exception as exc:
            rig.update(state='failed', message=('绑骨或动作失败，使用静态模型：' + str(exc))[:300])
        finally:
            self.save(job)
