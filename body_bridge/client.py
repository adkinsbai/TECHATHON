"""Companion HTTP 契约；不在桥接器中保存聊天或配置密钥。"""
import codecs
import json

import httpx


async def parse_sse(source):
    """处理任意字节分片、UTF-8、CRLF；跳过损坏及过大的事件。"""
    decoder = codecs.getincrementaldecoder('utf-8')('replace')
    buffer, event, data = '', 'message', []
    size, dropping = 0, False
    async for chunk in source:
        buffer += decoder.decode(chunk)
        while '\n' in buffer:
            line, buffer = buffer.split('\n', 1)
            line = line.rstrip('\r')
            if not line:
                if data and not dropping:
                    try:
                        payload = json.loads('\n'.join(data))
                        if isinstance(payload, dict):
                            yield event, payload
                    except (ValueError, TypeError):
                        pass
                event, data, size, dropping = 'message', [], 0, False
            elif not dropping and not line.startswith(':'):
                field, _, value = line.partition(':')
                value = value.removeprefix(' ')
                size += len(line)
                if size > 1024 * 1024:
                    data, dropping = [], True
                elif field == 'event':
                    event = value
                elif field == 'data':
                    data.append(value)
        if len(buffer) > 1024 * 1024:
            buffer, data, dropping = '', [], True


class CompanionClient:
    def __init__(self, url='http://127.0.0.1:8765', http=None):
        self.owned = http is None
        # Windows 注册表代理也会被 httpx 自动读取；本机 Companion 必须直连。
        self.http = http or httpx.AsyncClient(base_url=url.rstrip('/'),
                                             timeout=httpx.Timeout(30, connect=5), trust_env=False)

    async def close(self):
        if self.owned:
            await self.http.aclose()

    async def status(self, data):
        response = await self.http.post('/api/body/status', json=data, timeout=5)
        response.raise_for_status()
        return response.json()

    async def touch(self, data):
        async with self.http.stream('POST', '/api/body/event', json=data, timeout=90) as response:
            response.raise_for_status()
            async for event, payload in parse_sse(response.aiter_bytes()):
                if event == 'error':
                    raise RuntimeError(payload.get('message', '接触回应失败'))

    async def asr(self, wav):
        response = await self.http.post('/api/body/asr', files={'file': ('body.wav', wav, 'audio/wav')}, timeout=30)
        response.raise_for_status()
        heard = response.json()
        if not isinstance(heard, dict):
            raise ValueError('语音识别返回格式错误')
        return heard

    async def chat(self, heard):
        data = {'text': heard.get('text', ''), 'voice_emotion': heard.get('emotion', ''),
                'voice_event': heard.get('event', ''), 'source': 'body'}
        async with self.http.stream('POST', '/api/chat', json=data, timeout=90) as response:
            response.raise_for_status()
            async for event, payload in parse_sse(response.aiter_bytes()):
                if event == 'error':
                    raise RuntimeError(payload.get('message', '对话失败'))

    async def tts(self, text):
        async with self.http.stream('POST', '/api/body/tts', json={'text': text}, timeout=30) as response:
            response.raise_for_status()
            data = bytearray()
            async for chunk in response.aiter_bytes():
                data.extend(chunk)
                if len(data) > 8 * 1024 * 1024:
                    raise ValueError('语音文件过大')
            return bytes(data)

    async def events(self):
        # 不携带 Last-Event-ID：重连后只接收新事件，避免播出旧回复。
        async with self.http.stream('GET', '/api/body/stream', timeout=30) as response:
            response.raise_for_status()
            async for event in parse_sse(response.aiter_bytes()):
                yield event
