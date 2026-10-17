"""End-to-end verification on alternate ports using fake speech and a TCP board.

This does not touch the owner's database, microphone, speaker, USB or Wi-Fi config.
"""
import argparse
import asyncio
from array import array
import json
from pathlib import Path
import struct
import subprocess
import sys
import time
import uuid

import httpx

ROOT = Path(__file__).resolve().parents[1]
MAGIC = b"\xaa\x55\xaa\x55"


def frame(kind, payload):
    checksum = (sum(payload) + kind * 31 + len(payload)) & 65535
    return MAGIC + struct.pack("<BH", kind, len(payload)) + payload + struct.pack("<H", checksum)


class FakeBoard:
    def __init__(self, port):
        self.port, self.raw, self.raw2, self.mode = port, 4095, 4095, 0
        self.audio = bytearray()
        self.tasks = []
        self.closed = False

    async def start(self):
        for _ in range(100):
            try:
                self.reader, self.writer = await asyncio.open_connection("127.0.0.1", self.port)
                break
            except OSError:
                await asyncio.sleep(.1)
        else:
            raise AssertionError("bridge did not open its TCP listener")
        self.tasks = [asyncio.create_task(self.receive()), asyncio.create_task(self.send())]

    async def send(self):
        tick = 0
        while True:
            payload = frame(0x86, struct.pack("<HHHH", self.raw, round(self.raw / 4095 * 3190),
                                              self.raw2, round(self.raw2 / 4095 * 3190)))
            if tick % 5 == 0:
                payload += frame(0x82, bytes([self.mode, 0, 0, 0, 0, 0, 221, 0]))
            if self.mode == 2:
                payload += frame(0x81, struct.pack("<h", 2000) * 480)
            self.writer.write(payload)
            await self.writer.drain()
            tick += 1
            await asyncio.sleep(.02)

    async def receive(self):
        while True:
            header = await self.reader.readexactly(7)
            assert header[:4] == MAGIC
            kind, size = struct.unpack("<BH", header[4:])
            payload = await self.reader.readexactly(size)
            checksum, = struct.unpack("<H", await self.reader.readexactly(2))
            assert checksum == (sum(payload) + kind * 31 + size) & 65535
            if kind == 2:
                self.mode = payload[0]
            elif kind == 1:
                assert self.mode == 1, "audio sent outside playback mode"
                self.audio.extend(payload)

    async def stop(self):
        if self.closed:
            return
        self.closed = True
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        self.writer.close()
        await self.writer.wait_closed()


async def eventually(check, message, timeout=15):
    until = time.monotonic() + timeout
    while time.monotonic() < until:
        try:
            result = await check()
            if result:
                return result
        except (OSError, httpx.HTTPError):
            pass
        await asyncio.sleep(.1)
    raise AssertionError(message)


async def verify(args, output):
    fixture_log = (output / "fixture.log").open("w", encoding="utf-8")
    bridge_log = (output / "bridge.log").open("w", encoding="utf-8")
    fixture = subprocess.Popen([sys.executable, "-B", str(ROOT / "tools/body_fixture.py"),
                                "--source", str(args.source), "--root", str(output / "companion"),
                                "--port", str(args.api_port)], cwd=ROOT, stdout=fixture_log, stderr=subprocess.STDOUT)
    bridge = None
    board = None
    success = False
    async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{args.api_port}", timeout=5, trust_env=False) as http:
        async def state():
            r = await http.get("/api/body/status")
            r.raise_for_status()
            return r.json()

        async def fixture_stats():
            return (await http.get("/__fixture")).json()

        async def ready():
            if fixture.poll() is not None:
                raise RuntimeError("isolated fixture exited; inspect " + str(output / "fixture.log"))
            return (await state()).get("settings", {}).get("volume") == 10

        try:
            # Cold dependency imports on Windows were observed exceeding 60s.
            # Keep the wait bounded and report an exited child immediately.
            await eventually(ready, "isolated Companion fixture did not start", timeout=120)
            bridge = subprocess.Popen([sys.executable, "-B", "-m", "body_bridge", "--companion-url",
                                        f"http://127.0.0.1:{args.api_port}", "--port", str(args.tcp_port)],
                                       cwd=ROOT, stdout=bridge_log, stderr=subprocess.STDOUT)
            board = FakeBoard(args.tcp_port)
            await board.start()

            async def calibrated():
                s = await state()
                return s.get("connected") and s.get("stats", {}).get("calibrated")

            await eventually(calibrated, "board pressure calibration did not reach Companion")
            # Debounced short contact, then full physical response through the same dialogue backend.
            board.raw = 2500
            await asyncio.sleep(.24)
            board.raw = 4095

            async def touched():
                return (await fixture_stats())["tts_count"] >= 1 and len(board.audio) > 0 and board.mode == 0

            await eventually(touched, "short pressure did not produce physical response")
            amplitude = max(abs(x) for x in array("h", board.audio))
            assert 499 <= amplitude <= 501, f"expected 10% amplitude500, got {amplitude}"
            board.audio.clear()

            # Left hand (GPIO9): a touch is reported with its default site name, never recorded.

            async def both_calibrated():
                sensors = (await state()).get("sensors") or []
                return len(sensors) == 2 and all(s.get("calibrated") for s in sensors)

            await eventually(both_calibrated, "second pressure sensor did not calibrate")
            touches_before = (await fixture_stats())["tts_count"]
            board.raw2 = 2500
            await asyncio.sleep(.24)
            board.raw2 = 4095

            async def touched_site():
                result = await fixture_stats()
                return result["tts_count"] > touches_before and len(board.audio) > 0 and board.mode == 0

            await eventually(touched_site, "second sensor press did not produce physical response")
            assert "「左手」" in (await fixture_stats())["last_task"], "left-hand site missing from the model note"
            board.audio.clear()

            # Both hands pressed together is a hug: the right hand's recording is dropped, no ASR.
            hugs_before = (await fixture_stats())["tts_count"]
            board.raw = 2500
            await asyncio.sleep(.3)
            board.raw2 = 2500
            await asyncio.sleep(.6)
            board.raw = board.raw2 = 4095

            async def hugged():
                result = await fixture_stats()
                return result["tts_count"] > hugs_before and len(board.audio) > 0 and board.mode == 0

            await eventually(hugged, "two-hand hug did not produce physical response")
            stats = await fixture_stats()
            assert "抱抱" in stats["last_task"] and stats["asr_count"] == 0, "hug must reach the model without ASR"
            board.audio.clear()
            tts_base = (await fixture_stats())["tts_count"]

            # Hold a press, transmit microphone packets, release into ASR -> chat -> TTS.
            board.raw = 2400
            await asyncio.sleep(.9)
            board.raw = 4095

            async def utterance():
                result = await fixture_stats()
                return result["asr_count"] == 1 and result["tts_count"] > tts_base and len(board.audio) > 0 and board.mode == 0

            await eventually(utterance, "hold-release voice chain did not complete")
            stats = await fixture_stats()
            assert stats["last_audio"]["rate"] == 24000 and stats["last_audio"]["channels"] == 1
            assert stats["last_audio"]["width"] == 2 and stats["last_audio"]["frames"] > 8000
            history = (await http.get("/api/history")).json()
            assert any(m["role"] == "user" and "实体连接测试" in m["content"] for m in history)

            # A web-origin reply also routes to the entity, and zero really mutes.
            await http.patch("/api/body/settings", json={"volume": 0})
            await asyncio.sleep(2.2)
            board.audio.clear()
            response = await http.post("/api/chat", json={"text": "静音测试", "source": "web"})
            assert response.status_code == 200 and "event: done" in response.text

            async def muted_reply():
                return len(board.audio) > 0 and board.mode == 0

            await eventually(muted_reply, "web-origin reply did not reach the entity")
            assert max(abs(x) for x in array("h", board.audio)) == 0, "zero volume must mute"
            await http.patch("/api/body/settings", json={"volume": 10})

            # Disconnect while audio is active, rather than only after an idle turn.
            board.audio.clear()
            response = await http.post("/api/chat", json={"text": "断线恢复测试", "source": "web"})
            assert response.status_code == 200

            async def playing():
                return board.mode == 1 and len(board.audio) > 0

            await eventually(playing, "test did not reach active playback before disconnect")
            await board.stop()
            async def disconnected():
                return not (await state())["connected"]
            await eventually(disconnected, "disconnect was not reflected on Companion")
            board = FakeBoard(args.tcp_port)
            await board.start()
            await eventually(calibrated, "reconnected device did not recalibrate")
            await asyncio.sleep(.8)
            assert not board.audio, "old speech replayed after device reconnect"
            result = {"real_hardware": False, "pressure_touch": True, "left_hand_touch": True, "two_hand_hug": True,
                      "hold_release_asr_chat_tts": True,
                      "same_history": True, "default_volume": 10, "measured_test_pcm_amplitude": amplitude,
                      "web_reply_routes_to_body": True, "zero_mutes": True, "reconnect_discards_old_speech": True,
                      "disconnect_during_playback": True,
                      "api_port": args.api_port, "fixture_pid": fixture.pid, "fixture_root": str(output / "companion")}
            (output / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps(result, ensure_ascii=False))
            success = True
        finally:
            if board:
                await board.stop()
            if bridge:
                bridge.terminate()
                try:
                    bridge.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    bridge.kill()
            if not (success and args.keep_fixture):
                fixture.terminate()
                try:
                    fixture.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    fixture.kill()
            fixture_log.close()
            bridge_log.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--api-port", type=int, default=18765)
    parser.add_argument("--tcp-port", type=int, default=19500)
    parser.add_argument("--keep-fixture", action="store_true")
    args = parser.parse_args()
    output = ROOT / "runtime" / ("verification-" + uuid.uuid4().hex[:8])
    output.mkdir(parents=True)
    print("Verification artifacts: " + str(output), flush=True)
    asyncio.run(verify(args, output))


if __name__ == "__main__":
    main()
