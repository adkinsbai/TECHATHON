import asyncio
import json
import io
import unittest
import wave

import httpx
from fastapi import FastAPI

try:
    from companion_extension.body_runtime import BodyHub, attach_body_routes
except ModuleNotFoundError:
    BodyHub = attach_body_routes = None


class MemoryStore:
    def __init__(self):
        self.state = {}

    def get_state(self, key, default=None):
        return self.state.get(key, default)

    def set_state(self, key, value):
        self.state[key] = value


def sse(name, data):
    return f"event: {name}\ndata: {json.dumps(data)}\n\n"


class BodyRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.assertIsNotNone(BodyHub, "Companion physical body event runtime is missing")
        self.now = 100.0
        self.store = MemoryStore()
        self.hub = BodyHub(self.store, clock=lambda: self.now)

    async def online(self):
        await self.hub.update_status({"connected": True, "phase": "idle", "raw": 4095})

    async def test_default_volume_is_ten_and_settings_persist(self):
        self.assertEqual(self.hub.settings()["volume"], 10)
        await self.hub.set_volume(0)
        self.assertEqual(BodyHub(self.store).settings()["volume"], 0)

    async def test_stale_device_never_owns_audio(self):
        await self.online()
        self.assertTrue(self.hub.snapshot()["connected"])
        self.now += 8.1
        self.assertFalse(self.hub.snapshot()["connected"])
        self.assertFalse(self.hub.snapshot()["pressed"])
        self.assertEqual(self.hub.snapshot()["phase"], "offline")

    async def test_commands_are_one_shot_and_not_replayed_after_disconnect(self):
        await self.online()
        self.hub.command("record_start")
        self.assertEqual(self.hub.take_commands()[0]["command"], "record_start")
        self.assertEqual(self.hub.take_commands(), [])

    async def test_expired_commands_do_not_start_recording_on_restored_heartbeat(self):
        await self.online()
        self.hub.command("record_start")
        self.now += 11
        self.assertFalse(self.hub.snapshot()["connected"])
        await self.hub.update_status({"connected": True})
        self.assertEqual(self.hub.take_commands(), [])
        self.hub.command("record_start")
        await self.hub.update_status({"connected": False})
        self.assertEqual(self.hub.take_commands(), [])

    async def test_physical_event_deduplication_survives_restart(self):
        event = {"event_id": "touch-1", "kind": "touch", "duration": .15, "strength": .3}
        self.assertTrue(await self.hub.remember_event(event))
        self.assertFalse(await self.hub.remember_event(event))
        restarted = BodyHub(self.store)
        self.assertFalse(await restarted.remember_event(event))
        self.assertEqual(self.store.state["pets"]["count"], 1)
        self.assertAlmostEqual(self.store.state["closeness"], 10.2)
        self.assertIn("按压", self.hub.physical_context())

    async def test_broadcast_has_source_identity_and_ordered_turn(self):
        queue = await self.hub.subscribe()

        async def reply(user_text=None, note=None, heard=None):
            self.assertEqual(user_text, "hello")
            yield sse("start", {})
            yield sse("delta", {"text": "hi"})
            yield sse("done", {"text": "hi", "emotion": "happy", "intensity": .5, "closeness": 11})

        chunks = [c async for c in self.hub.relay(reply, user_text="hello", source="body")]
        self.assertEqual(len(chunks), 3)
        events = []
        while not queue.empty():
            events.append(queue.get_nowait())
        names = [e["event"] for e in events]
        self.assertEqual(names, ["turn_start", "user", "delta", "done", "turn_end"])
        self.assertEqual(events[1]["data"]["text"], "hello")
        self.assertEqual(len({e["data"]["turn_id"] for e in events}), 1)
        self.assertTrue(all(e["data"]["source"] == "body" for e in events))
        self.hub.unsubscribe(queue)

    async def test_two_input_channels_do_not_generate_simultaneously(self):
        active = 0
        maximum = 0

        async def reply(user_text=None, note=None, heard=None):
            nonlocal active, maximum
            active += 1
            maximum = max(maximum, active)
            await asyncio.sleep(.02)
            yield sse("done", {"text": user_text})
            active -= 1

        async def run(source):
            return [x async for x in self.hub.relay(reply, user_text=source, source=source)]

        await asyncio.gather(run("web"), run("body"))
        self.assertEqual(maximum, 1)

    async def test_exception_releases_turn_lock_and_reports_error(self):
        queue = await self.hub.subscribe()

        async def broken(**kwargs):
            raise RuntimeError("unavailable")
            yield ""

        chunks = [x async for x in self.hub.relay(broken, source="body")]
        self.assertTrue(any("event: error" in x for x in chunks))
        self.assertFalse(self.hub.turn_lock.locked())
        names = []
        while not queue.empty():
            names.append(queue.get_nowait()["event"])
        self.assertIn("error", names)
        self.assertEqual(names[-1], "turn_end")

    async def test_replay_excludes_already_consumed_events(self):
        first = await self.hub.publish("status", {"connected": False})
        second = await self.hub.publish("status", {"connected": True})
        queue = await self.hub.subscribe(last_id=first["id"])
        self.assertEqual(queue.get_nowait()["id"], second["id"])
        self.assertTrue(queue.empty())


class FakeVoice:
    """仿 companion/app/voice.py：本地 SenseVoice 识别 + 微软晓伊合成。"""
    DEFAULT_VOICE = "edge:zh-CN-XiaoyiNeural|+0%|+0Hz"

    def __init__(self):
        self.ready = True
        self.tts_ok = True
        self.calls = []

    def local_asr_ready(self):
        return self.ready

    def _local_asr(self, audio):
        self.calls.append("local_asr")
        return {"text": "本地识别", "emotion": "平静", "event": ""}

    async def tts_wav(self, text, voice=None):
        self.calls.append(("tts_wav", voice or self.DEFAULT_VOICE))
        if not self.tts_ok:
            raise RuntimeError("微软语音连续失败")
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(24000)
            wav.writeframes(b"\x00\x00" * 200)
        return buffer.getvalue()


class BodyHttpTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.assertIsNotNone(BodyHub, "Companion physical body HTTP extension is missing")
        self.store = MemoryStore()
        self.hub = BodyHub(self.store)
        self.voice = FakeVoice()
        self.replies = 0

        async def reply(user_text=None, note=None, heard=None, source="web"):
            self.replies += 1
            self.assertEqual(source, "body")
            self.assertIn("按压", note)
            yield sse("done", {"text": "I felt that touch", "emotion": "happy"})

        self.app = FastAPI()
        attach_body_routes(self.app, self.hub, reply, voice=self.voice)
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url="http://127.0.0.1")

    async def asyncTearDown(self):
        if hasattr(self, "client"):
            await self.client.aclose()

    async def test_volume_is_validated_and_default_is_ten(self):
        result = (await self.client.get("/api/body/status")).json()
        self.assertEqual(result["settings"]["volume"], 10)
        for bad in [-1, 101, True, 1.5]:
            self.assertEqual((await self.client.patch("/api/body/settings", json={"volume": bad})).status_code, 422)
        result = await self.client.patch("/api/body/settings", json={"volume": 10})
        self.assertEqual(result.status_code, 200)

    async def test_heartbeat_delivers_commands_once(self):
        self.assertEqual((await self.client.post("/api/body/command", json={"command": "record_start"})).status_code, 409)
        await self.client.post("/api/body/status", json={"connected": True, "phase": "idle"})
        await self.client.post("/api/body/command", json={"command": "calibrate"})
        r = await self.client.post("/api/body/status", json={"connected": True})
        self.assertEqual(r.json()["commands"][0]["command"], "calibrate")
        r = await self.client.post("/api/body/status", json={"connected": True})
        self.assertEqual(r.json()["commands"], [])

    async def test_touch_is_typed_deduplicated_and_streamed(self):
        event = {"event_id": "physical-1", "kind": "touch", "duration": .1, "strength": .5}
        r = await self.client.post("/api/body/event", json=event)
        self.assertEqual(r.status_code, 200)
        self.assertIn("event: done", r.text)
        self.assertEqual((await self.client.post("/api/body/event", json=event)).status_code, 204)
        self.assertEqual(self.replies, 1)
        event["kind"] = "read_mind"
        self.assertEqual((await self.client.post("/api/body/event", json=event)).status_code, 422)

    async def test_body_audio_uses_local_asr_and_xiaoyi_tts(self):
        result = await self.client.post("/api/body/asr", files={"file": ("test.wav", b"test", "audio/wav")})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()["text"], "本地识别")
        result = await self.client.post("/api/body/tts", json={"text": "你好"})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.headers["content-type"], "audio/wav")
        self.assertEqual(self.voice.calls, ["local_asr", ("tts_wav", FakeVoice.DEFAULT_VOICE)])

    async def test_missing_asr_model_and_tts_failure_return_503(self):
        self.voice.ready = False
        self.voice.tts_ok = False
        self.assertEqual((await self.client.post("/api/body/asr", files={"file": ("test.wav", b"x")})).status_code, 503)
        self.assertEqual((await self.client.post("/api/body/tts", json={"text": "你好"})).status_code, 503)
        # 识别模型缺失时不调用任何识别；合成失败只尝试晓伊，不换别的声音。
        self.assertEqual(self.voice.calls, [("tts_wav", FakeVoice.DEFAULT_VOICE)])


if __name__ == "__main__":
    unittest.main()
