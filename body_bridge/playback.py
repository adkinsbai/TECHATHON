"""半双工、可打断且有界的实体播放。"""
import asyncio
import time

from .audio import CHUNK_BYTES, RATE, chunks, decode_audio, scale_pcm


class Playback:
    async def send(self, method, value):
        generation = self.link.conn_id
        operation = asyncio.create_task(asyncio.to_thread(method, value))
        try:
            result = await asyncio.wait_for(asyncio.shield(operation), self.send_timeout)
            if not result:
                raise ConnectionError('板子发送失败')
            if generation != self.link.conn_id:
                raise ConnectionError('板子连接已更新')
        except TimeoutError:
            # 关闭发生超时的旧 socket，阻止后台 sendall 迟到写入。
            if generation == self.link.conn_id:
                sock = getattr(self.link, 'client', None)
                if sock is not None:
                    sock.close()
                    self.link.client = None
            raise TimeoutError('板子发送超时') from None
        except asyncio.CancelledError:
            # 先等待已开始的发送结束，再允许下一次 REC；取消线程 Future 不能撤回 socket 写入。
            try:
                await asyncio.wait_for(asyncio.shield(operation), self.send_timeout)
            except Exception:
                if generation == self.link.conn_id:
                    sock = getattr(self.link, 'client', None)
                    if sock is not None:
                        sock.close()
                        self.link.client = None
            raise

    async def play(self, text, epoch):
        if not self.fresh() or epoch != self.epoch or self.phase in ('recording', 'thinking'):
            return
        self.phase = 'speaking'
        token = self.play_token = self.play_token + 1
        try:
            data = await asyncio.wait_for(self.client.tts(text), 35)
            pcm = await asyncio.wait_for(asyncio.to_thread(decode_audio, data), 10)
            if not self.fresh() or epoch != self.epoch or token != self.play_token:
                return
            await self.send(self.link.set_mode, 1)
            deadline = time.monotonic()
            for packet in chunks(pcm):
                if not self.fresh() or epoch != self.epoch or token != self.play_token:
                    return
                await self.send(self.link.send_audio, scale_pcm(packet, self.volume))
                deadline += CHUNK_BYTES / (RATE * 4)
                await asyncio.sleep(max(0, deadline - time.monotonic()))
            await asyncio.sleep(self.drain_seconds)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.error = str(exc)[:240]
        finally:
            if epoch == self.epoch and token == self.play_token and self.phase == 'speaking':
                if self.fresh():
                    try:
                        await self.send(self.link.set_mode, 0)
                    except Exception as exc:
                        self.error = str(exc)[:240]
                self.phase = 'idle' if self.fresh() else 'disconnected'

    async def speech_loop(self):
        while True:
            text, epoch = await self.speech.get()
            try:
                # done 可能早于发起 /api/chat 的流关闭；等待同一轮处理结束。
                if self.work and not self.work.done():
                    try:
                        await asyncio.shield(self.work)
                    except asyncio.CancelledError:
                        if asyncio.current_task().cancelling():
                            raise
                        continue
                self.play_task = asyncio.create_task(self.play(text, epoch))
                try:
                    await self.play_task
                except asyncio.CancelledError:
                    if asyncio.current_task().cancelling():
                        raise
            finally:
                self.play_task = None
                self.speech.task_done()
