"""Local physical-body events for the existing Companion persona and store."""
import asyncio
from collections import deque
import datetime as dt
import json
import time
from typing import Annotated, Literal
import uuid

from fastapi import HTTPException, Request
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, StrictBool


def sse(name, data, event_id=None):
    prefix = f"id: {event_id}\n" if event_id is not None else ""
    return prefix + f"event: {name}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


class BodyHub:
    """One device, one dialogue lock; no independent character or database."""

    def __init__(self, store, clock=time.time):
        self.store = store
        self.clock = clock
        self.turn_lock = asyncio.Lock()
        self.event_lock = asyncio.Lock()
        self._status = {"connected": False, "phase": "offline", "pressed": False}
        self._last_seen = None
        self._listeners = set()
        self._recent = deque(maxlen=256)
        self._commands = deque(maxlen=16)
        self._sequence = 0

    def settings(self):
        saved = self.store.get_state("body_settings", {})
        volume = saved.get("volume", 10) if isinstance(saved, dict) else 10
        if type(volume) is not int or not 0 <= volume <= 100:
            volume = 10
        return {"volume": volume}

    async def set_volume(self, volume):
        if type(volume) is not int or not 0 <= volume <= 100:
            raise ValueError("volume must be an integer from 0 to 100")
        self.store.set_state("body_settings", {"volume": volume})
        await self.publish("status", self.snapshot())

    def snapshot(self):
        fresh = self._last_seen is not None and self.clock() - self._last_seen <= 8
        result = {**self._status, "connected": bool(fresh and self._status.get("connected")),
                  "last_seen": self._last_seen, "settings": self.settings()}
        if not result["connected"]:
            result.update(phase="offline", pressed=False)
        return result

    async def update_status(self, status):
        self._status = {"phase": "idle", "pressed": False, **status}
        self._last_seen = self.clock()
        if not status.get("connected"):
            self._commands.clear()
        await self.publish("status", self.snapshot())

    def command(self, command):
        if not self.snapshot()["connected"]:
            raise HTTPException(409, "实体尚未连接")
        if len(self._commands) >= self._commands.maxlen:
            raise HTTPException(409, "操作正在排队，请稍后再试")
        self._commands.append({"command": command, "id": uuid.uuid4().hex})

    def take_commands(self):
        commands = list(self._commands) if self.snapshot()["connected"] else []
        self._commands.clear()
        return commands

    async def publish(self, name, data):
        # Called on the one ASGI loop; no await inside the critical section.
        self._sequence += 1
        item = {"id": self._sequence, "event": name, "data": data}
        self._recent.append(item)
        for queue in tuple(self._listeners):
            if queue.full():
                queue.get_nowait()
            queue.put_nowait(item)
        return item

    async def subscribe(self, last_id=None):
        queue = asyncio.Queue(maxsize=256)
        if last_id is not None:
            for item in self._recent:
                if item["id"] > last_id:
                    queue.put_nowait(item)
        self._listeners.add(queue)
        return queue

    def unsubscribe(self, queue):
        self._listeners.discard(queue)

    async def remember_event(self, event):
        async with self.event_lock:
            events = self.store.get_state("body_events", [])
            if any(e.get("event_id") == event["event_id"] for e in events):
                return False
            events = (events + [{**event, "ts": self.clock()}])[-100:]
            self.store.set_state("body_events", events)
            today = dt.datetime.fromtimestamp(self.clock()).strftime("%Y-%m-%d")
            pets = self.store.get_state("pets", {})
            count = pets.get("count", 0) if pets.get("date") == today else 0
            self.store.set_state("pets", {"date": today, "count": count + 1})
            self.store.set_state("closeness", min(100.0, self.store.get_state("closeness", 10.0) + .2))
            return True

    def physical_context(self):
        events = [e for e in self.store.get_state("body_events", [])
                  if self.clock() - e.get("ts", 0) < 86400][-5:]
        if not events:
            return ""
        lines = [f"{dt.datetime.fromtimestamp(e['ts']):%H:%M} 实体压力传感器检测到一次短按压（{e['duration']:.2f}秒）"
                 for e in events]
        return "真实身体记录（只代表局部按压）：" + "；".join(lines)

    async def relay(self, reply_impl, user_text=None, note=None, heard=None, source="web"):
        async with self.turn_lock:
            turn_id = uuid.uuid4().hex
            meta = {"turn_id": turn_id, "source": source}
            await self.publish("turn_start", {**meta, "ts": self.clock()})
            if user_text is not None:
                await self.publish("user", {**meta, "text": user_text, "ts": self.clock()})
            context = self.physical_context()
            combined = "\n".join(x for x in (note, context) if x) or None
            try:
                async for chunk in reply_impl(user_text=user_text, note=combined, heard=heard):
                    # Existing Companion yields a complete SSE event for each chunk.
                    name = None
                    data = []
                    for line in chunk.splitlines():
                        if line.startswith("event:"):
                            name = line[6:].strip()
                        elif line.startswith("data:"):
                            data.append(line[5:].strip())
                    if name in {"delta", "done", "error"}:
                        payload = json.loads("\n".join(data) or "{}")
                        await self.publish(name, {**payload, **meta, "ts": self.clock()})
                    yield chunk
            except asyncio.CancelledError:
                raise
            except Exception:
                message = "小暖暂时没有回复，请稍后再试"
                await self.publish("error", {**meta, "message": message})
                yield sse("error", {"message": message})
            finally:
                await self.publish("turn_end", {**meta, "ts": self.clock()})


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DeviceStatus(Input):
    connected: StrictBool
    phase: str = Field(default="idle", max_length=32)
    raw: int | None = Field(default=None, ge=0, le=4095)
    mv: int | None = Field(default=None, ge=0, le=5000)
    pressed: bool = False
    stats: dict = Field(default_factory=dict)
    error: str = Field(default="", max_length=500)
    tcp_port: int = Field(default=5000, ge=1, le=65535)


class Settings(Input):
    volume: Annotated[int, Field(strict=True, ge=0, le=100)]


class Command(Input):
    command: Literal["record_start", "record_stop", "calibrate"]


class PhysicalEvent(Input):
    event_id: str = Field(min_length=1, max_length=128)
    kind: Literal["touch"]
    duration: float = Field(ge=0, le=15, allow_inf_nan=False)
    strength: float = Field(ge=0, le=1, allow_inf_nan=False)


def attach_body_routes(app, hub, reply_stream):
    @app.get("/api/body/status")
    async def status():
        return hub.snapshot()

    @app.post("/api/body/status")
    async def heartbeat(body: DeviceStatus):
        await hub.update_status(body.model_dump())
        return {"settings": hub.settings(), "commands": hub.take_commands()}

    @app.patch("/api/body/settings")
    async def settings(body: Settings):
        await hub.set_volume(body.volume)
        return hub.snapshot()

    @app.post("/api/body/command")
    async def command(body: Command):
        hub.command(body.command)
        return {"ok": True}

    @app.post("/api/body/event")
    async def physical_event(body: PhysicalEvent):
        if not await hub.remember_event(body.model_dump()):
            return Response(status_code=204)
        note = (f"你的实体身体的压力传感器刚检测到一次持续 {body.duration:.2f} 秒的短按压。"
                "你只知道有局部接触，无法由此知道对方的情绪或位置。自然、简短地回应这次触碰，只说一两句。")
        return StreamingResponse(reply_stream(note=note, source="body"), media_type="text/event-stream")

    @app.get("/api/body/stream")
    async def stream(request: Request):
        try:
            last_id = int(request.headers["last-event-id"]) if "last-event-id" in request.headers else None
        except ValueError:
            last_id = None
        queue = await hub.subscribe(last_id)

        async def generate():
            try:
                yield sse("hello", {"status": hub.snapshot(), "settings": hub.settings()})
                while not await request.is_disconnected():
                    try:
                        item = await asyncio.wait_for(queue.get(), timeout=3)
                        yield sse(item["event"], item["data"], item["id"])
                    except asyncio.TimeoutError:
                        yield ": heartbeat\n\n"
            finally:
                hub.unsubscribe(queue)

        return StreamingResponse(generate(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
