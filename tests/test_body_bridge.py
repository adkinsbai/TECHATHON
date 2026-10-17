import asyncio
import io
import json
import struct
import time
import unittest
import wave

from body_bridge.pressure import Pressure
from body_bridge.audio import chunks, decode_audio, scale_pcm, wav_bytes
from body_bridge.client import CompanionClient, parse_sse
from body_bridge.runtime import Bridge


class PressureTests(unittest.TestCase):
    def test_board_fsr_falling_polarity_from_saturated_rest(self):
        sensor = Pressure(calibration_samples=3, debounce=.1)
        for at, raw in [(0, 4095), (.1, 4095), (.2, 4095)]:
            self.assertIsNone(sensor.update(raw, at))
        self.assertIsNone(sensor.update(2500, .3))
        self.assertEqual(sensor.update(2500, .41), 'press')
        self.assertAlmostEqual(sensor.strength, 1595 / 4095)
        self.assertIsNone(sensor.update(4090, .5))
        self.assertEqual(sensor.update(4090, .61), 'release')

    def test_optional_sensor_requires_high_stable_rest(self):
        sensor = Pressure(calibration_samples=3, debounce=.1, rest_min=2500)
        for at, raw in [(0, 1000), (.1, 1001), (.2, 999)]:
            sensor.update(raw, at)
        self.assertIsNone(sensor.baseline)
        for at, raw in [(.3, 4095), (.4, 300), (.5, 4000)]:
            sensor.update(raw, at)
        self.assertIsNone(sensor.baseline)
        for at, raw in [(.6, 4095), (.7, 4090), (.8, 4093)]:
            sensor.update(raw, at)
        self.assertEqual(sensor.baseline, 4093)

    def calibrated(self):
        sensor = Pressure(calibration_samples=3, debounce=.1)
        for at, raw in [(0, 1000), (.1, 1002), (.2, 998)]:
            self.assertIsNone(sensor.update(raw, at))
        return sensor

    def test_rest_calibration_bounce_and_hysteresis(self):
        sensor = self.calibrated()
        self.assertEqual(sensor.baseline, 1000)
        self.assertIsNone(sensor.update(700, .3))
        self.assertIsNone(sensor.update(1000, .35))
        self.assertIsNone(sensor.update(700, .5))
        self.assertEqual(sensor.update(700, .61), 'press')
        self.assertIsNone(sensor.update(880, .7))
        self.assertTrue(sensor.pressed)
        self.assertIsNone(sensor.update(1000, .8))
        self.assertEqual(sensor.update(1000, .91), 'release')

    def test_reset_requires_new_rest_baseline(self):
        sensor = self.calibrated()
        sensor.reset()
        self.assertIsNone(sensor.baseline)
        self.assertFalse(sensor.pressed)


class AudioTests(unittest.TestCase):
    def test_ten_percent_is_exact_and_zero_mutes(self):
        pcm = struct.pack('<4h', 10000, -10000, 32760, -32760)
        self.assertEqual(struct.unpack('<4h', scale_pcm(pcm, 10)), (1000, -1000, 3276, -3276))
        self.assertEqual(scale_pcm(pcm, 0), bytes(8))

    def test_last_packet_is_zero_padded(self):
        blocks = list(chunks(b'a' * 4100))
        self.assertEqual([len(x) for x in blocks], [4096, 4096])
        self.assertEqual(blocks[-1], b'aaaa' + bytes(4092))

    def test_decode_wav_resamples_stereo_and_capture_wav_is_mono(self):
        wav = wav_bytes(struct.pack('<h', 10000) * 240)
        with wave.open(io.BytesIO(wav)) as reader:
            self.assertEqual((reader.getnchannels(), reader.getframerate()), (1, 24000))
        decoded = decode_audio(wav)
        self.assertEqual(len(decoded), 240 * 4)
        self.assertEqual(struct.unpack('<2h', decoded[:4]), (10000, 10000))


class ClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_owned_client_bypasses_machine_proxies_for_loopback(self):
        import httpx
        from unittest.mock import patch
        original = httpx.AsyncClient
        with patch('body_bridge.client.httpx.AsyncClient', wraps=original) as factory:
            client = CompanionClient('http://127.0.0.1:18765')
            try:
                self.assertIs(factory.call_args.kwargs.get('trust_env'), False)
            finally:
                await client.close()

    async def test_injected_client_keeps_its_proxy_and_lifecycle_configuration(self):
        import httpx
        async with httpx.AsyncClient(trust_env=True, transport=httpx.MockTransport(
                lambda request: httpx.Response(200))) as injected:
            client = CompanionClient(http=injected)
            self.assertIs(client.http, injected)
            await client.close()
            self.assertFalse(injected.is_closed)

    async def test_touch_drains_sse_and_propagates_error_with_chat_timeout(self):
        import httpx
        requests = []
        class Fragments(httpx.AsyncByteStream):
            async def __aiter__(self):
                yield b'event: delta\ndata: {"text":"hello"}\n\n'
                yield b'event: error\ndata: {"message":"touch failed"}\n\n'
        def handle(request):
            requests.append(request)
            return httpx.Response(200, stream=Fragments())
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle), base_url='http://127.0.0.1:8765') as http:
            client = CompanionClient(http=http)
            with self.assertRaisesRegex(RuntimeError, 'touch failed'):
                await client.touch({'event_id': 'a', 'kind': 'touch', 'duration': .2, 'strength': .4})
            self.assertEqual(requests[0].extensions['timeout']['read'], 90)

    async def test_local_voice_unavailable_never_falls_back_to_generic_voice_routes(self):
        import httpx
        paths = []
        def handle(request):
            paths.append(request.url.path)
            return httpx.Response(503, json={'detail': '本地模型未就绪'})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle), base_url='http://127.0.0.1:8765') as http:
            client = CompanionClient(http=http)
            with self.assertRaises(httpx.HTTPStatusError):
                await client.asr(wav_bytes(bytes(480)))
            with self.assertRaises(httpx.HTTPStatusError):
                await client.tts('你好')
        self.assertEqual(paths, ['/api/body/asr', '/api/body/tts'])

    async def test_fragmented_utf8_crlf_and_malformed_sse(self):
        raw = ('event: done\r\ndata: {"text":"暖"}\r\n\r\n'
               'event: done\ndata: {broken}\n\n'
               ': beat\n\nevent: delta\ndata: {"text":\ndata: "好"}\n\n').encode()
        async def source():
            for offset in range(0, len(raw), 2):
                yield raw[offset:offset + 2]
        events = [event async for event in parse_sse(source())]
        self.assertEqual(events, [('done', {'text': '暖'}), ('delta', {'text': '好'})])

    async def test_http_contracts_and_chat_stream_is_drained(self):
        import httpx
        calls = []
        def handle(request):
            calls.append(request)
            if request.url.path.endswith('/asr'):
                self.assertIn(b'name="file"', request.content)
                return httpx.Response(200, json={'text': '你好', 'emotion': 'calm', 'event': 'speech'})
            if request.url.path == '/api/chat':
                return httpx.Response(200, content=b'event: done\ndata: {"text":"ok"}\n\n')
            return httpx.Response(200, content=b'audio')
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle), base_url='http://127.0.0.1:8765') as http:
            client = CompanionClient(http=http)
            heard = await client.asr(wav_bytes(bytes(480)))
            self.assertEqual(calls[-1].url.path, '/api/body/asr')
            await client.chat(heard)
            self.assertEqual(json.loads(calls[-1].content), {'text': '你好', 'voice_emotion': 'calm', 'voice_event': 'speech', 'source': 'body'})
            self.assertEqual(await client.tts('你好'), b'audio')
            self.assertEqual(calls[-1].url.path, '/api/body/tts')
            self.assertEqual(json.loads(calls[-1].content), {'text': '你好'})


class FakeLink:
    def __init__(self):
        self.connected = True
        self.conn_id = 1
        self.last_rx = time.monotonic()
        self.force = {}
        self.stats = {}
        self.bind_error = ''
        self.sent = []
        self.on_mic = None
    def set_mode(self, mode):
        self.sent.append(('mode', mode))
        return True
    def send_audio(self, pcm):
        self.sent.append(('audio', pcm))
        return True


class FakeClient:
    def __init__(self):
        self.calls = []
    async def touch(self, data): self.calls.append(('touch', data))
    async def asr(self, wav):
        self.calls.append(('asr', wav))
        return {'text': '听到了', 'emotion': '', 'event': ''}
    async def chat(self, heard): self.calls.append(('chat', heard))
    async def tts(self, text):
        self.calls.append(('tts', text))
        return wav_bytes(struct.pack('<h', 10000) * 24)
    async def status(self, status):
        self.calls.append(('status', status))
        return {'settings': {'volume': 7}, 'commands': []}


class RuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.link, self.client = FakeLink(), FakeClient()
        self.bridge = Bridge(self.link, self.client, drain_seconds=0)
        await self.bridge.poll()
    async def asyncTearDown(self):
        await self.bridge.close()

    async def test_short_touch_has_unique_event_and_no_asr(self):
        await self.bridge.press(1)
        await self.bridge.release(1.2)
        await self.bridge.wait_work()
        first = self.client.calls[0][1]
        self.assertEqual(first['kind'], 'touch')
        self.assertAlmostEqual(first['duration'], .2)
        await self.bridge.press(2)
        await self.bridge.release(2.2)
        await self.bridge.wait_work()
        self.assertNotEqual(first['event_id'], self.client.calls[1][1]['event_id'])
        self.assertFalse(any(c[0] == 'asr' for c in self.client.calls))

    async def test_long_release_runs_wav_asr_then_same_companion_chat(self):
        await self.bridge.press(1)
        self.bridge.feed_mic(bytes(4800))
        await self.bridge.release(2)
        await self.bridge.wait_work()
        self.assertEqual([c[0] for c in self.client.calls], ['asr', 'chat'])
        self.assertEqual(self.client.calls[0][1][:4], b'RIFF')

    async def test_busy_advisory_clears_when_current_turn_finishes(self):
        entered, finish = asyncio.Event(), asyncio.Event()
        async def chat(heard):
            entered.set()
            await finish.wait()
        self.client.chat = chat
        await self.bridge.press(1)
        self.bridge.feed_mic(bytes(4800))
        await self.bridge.release(2)
        await entered.wait()
        await self.bridge.press(3)
        self.assertEqual(self.bridge.error, '正在处理上一句话，请稍候')
        finish.set()
        await self.bridge.wait_work()
        self.assertEqual(self.bridge.phase, 'idle')
        self.assertEqual(self.bridge.error, '')

    async def test_real_asr_failure_replaces_busy_advisory_and_is_preserved(self):
        entered, finish = asyncio.Event(), asyncio.Event()
        async def asr(wav):
            entered.set()
            await finish.wait()
            raise RuntimeError('本地识别失败')
        self.client.asr = asr
        await self.bridge.press(1)
        self.bridge.feed_mic(bytes(4800))
        await self.bridge.release(2)
        await entered.wait()
        await self.bridge.press(3)
        finish.set()
        await self.bridge.wait_work()
        self.assertEqual(self.bridge.error, '本地识别失败')

    async def test_busy_press_does_not_overwrite_a_real_error(self):
        finish = asyncio.Event()
        self.bridge.work = asyncio.create_task(finish.wait())
        self.bridge.error = '板子发送超时'
        try:
            await self.bridge.press()
            self.assertEqual(self.bridge.error, '板子发送超时')
        finally:
            finish.set()
            await self.bridge.wait_work()

    async def test_connection_recovery_clears_busy_advisory_but_preserves_real_error(self):
        self.bridge.error = '正在处理上一句话，请稍候'
        self.link.connected = False
        await self.bridge.poll()
        self.assertEqual(self.bridge.error, '')
        self.bridge.error = '板子发送超时'
        self.link.connected = True
        self.link.conn_id += 1
        await self.bridge.poll()
        self.assertEqual(self.bridge.error, '板子发送超时')

    async def test_raw_pressure_samples_never_call_companion_without_contact(self):
        for index in range(50):
            self.link.force = {'raw': 1000 + index % 3, 'mv': 805, 'at': time.time() + index * .00001}
            await self.bridge.poll(now=index * .1)
        self.assertEqual(self.bridge.phase, 'idle')
        self.assertEqual(self.client.calls, [])

    async def test_debounced_pressure_contact_reaches_touch_endpoint(self):
        self.bridge.pressure = Pressure(calibration_samples=3, debounce=.1)
        values = [(0, 4095), (.1, 4095), (.2, 4095),
                  (.3, 2500), (.41, 2500), (.5, 4090), (.61, 4090)]
        for index, (at, raw) in enumerate(values):
            self.link.force = {'raw': raw, 'mv': 1000, 'at': time.time() + index * .00001}
            await self.bridge.poll(now=at)
        await self.bridge.wait_work()
        self.assertEqual([c[0] for c in self.client.calls], ['touch'])
        self.assertGreater(self.client.calls[0][1]['strength'], 0)

    async def feed_two(self, values):
        for index, (at, raw, raw2) in enumerate(values):
            self.link.force = {'raw': raw, 'mv': 1000, 'raw2': raw2, 'mv2': 1000, 'at': time.time() + index * .00001}
            await self.bridge.poll(now=at)
        await self.bridge.wait_work()

    async def test_second_sensor_touch_is_tagged_with_its_sensor_number(self):
        self.bridge.pressure = Pressure(calibration_samples=3, debounce=.1)
        self.bridge.pressure2 = Pressure(calibration_samples=3, debounce=.1, rest_min=2500)
        await self.feed_two([(0, 4095, 4095), (.1, 4095, 4095), (.2, 4095, 4095),
                             (.3, 4095, 2500), (.41, 4095, 2500), (.5, 4095, 4090), (.61, 4095, 4090)])
        self.assertEqual([c[0] for c in self.client.calls], ['touch'])
        self.assertEqual(self.client.calls[0][1]['sensor'], 2)
        self.assertGreater(self.client.calls[0][1]['strength'], 0)

    async def test_first_sensor_touch_still_reports_sensor_one(self):
        self.bridge.pressure = Pressure(calibration_samples=3, debounce=.1)
        self.bridge.pressure2 = Pressure(calibration_samples=3, debounce=.1, rest_min=2500)
        await self.feed_two([(0, 4095, 4095), (.1, 4095, 4095), (.2, 4095, 4095),
                             (.3, 2500, 4095), (.41, 2500, 4095), (.5, 4090, 4095), (.61, 4090, 4095)])
        self.assertEqual(self.client.calls[0][1]['sensor'], 1)

    async def test_unplugged_floating_second_sensor_never_calibrates_or_triggers(self):
        self.bridge.pressure = Pressure(calibration_samples=3, debounce=.1)
        self.bridge.pressure2 = Pressure(calibration_samples=3, debounce=.1, rest_min=2500)
        noise = [1200, 3900, 300, 2600, 50, 4095, 900, 3100, 1800, 200]
        await self.feed_two([(i * .1, 4095, noise[i % len(noise)]) for i in range(60)])
        self.assertIsNone(self.bridge.pressure2.baseline)
        self.assertEqual(self.client.calls, [])
        self.assertEqual(self.bridge.phase, 'idle')
        sensors = self.bridge.snapshot()['sensors']
        self.assertEqual([s['calibrated'] for s in sensors], [True, False])

    def two_hands(self):
        self.bridge.pressure = Pressure(calibration_samples=3, debounce=.1)
        self.bridge.pressure2 = Pressure(calibration_samples=3, debounce=.1, rest_min=2500)
        return [(0, 4095, 4095), (.1, 4095, 4095), (.2, 4095, 4095)]

    async def test_right_then_left_together_is_a_hug_and_drops_the_recording(self):
        rest = self.two_hands()
        await self.feed_two(rest + [(.3, 2500, 4095), (.41, 2500, 4095),      # 右手按下：开始录音
                                    (.6, 2500, 2500), (.71, 2500, 2500),      # 0.3 秒后左手也按下：抱抱
                                    (2.0, 4095, 4095), (2.11, 4095, 4095)])   # 两只手都松开
        self.assertEqual([c[0] for c in self.client.calls], ['touch'])
        hug = self.client.calls[0][1]
        self.assertEqual(hug['kind'], 'hug')
        self.assertNotIn('sensor', hug)
        self.assertAlmostEqual(hug['duration'], 2.11 - .41, places=2)
        self.assertGreater(hug['strength'], 0)
        self.assertIn(('mode', 2), self.link.sent)
        self.assertEqual(self.link.sent[-1], ('mode', 0))

    async def test_left_then_right_together_is_a_hug(self):
        rest = self.two_hands()
        await self.feed_two(rest + [(.3, 4095, 2500), (.41, 4095, 2500),
                                    (.9, 2500, 2500), (1.01, 2500, 2500),
                                    (1.5, 4095, 4095), (1.61, 4095, 4095)])
        self.assertEqual([(c[0], c[1]['kind']) for c in self.client.calls], [('touch', 'hug')])
        self.assertNotIn(('mode', 2), self.link.sent)

    async def test_left_hand_never_records_even_when_held(self):
        rest = self.two_hands()
        await self.feed_two(rest + [(.3, 4095, 2500), (.41, 4095, 2500), (3.0, 4095, 4090), (3.11, 4095, 4090)])
        self.assertEqual(len(self.client.calls), 1)
        touch = self.client.calls[0][1]
        self.assertEqual((touch['kind'], touch['sensor']), ('touch', 2))
        self.assertAlmostEqual(touch['duration'], 3.11 - .41, places=2)
        self.assertNotIn(('mode', 2), self.link.sent)

    async def test_late_left_touch_does_not_interrupt_talking(self):
        rest = self.two_hands()
        await self.feed_two(rest + [(.3, 2500, 4095), (.41, 2500, 4095),
                                    (2.0, 2500, 2500), (2.11, 2500, 2500), (2.5, 2500, 4090), (2.61, 2500, 4090)])
        self.assertEqual(self.bridge.phase, 'recording')
        self.assertEqual(self.client.calls, [])

    async def test_holding_left_then_pressing_right_later_starts_talking(self):
        rest = self.two_hands()
        await self.feed_two(rest + [(.3, 4095, 2500), (.41, 4095, 2500), (2.0, 2500, 2500), (2.11, 2500, 2500)])
        self.assertEqual(self.bridge.phase, 'recording')
        self.bridge.feed_mic(bytes(4800))
        await self.feed_two([(3.0, 4095, 2500), (3.11, 4095, 2500), (3.5, 4095, 4095), (3.61, 4095, 4095)])
        self.assertEqual([c[0] for c in self.client.calls], ['asr', 'chat'])

    async def test_old_single_sensor_frames_still_work(self):
        self.bridge.pressure = Pressure(calibration_samples=3, debounce=.1)
        values = [(0, 4095), (.1, 4095), (.2, 4095), (.3, 2500), (.41, 2500), (.5, 4090), (.61, 4090)]
        for index, (at, raw) in enumerate(values):
            self.link.force = {'raw': raw, 'mv': 1000, 'at': time.time() + index * .00001}
            await self.bridge.poll(now=at)
        await self.bridge.wait_work()
        self.assertEqual(self.client.calls[0][1]['sensor'], 1)
        self.assertFalse(self.bridge.snapshot()['sensors'][1]['reported'])

    async def test_capture_cap_sends_once_and_waits_for_release(self):
        self.bridge.pressure.pressed = True
        await self.bridge.press(1)
        self.bridge.feed_mic(bytes(1000000))
        self.assertLessEqual(len(self.bridge.capture), 15 * 24000 * 2)
        await self.bridge.poll(now=16.1)
        await self.bridge.wait_work()
        await self.bridge.press(17)
        self.assertNotEqual(self.bridge.phase, 'recording')
        self.bridge.pressure.pressed = False
        await self.bridge.release(18)
        await self.bridge.press(19)
        self.assertEqual(self.bridge.phase, 'recording')
        self.assertEqual([c[0] for c in self.client.calls].count('asr'), 1)

    async def test_browser_record_can_restart_after_cap_without_sensor_release(self):
        commands = [{'command': 'record_start'}]
        async def status(data):
            batch = list(commands)
            commands.clear()
            return {'settings': {'volume': 10}, 'commands': batch}
        self.client.status = status
        await self.bridge.heartbeat()
        self.bridge.feed_mic(bytes(4800))
        self.bridge.started -= 16
        await self.bridge.poll()
        await self.bridge.wait_work()
        commands.append({'command': 'record_start'})
        await self.bridge.heartbeat()
        self.assertEqual(self.bridge.phase, 'recording')

    async def test_browser_stop_does_not_unblock_a_physically_held_capped_press(self):
        self.bridge.pressure.pressed = True
        await self.bridge.press(1)
        self.bridge.feed_mic(bytes(4800))
        await self.bridge.poll(now=16.1)
        await self.bridge.wait_work()
        async def status(data):
            return {'commands': ['record_stop', 'record_start']}
        self.client.status = status
        await self.bridge.heartbeat()
        self.assertNotEqual(self.bridge.phase, 'recording')
        self.assertTrue(self.bridge.blocked_until_release)

    async def test_disconnect_discards_capture_and_queued_speech(self):
        await self.bridge.press(1)
        self.bridge.feed_mic(bytes(4800))
        self.bridge.on_event('turn_start', {'turn_id': 'old'})
        self.bridge.on_event('done', {'turn_id': 'old', 'text': 'old'})
        self.link.connected = False
        await self.bridge.poll()
        self.assertEqual(self.bridge.capture, b'')
        self.assertTrue(self.bridge.speech.empty())
        self.link.connected = True
        self.link.conn_id += 1
        await self.bridge.poll()
        self.bridge.on_event('done', {'turn_id': 'old', 'text': 'old'})
        self.assertTrue(self.bridge.speech.empty())

    async def test_stale_connection_reports_disconnected(self):
        self.link.last_rx = time.monotonic() - 9
        await self.bridge.poll()
        self.assertFalse(self.bridge.snapshot()['connected'])

    async def test_port_conflict_fails_instead_of_claiming_healthy_runtime(self):
        self.link.bind_error = '测试端口已被占用'
        with self.assertRaisesRegex(OSError, '端口'):
            await self.bridge.poll()

    async def test_new_connection_does_not_accept_an_old_turn_completion(self):
        self.bridge.on_event('turn_start', {'turn_id': 'old'})
        self.link.conn_id += 1
        await self.bridge.poll()
        self.bridge.on_event('done', {'turn_id': 'old', 'text': '旧话'})
        self.assertTrue(self.bridge.speech.empty())

    async def test_done_dedupes_and_speech_queue_is_bounded(self):
        for i in range(8):
            self.bridge.on_event('turn_start', {'turn_id': str(i), 'source': 'web'})
            self.bridge.on_event('done', {'turn_id': str(i), 'text': 'hello'})
            self.bridge.on_event('done', {'turn_id': str(i), 'text': 'hello'})
        self.assertEqual(self.bridge.speech.qsize(), 2)

    async def test_playback_scales_padding_and_idle_after_drain(self):
        await self.bridge.play('hello', self.bridge.epoch)
        audio = [data for kind, data in self.link.sent if kind == 'audio']
        self.assertEqual(len(audio), 1)
        self.assertEqual(len(audio[0]), 4096)
        self.assertEqual(struct.unpack('<2h', audio[0][:4]), (1000, 1000))
        self.assertEqual(self.link.sent[-1], ('mode', 0))

    async def test_default_playback_drain_covers_board_dma(self):
        default = Bridge(self.link, self.client)
        self.assertGreaterEqual(default.drain_seconds, .4)

    async def test_send_failure_is_bounded_and_does_not_stay_speaking(self):
        import threading
        release_sender = threading.Event()
        finished = threading.Event()
        attempts = []
        def stuck(pcm):
            attempts.append(len(pcm))
            try:
                release_sender.wait()
                return True
            finally:
                finished.set()
        self.link.send_audio = stuck
        self.bridge.send_timeout = .5
        try:
            # 完成必须依赖发送超时；工作线程在断言结束前始终保持阻塞。
            await asyncio.wait_for(self.bridge.play('hello', self.bridge.epoch), timeout=5)
            self.assertEqual(attempts, [4096])  # 部分发送超时不重试音频帧。
            self.assertEqual(self.bridge.phase, 'idle')
            self.assertEqual(self.bridge.error, '板子发送超时')
        finally:
            release_sender.set()
            await asyncio.to_thread(finished.wait, 1)

    async def test_press_waits_for_inflight_audio_before_switching_to_recording(self):
        import threading
        sending = threading.Event()
        def slow_send(pcm):
            sending.set()
            time.sleep(.04)
            self.link.sent.append(('audio', pcm))
            return True
        self.link.send_audio = slow_send
        self.bridge.play_task = asyncio.create_task(self.bridge.play('hello', self.bridge.epoch))
        while not sending.is_set():
            await asyncio.sleep(.001)
        await self.bridge.press()
        await asyncio.sleep(.06)
        self.assertEqual(self.bridge.phase, 'recording')
        self.assertEqual(self.link.sent[-1], ('mode', 2))

    async def test_old_pending_microphone_callback_cannot_enter_new_capture(self):
        pending = []
        class Scheduler:
            def is_closed(self): return False
            def call_soon_threadsafe(self, callback, *args): pending.append((callback, args))
        self.bridge.loop = Scheduler()
        await self.bridge.press(1)
        self.bridge.mic_callback(bytes(800))
        await self.bridge.release(1.2)
        await self.bridge.wait_work()
        await self.bridge.press(2)
        for callback, args in pending:
            callback(*args)
        self.assertEqual(self.bridge.capture, b'')

    async def test_speech_worker_survives_connection_reset_during_chat(self):
        gate = asyncio.Event()
        async def chat(heard): await gate.wait()
        self.client.chat = chat
        await self.bridge.press(1)
        self.bridge.feed_mic(bytes(4800))
        await self.bridge.release(2)
        self.bridge.on_event('turn_start', {'turn_id': 'pending'})
        self.bridge.on_event('done', {'turn_id': 'pending', 'text': 'reply'})
        worker = asyncio.create_task(self.bridge.speech_loop())
        try:
            await asyncio.sleep(.01)
            self.link.connected = False
            await self.bridge.poll()
            await asyncio.sleep(.01)
            self.assertFalse(worker.done())
        finally:
            worker.cancel()
            await asyncio.gather(worker, return_exceptions=True)

    async def test_heartbeat_volume_and_string_or_object_commands(self):
        async def status(data):
            self.assertIn('tcp_port', data)
            return {'settings': {'volume': 12}, 'commands': ['record_start', {'command': 'record_stop'}]}
        self.client.status = status
        await self.bridge.heartbeat()
        self.assertEqual(self.bridge.volume, 12)
        self.assertNotEqual(self.bridge.phase, 'recording')


if __name__ == '__main__':
    unittest.main()
