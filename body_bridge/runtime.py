"""实体连接生命周期与 Companion 状态协调。"""
import asyncio
from collections import deque
import time

from .capture import Capture
from .playback import Playback
from .pressure import Pressure


class Bridge(Capture, Playback):
    def __init__(self, link, client, volume=10, port=5000, drain_seconds=.4):
        if not isinstance(volume, int) or not 0 <= volume <= 100:
            raise ValueError('音量须为 0..100')
        self.link, self.client = link, client
        self.volume, self.port = volume, port
        self.drain_seconds, self.send_timeout = drain_seconds, 6
        self.pressure = Pressure()
        # 第二个传感器（GPIO9）可选：没接时静置读数不稳，永远不会校准，也就不会触发。
        self.pressure2 = Pressure(rest_min=2500)
        self.active_sensor = 1
        self.phase, self.error = 'disconnected', ''
        self.epoch, self.conn_id = 0, None
        self.was_connected = False
        self.capture = bytearray()
        self.capture_id = 0
        self.started, self.peak_strength = 0, 0
        self.blocked_until_release = False
        self.last_force = None
        self.speech = asyncio.Queue(maxsize=2)
        self.turns, self.seen = {}, deque(maxlen=256)
        self.work = self.play_task = None
        self.play_token = 0
        self.loop, self.pending_mic = None, 0
        self.tasks = []
        link.on_mic = self.mic_callback

    def fresh(self):
        last_rx = getattr(self.link, 'last_rx', 0)
        return bool(self.link.connected and last_rx and time.monotonic() - last_rx <= 8)

    def clear_speech(self):
        while not self.speech.empty():
            self.speech.get_nowait()
            self.speech.task_done()

    async def reset_connection(self, connected):
        self.clear_busy_advisory()
        self.epoch += 1
        self.play_token += 1
        self.capture.clear()
        self.clear_speech()
        self.turns.clear()
        self.pressure.reset()
        self.pressure2.reset()
        self.active_sensor = 1
        self.last_force = None
        self.blocked_until_release = False
        active = [task for task in (self.work, self.play_task) if task and not task.done()]
        for task in active:
            task.cancel()
        if active:
            await asyncio.gather(*active, return_exceptions=True)
        self.work = self.play_task = None
        self.phase = 'calibrating' if connected else 'disconnected'
        if connected:
            try:
                await self.send(self.link.set_mode, 0)
            except Exception as exc:
                self.error = str(exc)[:240]

    async def poll(self, now=None):
        if getattr(self.link, 'bind_error', ''):
            raise OSError(self.link.bind_error)
        now = time.monotonic() if now is None else now
        connected = self.fresh()
        if connected != self.was_connected or self.link.conn_id != self.conn_id:
            self.was_connected, self.conn_id = connected, self.link.conn_id
            await self.reset_connection(connected)
        if not connected:
            return
        force = dict(self.link.force)
        if force and force.get('at') != self.last_force and time.time() - force.get('at', 0) <= 2:
            self.last_force = force['at']
            events = [(1, self.pressure.update(force['raw'], now))]
            if force.get('raw2') is not None:
                events.append((2, self.pressure2.update(force['raw2'], now)))
            self.peak_strength = max(self.peak_strength, self.active_pressure().strength)
            if self.phase == 'calibrating' and self.pressure.baseline is not None:
                self.phase = 'idle'
            for sensor, event in events:
                if event == 'press':
                    await self.press(now, sensor=sensor)
                elif event == 'release' and sensor == self.active_sensor:
                    # 只有正在用的那个传感器松手才结束；另一个传感器的松手不影响。
                    await self.release(now)
        if self.phase == 'recording' and now - self.started >= 15:
            await self.release(now, capped=True)

    def active_pressure(self):
        return self.pressure2 if self.active_sensor == 2 else self.pressure

    def on_event(self, event, data):
        turn = str(data.get('turn_id', ''))
        if event == 'turn_start' and turn and self.fresh():
            self.turns[turn] = self.epoch
            if len(self.turns) > 256:
                self.turns.pop(next(iter(self.turns)))
        if event == 'done' and turn:
            epoch = self.turns.pop(turn, None)
            text = data.get('text', '')
            if epoch != self.epoch or turn in self.seen or not self.fresh():
                return
            self.seen.append(turn)
            if not isinstance(text, str) or not text.strip() or self.phase == 'recording':
                return
            if self.speech.full():
                self.speech.get_nowait()
                self.speech.task_done()
            self.speech.put_nowait((text[:12000], epoch))
        if event in ('error', 'turn_end'):
            self.turns.pop(turn, None)

    def snapshot(self):
        force = dict(self.link.force)
        stats = dict(self.link.stats)
        stats['rx_age_seconds'] = round(max(0, time.monotonic() - self.link.last_rx), 2) if self.link.last_rx else None
        stats['calibrated'] = self.pressure.baseline is not None
        sensors = [{'sensor': 1, 'raw': force.get('raw'), 'pressed': self.pressure.pressed,
                    'calibrated': self.pressure.baseline is not None, 'reported': 'raw' in force},
                   {'sensor': 2, 'raw': force.get('raw2'), 'pressed': self.pressure2.pressed,
                    'calibrated': self.pressure2.baseline is not None, 'reported': 'raw2' in force}]
        return {'connected': self.fresh(), 'phase': self.phase,
                'raw': force.get('raw'), 'mv': force.get('mv'),
                'pressed': self.pressure.pressed or self.pressure2.pressed, 'sensors': sensors, 'stats': stats,
                'error': self.error or getattr(self.link, 'bind_error', ''), 'tcp_port': self.port}

    async def heartbeat(self):
        response = await self.client.status(self.snapshot())
        volume = response.get('settings', {}).get('volume')
        if isinstance(volume, int) and 0 <= volume <= 100:
            self.volume = volume
        for item in response.get('commands', [])[:16]:
            command = item.get('command') if isinstance(item, dict) else item
            if command == 'calibrate':
                if self.phase == 'recording':
                    self.capture.clear()
                    await self.send(self.link.set_mode, 0)
                self.pressure.reset()
                self.pressure2.reset()
                self.blocked_until_release = False
                if self.phase not in ('thinking', 'speaking'):
                    self.phase = 'calibrating' if self.fresh() else 'disconnected'
            elif command == 'record_start':
                await self.press()
            elif command == 'record_stop':
                await self.release()

    async def heartbeat_loop(self):
        while True:
            try:
                await self.heartbeat()
            except Exception as exc:
                self.error = str(exc)[:240]
            await asyncio.sleep(2)

    async def events_loop(self):
        delay = 1
        while True:
            try:
                async for event, data in self.client.events():
                    delay = 1
                    self.on_event(event, data)
            except Exception as exc:
                self.error = str(exc)[:240]
            # 流重连不重放，也不保留未完成轮次。
            self.turns.clear()
            await asyncio.sleep(delay)
            delay = min(10, delay * 2)

    async def run(self):
        self.loop = asyncio.get_running_loop()
        self.tasks = [asyncio.create_task(worker()) for worker in
                      (self.heartbeat_loop, self.events_loop, self.speech_loop)]
        try:
            while True:
                await self.poll()
                for task in self.tasks:
                    if task.done():
                        task.result()
                        raise RuntimeError('桥接后台任务停止')
                await asyncio.sleep(.04)
        finally:
            await self.close()

    async def close(self):
        self.link.on_mic = None
        self.epoch += 1
        active = {task for task in self.tasks + [self.work, self.play_task] if task and not task.done()}
        for task in active:
            task.cancel()
        await asyncio.gather(*active, return_exceptions=True)
        self.capture.clear()
        self.clear_speech()
        if self.fresh():
            try:
                await self.send(self.link.set_mode, 0)
            except Exception:
                pass
        self.phase = 'disconnected'
