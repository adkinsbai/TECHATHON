"""Scene studio endpoints; demo data lives outside personal chat history."""
from typing import Literal
import asyncio
import webbrowser

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from . import config, store
from .scene_assets import SceneStudio, image_mime
from .scene_plan import ZOO_CONVERSATION


def attach_scene_routes(app):
    studio = SceneStudio(config.HOME / 'world-studio')

    async def local_origin(request: Request):
        origin = request.headers.get('origin')
        if origin and origin != str(request.base_url).rstrip('/'):
            raise HTTPException(403, '仅允许本机页面操作场景生成。')

    router = APIRouter(prefix='/api/scene-studio', dependencies=[Depends(local_origin)])

    class PlanIn(BaseModel):
        conversation: list[str] = Field(default_factory=list, max_length=40)
        use_recent_chat: bool = False

    class GenerateIn(BaseModel):
        # auto：动物走 Tripo（自动绑骨、加动作），植物和建筑走 Rodin。
        provider: Literal['auto', 'rodin', 'tripo'] = 'auto'
        asset_ids: list[str] | None = Field(default=None, max_length=16)

    class ReviseIn(BaseModel):
        changes: str = Field(min_length=1, max_length=3000)
        regenerate_asset_ids: list[str] = Field(default_factory=list, max_length=16)

    class OpenWorldIn(BaseModel):
        scene_id: str | None = Field(default=None, pattern=r'^[a-f0-9]{32}$')
        chapter: str = Field(default='cabin', pattern=r'^(cabin|voyage|w[0-9]+)$')

    @app.post('/api/open-world', dependencies=[Depends(local_origin)])
    async def open_world(body: OpenWorldIn, request: Request):
        if body.scene_id:
            job_for(body.scene_id)
        query = 'scene=' + body.scene_id if body.scene_id else 'chapter=' + body.chapter
        url = f'http://127.0.0.1:{request.url.port or config.PORT}/world?{query}'
        opened = await asyncio.to_thread(webbrowser.open, url)
        if not opened:
            raise HTTPException(503, '未能打开默认浏览器，请把当前地址复制到 Edge / Chrome。')
        return {'ok': True, 'url': url}

    def job_for(job_id):
        try:
            return studio.get(job_id)
        except KeyError:
            raise HTTPException(404, '没有这个场景。') from None

    @router.get('/config')
    async def capabilities():
        settings = studio.settings
        return {'image_configured': bool(settings.get('OPENAI_API_KEY')),
                'rodin_configured': bool(settings.get('RODIN_API_KEY')),
                'tripo_configured': bool(settings.get('TRIPO_API_KEY')),
                'planner_model': settings.get('SCENE_PLANNER_MODEL') or config.DEEPSEEK_MODEL,
                'image_model': settings.get('OPENAI_IMAGE_MODEL', 'gpt-image-2'),
                'concurrency': {'images': 2, 'models': 3}, 'demo_conversation': ZOO_CONVERSATION}

    @router.get('')
    async def list_jobs():
        return [studio.public(job) for job in reversed(list(studio.jobs.values()))]

    @router.post('/plan')
    async def create_plan(body: PlanIn):
        if len(studio.tasks) >= 3:
            raise HTTPException(409, '场景任务队列已满，请等待当前任务完成。')
        quotes = body.conversation
        if body.use_recent_chat:
            quotes = [m['content'] for m in store.recent_messages(40) if m['role'] == 'user'][-20:]
        if not quotes or any(not isinstance(q, str) or not q.strip() or len(q) > 3000 for q in quotes):
            raise HTTPException(422, '请输入 1–40 句对话，每句不超过 3000 字。')
        if sum(map(len, quotes)) > 24000:
            raise HTTPException(422, '本次场景素材超过 24000 字。')
        return studio.public(studio.create(quotes))

    @router.get('/{job_id}')
    async def get_job(job_id: str):
        return studio.public(job_for(job_id))

    @router.post('/{job_id}/generate')
    async def generate(job_id: str, body: GenerateIn):
        job = job_for(job_id)
        try:
            studio.start(job, body.provider, body.asset_ids)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from None
        return studio.public(job)

    @router.post('/{job_id}/revise')
    async def revise(job_id: str, body: ReviseIn):
        job = job_for(job_id)
        try:
            studio.revise(job, body.changes, body.regenerate_asset_ids)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from None
        return studio.public(job)

    @router.post('/{job_id}/assets/{asset_id}/reference')
    async def upload_reference(job_id: str, asset_id: str, file: UploadFile = File(...)):
        job = job_for(job_id)
        if asset_id not in job.get('assets', {}):
            raise HTTPException(404, '没有这个资产。')
        if job_id in studio.tasks or job['assets'][asset_id]['state'] != 'planned':
            raise HTTPException(409, '请在开始生成前上传参考图。')
        data = await file.read(8 * 1024 * 1024 + 1)
        if len(data) > 8 * 1024 * 1024:
            raise HTTPException(413, '参考图不能超过 8 MB。')
        try:
            image_mime(data)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None
        (studio.directory / job_id / (asset_id + '.reference')).write_bytes(data)
        job['assets'][asset_id]['has_reference'] = True
        studio.save(job)
        return {'ok': True}

    @router.get('/{job_id}/assets/{asset_id}/{kind}')
    async def artifact(job_id: str, asset_id: str, kind: Literal['image', 'model']):
        job = job_for(job_id)
        if asset_id not in job.get('assets', {}):
            raise HTTPException(404, '没有这个资产。')
        file = studio.directory / job_id / (asset_id + ('.image' if kind == 'image' else '.glb'))
        if not file.is_file():
            raise HTTPException(404, '资产尚未就绪。')
        mime = image_mime(file.read_bytes()[:16]) if kind == 'image' else 'model/gltf-binary'
        return FileResponse(file, media_type=mime)

    @router.get('/{job_id}/assets/{asset_id}/clip/{index}')
    async def clip(job_id: str, asset_id: str, index: int):
        job = job_for(job_id)
        if asset_id not in job.get('assets', {}) or not 0 <= index < 8:
            raise HTTPException(404, '没有这个动作文件。')
        file = studio.directory / job_id / f'{asset_id}.clip{index}.glb'
        if not file.is_file():
            raise HTTPException(404, '动作文件尚未就绪。')
        return FileResponse(file, media_type='model/gltf-binary')

    @app.get('/world-studio')
    async def studio_page():
        return FileResponse(config.ROOT / 'static/world-studio.html')

    app.include_router(router)
    app.state.scene_studio = studio
