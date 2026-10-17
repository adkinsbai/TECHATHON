"""声音：伴侣后端对 voice_pack 的一层薄包装。

整条语音链路只有一条：本地 SenseVoice 听（离线，顺带听出情绪）→ DeepSeek 想 → 微软·晓伊说。
- 合成失败会重试，再失败就报错（这句不出声），不会换成别的声音
- 玩偶要 WAV，用 tts_wav()；网页要 mp3，用 tts()
（以前的本地 Kokoro 合成和智谱 GLM 已经去掉：声音不好听 / key 无效，链路越短越快。）
"""
import asyncio

import voice_pack as vp

from .config import MODELS_DIR

vp.configure(models_dir=MODELS_DIR)

DEFAULT_VOICE = vp.DEFAULT_VOICE   # 噜噜的声音：微软·晓伊（活泼）
VoiceError = vp.TTSError


def _pick(voice: str | None) -> str:
    # 老设置里可能存着 local:* / 智谱的音色名，统一换成晓伊
    return voice if voice and voice.startswith("edge:") else DEFAULT_VOICE


# ---------- 合成 ----------
def voices():
    return dict(vp.VOICES)


async def tts(text: str, voice: str | None = None, speed: float = 1.0) -> bytes:
    """文字 → mp3（晓伊）。"""
    return await vp.synthesize(text, _pick(voice))


async def tts_wav(text: str, voice: str | None = None) -> bytes:
    """文字 → WAV（同一个声音，给玩偶等只认 WAV 的设备）。"""
    return await vp.synthesize_wav(text, _pick(voice))


# ---------- 识别 ----------
def local_asr_ready() -> bool:
    return vp.asr_ready()


def _local_asr(audio: bytes) -> dict:
    return vp.transcribe(audio)


async def asr(audio: bytes, filename="speech.wav") -> dict:
    return await asyncio.to_thread(vp.transcribe, audio)


def warm_up():
    vp.warm_up()


# 给 /api/voices 用的状态
def use_local_asr() -> bool:
    return vp.asr_ready()


def use_local_tts() -> bool:
    return False
