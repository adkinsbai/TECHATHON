"""按下录音，短触与松手提交；原始样本不进入对话。"""
import asyncio
import time
import uuid

from .audio import MAX_CAPTURE_BYTES, wav_bytes


class Capture:
    def feed_mic(self, payload):
        # Link 在接收线程回调；只把有界字节投递回所属事件循环。
        if self.phase != 'recording':
            return
        usable = min(len(payload) & ~1, MAX_CAPTURE_BYTES - len(self.capture))
        if usable > 0:
            self.capture.extend(payload[:usable])

    def mic_callback(self, payload):
        if self.loop is not None and not self.loop.is_closed():
            # 限制待处理回调数量；网络异常时不积压无限音频。
            if self.pending_mic < 16:
                epoch, capture_id = self.epoch, self.capture_id
                self.pending_mic += 1
                self.loop.call_soon_threadsafe(self._mic_on_loop, bytes(payload[:4096]), epoch, capture_id)

    def _mic_on_loop(self, payload, epoch, capture_id):
        self.pending_mic -= 1
        if epoch == self.epoch and capture_id == self.capture_id:
            self.feed_mic(payload)

    async def press(self, now=None):
        if not self.fresh() or self.blocked_until_release or self.phase == 'recording':
            return
        if self.work and not self.work.done():
            self.error = '正在处理上一句话，请稍候'
            return
        self.play_token += 1
        if self.play_task:
            self.play_task.cancel()
            await asyncio.gather(self.play_task, return_exceptions=True)
        self.clear_speech()
        self.capture = bytearray()
        self.capture_id += 1
        self.started = time.monotonic() if now is None else now
        self.peak_strength = self.pressure.strength
        self.phase = 'recording'
        try:
            await self.send(self.link.set_mode, 2)
        except Exception as exc:
            self.capture.clear()
            self.phase, self.error = 'idle', str(exc)[:240]

    async def release(self, now=None, capped=False):
        if self.blocked_until_release and not capped:
            self.blocked_until_release = False
            return
        if self.phase != 'recording':
            return
        duration = max(0, (time.monotonic() if now is None else now) - self.started)
        pcm, self.capture = bytes(self.capture), bytearray()
        self.phase = 'thinking'
        self.blocked_until_release = capped
        try:
            await self.send(self.link.set_mode, 0)
        except Exception as exc:
            self.phase, self.error = 'disconnected', str(exc)[:240]
            return
        epoch = self.epoch
        touch = {'event_id': uuid.uuid4().hex, 'kind': 'touch',
                 'duration': round(duration, 3), 'strength': round(self.peak_strength, 4)}
        self.work = asyncio.create_task(self._submit(pcm, touch, epoch))

    async def _submit(self, pcm, touch, epoch):
        try:
            if touch['duration'] < .35:
                await asyncio.wait_for(self.client.touch(touch), 12)
            elif pcm:
                heard = await asyncio.wait_for(self.client.asr(wav_bytes(pcm)), 35)
                if self.epoch == epoch and self.fresh() and str(heard.get('text', '')).strip():
                    await asyncio.wait_for(self.client.chat(heard), 95)
            else:
                self.error = '没有收到录音，请重试'
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.error = str(exc)[:240]
        finally:
            if epoch == self.epoch and self.phase == 'thinking':
                self.phase = 'idle' if self.fresh() else 'disconnected'

    async def wait_work(self):
        if self.work:
            await self.work
