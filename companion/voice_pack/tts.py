"""语音合成：微软神经语音（edge-tts）。噜噜的声音固定是“晓伊（活泼）”。

- 免费、不要 key、需要联网；文字会发给微软合成
- 失败会重试；重试也失败就抛 TTSError（调用方决定这句不出声），不会偷偷换成别的声音
- synthesize_wav() 直接给 WAV（24kHz 单声道 16 位），玩偶等只认 WAV 的设备用
"""
import asyncio
import io
import wave

import numpy as np

# 格式：edge:音色|语速|音调
DEFAULT_VOICE = "edge:zh-CN-XiaoyiNeural|+0%|+0Hz"
VOICES = {
    "edge:zh-CN-XiaoyiNeural|+0%|+0Hz": "晓伊（活泼）· 噜噜的声音",
    "edge:zh-CN-XiaoyiNeural|-5%|+12Hz": "晓伊（软萌）",
    "edge:zh-CN-XiaoxiaoNeural|+0%|+0Hz": "晓晓（温柔）",
    "edge:zh-CN-XiaoxiaoNeural|-3%|+10Hz": "晓晓（甜）",
    "edge:zh-TW-HsiaoChenNeural|+0%|+0Hz": "曉臻（台湾腔·软）",
    "edge:zh-TW-HsiaoYuNeural|+0%|+0Hz": "曉雨（台湾腔·温柔）",
    "edge:zh-CN-YunxiaNeural|+0%|+0Hz": "云夏（可爱男孩）",
}
WAV_RATE = 24000


class TTSError(RuntimeError):
    pass


def _parse(voice: str):
    spec = voice.split(":", 1)[1] if voice.startswith("edge:") else voice
    name, rate, pitch = (spec.split("|") + ["+0%", "+0Hz"])[:3]
    return name, rate, pitch


async def _once(text: str, voice: str) -> bytes:
    import edge_tts
    name, rate, pitch = _parse(voice)
    out = bytearray()
    async for chunk in edge_tts.Communicate(text[:1000], name, rate=rate, pitch=pitch).stream():
        if chunk["type"] == "audio":
            out += chunk["data"]
    if not out:
        raise TTSError("微软语音没有返回音频")
    return bytes(out)


async def synthesize(text: str, voice: str | None = None, tries: int = 4, timeout: float = 15) -> bytes:
    """文字 → mp3。网络偶尔抖动会自动重试。"""
    voice = voice or DEFAULT_VOICE
    err = None
    for i in range(tries):
        try:
            return await asyncio.wait_for(_once(text, voice), timeout=timeout)
        except Exception as e:
            err = e
            await asyncio.sleep(0.4 * (i + 1))
    raise TTSError(f"微软语音连续 {tries} 次失败：{err}")


def mp3_to_wav(mp3: bytes, sample_rate: int = WAV_RATE) -> bytes:
    import miniaudio
    d = miniaudio.decode(mp3, output_format=miniaudio.SampleFormat.SIGNED16, nchannels=1, sample_rate=sample_rate)
    pcm = np.frombuffer(d.samples.tobytes(), dtype=np.int16)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(pcm.tobytes())
    return buf.getvalue()


async def synthesize_wav(text: str, voice: str | None = None, sample_rate: int = WAV_RATE) -> bytes:
    """文字 → WAV（同一个声音）。"""
    mp3 = await synthesize(text, voice)
    return await asyncio.to_thread(mp3_to_wav, mp3, sample_rate)
