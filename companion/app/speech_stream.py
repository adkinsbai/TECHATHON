"""边说边合成：回复还在一个字一个字地生成时，每凑够一句就马上去合成这一句的语音，
按顺序把音频交给前端，前端一句接一句地播。不用等整段回复写完再合成。
"""
import asyncio
import re
import time
import uuid

from . import voice

_LEAD = re.compile(r"^\s*[\[【]\s*[A-Za-z]+[\s,，:：]*[\d.]*\s*[\]】]\s*")   # 开头的情绪标签 [shy 0.7]
_SENT_END = re.compile(r"[。！？!?…～~\n]")
_MIN_LEN = 6          # 太短的句子先攒着，和下一句一起合成（语气更连贯，请求也少）

# 合成好的音频临时放这里，前端用 /api/audio/{id} 取；5 分钟后清掉
_AUDIO: dict[str, tuple[float, bytes, str]] = {}


def get_audio(audio_id: str):
    item = _AUDIO.get(audio_id)
    return (item[1], item[2]) if item else None


def _cleanup():
    now = time.time()
    for k in [k for k, v in _AUDIO.items() if now - v[0] > 300]:
        _AUDIO.pop(k, None)


def _visible(raw: str) -> str:
    if re.match(r"^\s*[\[【][^\]】]*$", raw):        # 情绪标签还没写完
        return ""
    text = _LEAD.sub("", raw)
    return re.sub(r"<state>[\s\S]*$|<[a-z/]*$", "", text, flags=re.I)


def _speakable(text: str) -> str:
    text = re.sub(r"[（(][^）)]*[）)]", "", text)
    text = re.sub(r"[\U0001F000-\U0001FAFF☀-➿]", "", text)
    return re.sub(r"[~～]+", "，", text).strip()


class Speaker:
    def __init__(self, voice_id: str | None):
        self.voice_id = voice_id
        self.raw = ""
        self.done_upto = 0          # 可见文字里已经切出去的位置
        self.tasks: list[asyncio.Task] = []
        self.sent = 0               # 已经交给前端的句数

    def _start(self, sentence: str):
        text = _speakable(sentence)
        if len(re.sub(r"[\s，。！？!?、…,.]", "", text)) == 0:
            return
        self.tasks.append(asyncio.create_task(self._synth(text)))

    async def _synth(self, text: str):
        try:
            audio = await voice.tts(text, self.voice_id)
        except Exception as e:  # 这句合成不了就跳过（不换声音）
            print("这一句语音没合成出来：", e)
            return None
        _cleanup()
        audio_id = uuid.uuid4().hex
        mime = "audio/wav" if audio[:4] == b"RIFF" else "audio/mpeg"
        _AUDIO[audio_id] = (time.time(), audio, mime)
        return {"url": f"/api/audio/{audio_id}", "text": text}

    def feed(self, piece: str):
        self.raw += piece
        vis = _visible(self.raw)
        pending = vis[self.done_upto:]
        # 找到最后一个句尾，把它之前的部分切出去合成
        last = None
        for m in _SENT_END.finditer(pending):
            last = m.end()
        if last and len(pending[:last].strip()) >= _MIN_LEN:
            self._start(pending[:last])
            self.done_upto += last

    def finish(self):
        rest = _visible(self.raw)[self.done_upto:]
        self.done_upto = len(_visible(self.raw))
        if rest.strip():
            self._start(rest)

    def ready(self):
        """已经按顺序合成好的句子（前面的没好，后面的先好了也要等，保证顺序）。"""
        out = []
        while self.sent < len(self.tasks) and self.tasks[self.sent].done():
            res = self.tasks[self.sent].result()
            self.sent += 1
            if res:
                out.append({**res, "seq": self.sent})
        return out

    async def drain(self):
        while self.sent < len(self.tasks):
            res = await self.tasks[self.sent]
            self.sent += 1
            if res:
                yield {**res, "seq": self.sent}
