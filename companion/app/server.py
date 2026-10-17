"""Web 服务：python -m app.server 启动后打开 http://127.0.0.1:8765"""
import asyncio
import json
import time
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import brain, speech_stream, store, voice, weaver
from .body_runtime import BodyHub, attach_body_routes
from .config import PORT, ROOT

STATIC = ROOT / "static"
store.init()
body_hub = BodyHub(store)
_consolidating = asyncio.Lock()

INNER_AWAY = 30 * 60       # 对方离开多久后，TA 开始过自己的小日子
INNER_INTERVAL = 45 * 60   # 两次“内心活动”之间的间隔
INNER_MAX_PER_DAY = 16
WEAVE_DAYS = 3             # 每隔几天（且有新素材时）编织一个新世界


async def _inner_loop():
    await brain.warm()
    while True:
        await asyncio.sleep(60)
        await brain.warm()   # 保持和 DeepSeek 的连接不断，随时能快速回话
        try:
            last_user = store.last_user_ts()
            if not last_user:
                continue  # 还没认识，不写日记
            now = time.time()
            today = time.strftime("%Y-%m-%d")
            budget = store.get_state("inner_budget", {})
            used = budget.get("count", 0) if budget.get("date") == today else 0
            if (now - last_user > INNER_AWAY and now - store.get_state("last_inner_ts", 0) > INNER_INTERVAL
                    and used < INNER_MAX_PER_DAY):
                store.set_state("last_inner_ts", now)
                store.set_state("inner_budget", {"date": today, "count": used + 1})
                data = await brain.inner_life()
                print("内心活动：", data)
        except Exception as e:
            print("内心活动失败：", e)
        # 每小时看一次：隔了几天、又有新的生活或梦，就编织一个新世界
        try:
            # 编织也是一次很长的 DeepSeek 调用：只在用户 10 分钟没说话时做，免得拖慢聊天
            last_msg = store.last_message()
            idle = not last_msg or now - last_msg["ts"] > 600
            if idle and now - store.get_state("last_weave_check", 0) > 3600:
                store.set_state("last_weave_check", now)
                if weaver.should_weave(days=WEAVE_DAYS) and not _weaving.locked():
                    async with _weaving:
                        wid, recipe = await weaver.weave()
                    print("编织了新世界：", wid, recipe["title"])
        except Exception as e:
            print("编织世界失败：", e)


def _warm_voice():
    try:
        voice.warm_up()
        print("本地语音模型已就绪")
    except Exception as e:
        print("本地语音模型加载失败：", e)


@asynccontextmanager
async def lifespan(_app):
    task = asyncio.create_task(_inner_loop())
    asyncio.get_running_loop().run_in_executor(None, _warm_voice)
    yield
    task.cancel()


app = FastAPI(title="Companion", lifespan=lifespan)


@app.middleware("http")
async def no_cache(request, call_next):
    # 页面和脚本每次都重新校验，改完代码刷新就能生效（不会用到浏览器里的旧版本）
    response = await call_next(request)
    if not request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-cache"
    return response


def _sse(event, data):
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def _consolidate_bg(force=False):
    if _consolidating.locked():
        return
    async with _consolidating:
        try:
            await brain.consolidate(force)
        except Exception as e:  # 整理失败不影响聊天，下次再试
            print("记忆整理失败：", e)


async def _reply_stream_impl(user_text=None, note=None, heard=None):
    persona = store.get_persona()
    share = store.get_state("want_to_tell", "")
    messages = brain.build_messages(persona, user_text, note, heard=heard)
    if user_text is not None:
        store.add_message("user", user_text)
    yield _sse("start", {})
    raw = ""
    try:
        async for piece in brain.stream_chat(messages):
            raw += piece
            yield _sse("delta", {"text": piece})
    except Exception as e:
        if not brain.split_reply(raw)[0]:
            yield _sse("error", {"message": f"大脑暂时连不上：{e}"})
            return
        print("回复中途断开，保留已收到的部分：", e)
    text, emotion, intensity = brain.split_reply(raw)
    if not text:
        text = "……"
    store.add_message("assistant", text, emotion)
    store.set_state("mood", {"emotion": emotion, "intensity": intensity, "ts": time.time()})
    brain.bump_closeness()
    # 攒着的话说出口了（或是主动开口的场合），就清掉
    if share and (note or len(brain._bigrams(share) & brain._bigrams(text)) >= 4):
        store.set_state("want_to_tell", "")
    if user_text is not None:
        store.set_state("activity", "")
    yield _sse("done", {"text": text, "emotion": emotion, "intensity": intensity,
                        "closeness": store.get_state("closeness", 10.0)})
    _schedule_consolidate()


# 记忆整理要调一次很长的 DeepSeek（开思考）。如果回完话马上整理，正好撞上用户的下一句，
# 两个请求同时打过去，下一句的首字会从 2 秒拖到 7~19 秒（实测）。所以等用户停下来 90 秒再整理。
_CONSOLIDATE_IDLE = 90
_consolidate_timer: asyncio.Task | None = None


def _schedule_consolidate():
    global _consolidate_timer
    if _consolidate_timer and not _consolidate_timer.done():
        _consolidate_timer.cancel()          # 还在聊：往后推
    _consolidate_timer = asyncio.create_task(_consolidate_when_idle())


async def _consolidate_when_idle():
    try:
        await asyncio.sleep(_CONSOLIDATE_IDLE)
    except asyncio.CancelledError:
        return
    await _consolidate_bg()


def _parse_sse(chunk):
    name, data = None, []
    for line in chunk.splitlines():
        if line.startswith("event:"):
            name = line[6:].strip()
        elif line.startswith("data:"):
            data.append(line[5:].strip())
    try:
        return name, json.loads("\n".join(data) or "{}")
    except json.JSONDecodeError:
        return name, {}


async def _reply_stream(user_text=None, note=None, heard=None, source="web", tts=False):
    # tts=True：边生成边按句合成语音，用 audio 事件一句句发给前端（不用等整段写完）
    sp = speech_stream.Speaker(store.get_persona().get("voice")) if tts else None
    async for chunk in body_hub.relay(_reply_stream_impl, user_text=user_text, note=note, heard=heard, source=source):
        yield chunk
        if sp:
            ev, data = _parse_sse(chunk)
            if ev == "delta":
                sp.feed(data.get("text", ""))
            elif ev == "done":
                sp.finish()
            for a in sp.ready():
                yield _sse("audio", a)
    if sp:
        async for a in sp.drain():
            yield _sse("audio", a)
        yield _sse("audio_end", {})


@app.get("/api/audio/{audio_id}")
async def get_audio(audio_id: str):
    item = speech_stream.get_audio(audio_id)
    if not item:
        raise HTTPException(404, "音频已过期")
    return Response(item[0], media_type=item[1])


attach_body_routes(app, body_hub, _reply_stream, voice=voice)


class ChatIn(BaseModel):
    text: str
    source: Literal["web", "body"] = "web"
    voice_emotion: str = ""   # 语音识别听出的情绪（只有语音输入时才有）
    voice_event: str = ""
    scene: str = ""           # 所处场景，比如在 3D 星球的小木屋里
    tts: bool = False         # 要不要边说边合成语音


@app.post("/api/chat")
async def chat(body: ChatIn):
    text = body.text.strip()
    if not text:
        raise HTTPException(400, "空消息")
    heard = {"emotion": body.voice_emotion, "event": body.voice_event} if (body.voice_emotion or body.voice_event) else None
    note = f"（场景：{body.scene}）" if body.scene else None
    return StreamingResponse(_reply_stream(text, note=note, heard=heard, source=body.source, tts=body.tts), media_type="text/event-stream")


# 章节：每个章节是一个可以进去的世界。以后根据生活和梦境生成的新世界也加在这里。
CHAPTERS = [
    {"id": "cabin", "title": "第一章 · 小木屋", "desc": "在梦幻星球的草原上散步，去湖边的小木屋找噜噜。", "unlock_hint": ""},
    {"id": "voyage", "title": "第二章 · 星际旅行", "desc": "噜噜悄悄准备了一架 UFO，想带你飞出星球去看星星。",
     "unlock_hint": "先在第一章里走进小木屋找到噜噜"},
]


def _unlocked():
    u = store.get_state("unlocked_chapters", ["cabin"])
    if "voyage" not in u and store.get_state("last_visit_ts"):  # 以前已经进过小木屋的，直接算解锁
        u = u + ["voyage"]
        store.set_state("unlocked_chapters", u)
    return u


def unlock_chapter(cid):
    u = _unlocked()
    if cid not in u:
        store.set_state("unlocked_chapters", u + [cid])


@app.get("/api/chapters")
async def chapters():
    u = _unlocked()
    out = [{**c, "unlocked": c["id"] in u} for c in CHAPTERS]
    for i, w in enumerate(store.list_worlds()):
        out.append({"id": f"w{w['id']}", "title": f"第{len(CHAPTERS) + i + 1}章 · {w['title']}", "desc": w["recipe"].get("intro", ""),
                    "unlock_hint": "", "unlocked": True, "completed": bool(w.get("completed")), "world_id": w["id"]})
    return out


# ---------- 梦境日记 ----------
class DreamIn(BaseModel):
    content: str
    title: str = ""


@app.get("/api/dreams")
async def dreams():
    return store.list_dreams(200)


@app.post("/api/dreams")
async def add_dream(d: DreamIn):
    if not d.content.strip():
        raise HTTPException(400, "空的梦")
    return {"id": store.add_dream(d.content.strip(), d.title.strip()[:20])}


@app.delete("/api/dreams/{dream_id}")
async def del_dream(dream_id: int):
    store.delete_dream(dream_id)
    return {"ok": True}


# ---------- 编织出来的世界 ----------
_weaving = asyncio.Lock()


@app.get("/api/worlds")
async def worlds():
    return store.list_worlds()


@app.get("/api/worlds/{world_id}")
async def get_world(world_id: int):
    w = store.get_world(world_id)
    if not w:
        raise HTTPException(404, "没有这个世界")
    return w


@app.post("/api/worlds/weave")
async def weave_now():
    if _weaving.locked():
        raise HTTPException(409, "噜噜正在编织中，稍等一下")
    async with _weaving:
        try:
            wid, recipe = await weaver.weave()
        except Exception as e:
            raise HTTPException(502, f"编织失败：{e}")
    return {"id": wid, "recipe": recipe}


@app.post("/api/worlds/{world_id}/complete")
async def complete_world(world_id: int):
    store.complete_world(world_id)
    brain.bump_closeness(3)
    return {"ok": True, "closeness": store.get_state("closeness", 10.0)}


@app.delete("/api/worlds/{world_id}")
async def del_world(world_id: int):
    store.delete_world(world_id)
    return {"ok": True}


@app.post("/api/visit")
async def visit(tts: bool = False):
    """在 3D 星球里，对方走进了小木屋。"""
    unlock_chapter("voyage")  # 第一次在小木屋见到噜噜，就解锁第二章
    if time.time() - store.get_state("last_visit_ts", 0) < 120:
        return Response(status_code=204)
    store.set_state("last_visit_ts", time.time())
    note = ("对方刚刚穿过梦幻星球的草原，走进了你的小木屋来找你（你正坐在屋里的粉色坐垫上）。"
            "惊喜又自然地迎接，可以说说你刚才在屋里做什么。只说一两句。")
    return StreamingResponse(_reply_stream(None, note, tts=tts), media_type="text/event-stream")


@app.post("/api/hello")
async def hello(tts: bool = False):
    """打开页面时：第一次见面、或很久没聊时，主动打招呼。"""
    last = store.last_message()
    if last is None:
        note = "这是你们第一次见面。用温暖、自然的方式介绍自己，并好奇地问问对方怎么称呼。"
    elif time.time() - last["ts"] > 2 * 3600:
        note = ("对方隔了一段时间又打开了聊天窗口。结合现在的时间、你们之前聊过的事、你记得的事和你这段时间的日记，"
                "主动打个招呼：可以表达想念、关心对方之前提到的事，或者分享你攒着想说的小事。只说一两句。")
    else:
        return Response(status_code=204)
    return StreamingResponse(_reply_stream(None, note, tts=tts), media_type="text/event-stream")


@app.post("/api/nudge")
async def nudge(tts: bool = False):
    """对方开着窗口却很久没说话时，TA 轻轻开口（每段沉默最多一次）。"""
    last = store.last_message()
    last_user = store.last_user_ts()
    if not last or not last_user or store.get_state("last_nudge_ts", 0) > last_user:
        return Response(status_code=204)
    minutes = int((time.time() - last["ts"]) // 60)
    if minutes < 8:
        return Response(status_code=204)
    store.set_state("last_nudge_ts", time.time())
    note = (f"对方开着聊天窗口，但已经 {minutes} 分钟没说话了，可能在忙。轻轻地说一句：可以分享你刚刚在做或在想的小事，"
            "或者温柔地关心一下（比如提醒喝水、休息），不要打扰太多，不要追问。只说一两句。")
    return StreamingResponse(_reply_stream(None, note, tts=tts), media_type="text/event-stream")


class EventIn(BaseModel):
    note: str
    tts: bool = False


@app.post("/api/event")
async def scene_event(body: EventIn):
    """3D 世界里发生的事（出门坐 UFO、飞过某颗星球……），让 TA 自然地说一两句。"""
    note = body.note.strip()[:400]
    if not note:
        raise HTTPException(400, "空事件")
    return StreamingResponse(_reply_stream(None, note + " 只说一两句，口语、生动。", tts=body.tts), media_type="text/event-stream")


@app.post("/api/pet")
async def pet():
    today = time.strftime("%Y-%m-%d")
    pets = store.get_state("pets", {})
    count = (pets.get("count", 0) if pets.get("date") == today else 0) + 1
    store.set_state("pets", {"date": today, "count": count})
    brain.bump_closeness(0.2)
    return {"count": count, "closeness": store.get_state("closeness", 10.0)}


@app.get("/api/diary")
async def diary():
    return store.list_diary(100)


@app.post("/api/diary/now")
async def diary_now():
    """手动让 TA 写一篇日记（调试/好奇时用）。"""
    try:
        return await brain.inner_life()
    except Exception as e:
        raise HTTPException(502, str(e))


@app.get("/api/status")
async def status():
    persona = store.get_persona()
    first = store.first_message_ts()
    return {
        "persona": {"name": persona["name"], "user_name": persona["user_name"], "voice": persona.get("voice")},
        "mood": store.get_state("mood", {"emotion": "calm", "intensity": 0.5}),
        "closeness": store.get_state("closeness", 10.0),
        "days": int((time.time() - first) // 86400) + 1 if first else 0,
        "message_count": store.message_count(),
        "memory_count": len(store.list_memories()),
        "activity": store.get_state("activity", ""),
    }


@app.get("/api/history")
async def history(limit: int = 60):
    return store.recent_messages(limit)


@app.delete("/api/history")
async def clear_history():
    await _consolidate_bg(force=True)  # 清空前先把还没整理的对话存进记忆
    store.clear_messages()
    return {"ok": True}


# ---------- 人设 ----------
@app.get("/api/persona")
async def get_persona():
    return store.get_persona()


@app.put("/api/persona")
async def put_persona(p: dict):
    merged = store.get_persona()
    merged.update(p)
    store.save_persona(merged)
    return merged


class ImportIn(BaseModel):
    text: str
    who: str
    user_name: str
    save_facts: bool = True


@app.post("/api/persona/from_chat")
async def persona_from_chat(body: ImportIn):
    if len(body.text.strip()) < 50:
        raise HTTPException(400, "聊天记录太短了")
    try:
        data = await brain.persona_from_chat(body.text, body.who, body.user_name)
    except Exception as e:
        raise HTTPException(502, f"分析失败：{e}")
    return data  # 先返回给前端预览，确认后再 PUT /api/persona 保存


class FactsIn(BaseModel):
    facts: list[str]


@app.post("/api/memories/bulk")
async def add_facts(body: FactsIn):
    for f in body.facts:
        if f.strip():
            store.add_memory(f.strip(), "fact", 3)
    return {"ok": True}


# ---------- 记忆 ----------
@app.get("/api/memories")
async def memories():
    return {"memories": store.list_memories(), "episodes": store.list_episodes()}


class MemIn(BaseModel):
    content: str
    importance: int = 3


@app.post("/api/memories")
async def add_memory(m: MemIn):
    store.add_memory(m.content, "fact", m.importance)
    return {"ok": True}


@app.put("/api/memories/{mem_id}")
async def edit_memory(mem_id: int, m: MemIn):
    store.update_memory(mem_id, m.content, m.importance)
    return {"ok": True}


@app.delete("/api/memories/{mem_id}")
async def del_memory(mem_id: int):
    store.delete_memory(mem_id)
    return {"ok": True}


@app.delete("/api/episodes/{ep_id}")
async def del_episode(ep_id: int):
    store.delete_episode(ep_id)
    return {"ok": True}


@app.post("/api/memories/consolidate")
async def consolidate_now():
    await _consolidate_bg(force=True)
    return {"ok": True}


# ---------- 声音 ----------
class TTSIn(BaseModel):
    text: str
    voice: str | None = None


@app.get("/api/voices")
async def voices():
    return {"voices": voice.voices(), "local_tts": voice.use_local_tts(), "local_asr": voice.use_local_asr()}


@app.post("/api/tts")
async def tts(body: TTSIn):
    try:
        audio = await voice.tts(body.text, body.voice or store.get_persona().get("voice"))
    except Exception as e:
        raise HTTPException(503, str(e))
    return Response(audio, media_type="audio/wav" if audio[:4] == b"RIFF" else "audio/mpeg")


@app.post("/api/asr")
async def asr(file: UploadFile = File(...)):
    try:
        return await voice.asr(await file.read(), file.filename or "speech.wav")
    except Exception as e:
        raise HTTPException(503, str(e))


# ---------- 页面 ----------
@app.get("/")
async def index():
    return FileResponse(STATIC / "index.html")


@app.get("/world")
async def world():
    return FileResponse(STATIC / "world.html")


from .scene_routes import attach_scene_routes
attach_scene_routes(app)

app.mount("/static", StaticFiles(directory=STATIC), name="static")


if __name__ == "__main__":
    import uvicorn
    print(f"打开 http://127.0.0.1:{PORT}")
    uvicorn.run(app, host="127.0.0.1", port=PORT)
