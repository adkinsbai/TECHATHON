import asyncio
import json
import unittest

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


class BodyHttpTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.assertIsNotNone(BodyHub, "Companion physical body HTTP extension is missing")
        self.store = MemoryStore()
        self.hub = BodyHub(self.store)
        self.replies = 0

        async def reply(user_text=None, note=None, heard=None, source="web"):
            self.replies += 1
            self.assertEqual(source, "body")
            self.assertIn("按压", note)
            yield sse("done", {"text": "I felt that touch", "emotion": "happy"})

        self.app = FastAPI()
        attach_body_routes(self.app, self.hub, reply)
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


if __name__ == "__main__":
    unittest.main()
