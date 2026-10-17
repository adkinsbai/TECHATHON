"""声音：
- 本地（默认）：sherpa-onnx + SenseVoice（识别，顺带听出情绪）+ Kokoro（合成），纯 CPU、离线、免 key
- 智谱 GLM：TTS / ASR，本地模型不在时使用
前端在两者都不可用时会退回浏览器自带语音。
"""
import asyncio
import io
import os
import re
import threading
import wave

import httpx
import numpy as np

from .config import (ASR_ENGINE, GLM_API_KEY, GLM_ASR_MODEL, GLM_BASE_URL, GLM_TTS_MODEL, GLM_TTS_VOICE,
                     MODELS_DIR, TTS_ENGINE)

MODELS = MODELS_DIR
SENSEVOICE_DIR = MODELS / "sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2025-09-09"
KOKORO_DIR = MODELS / "kokoro-int8-multi-lang-v1_1"

# Kokoro v1.1 共 103 个说话人：0~2 是英文音色，3 起是中文女声（实测基频 170~330Hz）。
# 名字是按实测音高起的，具体哪个好听请在“声音”设置里试听。
LOCAL_VOICES = {
    "local:3": "本地 · 女声 3（温柔）", "local:14": "本地 · 女声 14（温柔）", "local:18": "本地 · 女声 18（柔和）",
    "local:27": "本地 · 女声 27（清甜）", "local:36": "本地 · 女声 36（清甜）", "local:23": "本地 · 女声 23（少女感）",
    "local:41": "本地 · 女声 41（软萌·音调高）", "local:13": "本地 · 女声 13（成熟·音调低）",
}
GLM_VOICES = {
    "tongtong": "智谱 · 彤彤（温柔女声）", "chuichui": "智谱 · 锤锤（活泼）", "xiaochen": "智谱 · 小陈（男声）",
}
DEFAULT_LOCAL_VOICE = "local:3"
THREADS = max(2, min(8, (os.cpu_count() or 4) // 2))


def _kokoro_model():
    # 全精度 model.onnx 在 CPU 上比 int8 快好几倍（int8 的量化算子在 CPU 上很慢），有就优先用
    for name in ("model.onnx", "model.int8.onnx"):
        if (KOKORO_DIR / name).exists():
            return KOKORO_DIR / name
    return None

EMOTION_ZH = {"HAPPY": "开心", "SAD": "难过", "ANGRY": "生气", "FEARFUL": "害怕", "DISGUSTED": "厌烦",
              "SURPRISED": "惊讶", "NEUTRAL": "平静"}
EVENT_ZH = {"Laughter": "笑了", "Cry": "在哭", "Cough": "咳嗽", "Sneeze": "打喷嚏"}


class VoiceError(Exception):
    pass


# ---------- 本地模型（懒加载，第一次用到时才载入） ----------
_lock = threading.Lock()
_recognizer = None
_tts = None


def local_asr_ready():
    return (SENSEVOICE_DIR / "model.int8.onnx").exists()


def local_tts_ready():
    return _kokoro_model() is not None


def use_local_asr():
    return ASR_ENGINE == "local" or (ASR_ENGINE == "auto" and local_asr_ready())


def use_local_tts():
    return TTS_ENGINE == "local" or (TTS_ENGINE == "auto" and local_tts_ready())


def _get_recognizer():
    global _recognizer
    with _lock:
        if _recognizer is None:
            import sherpa_onnx
            _recognizer = sherpa_onnx.OfflineRecognizer.from_sense_voice(
                model=str(SENSEVOICE_DIR / "model.int8.onnx"), tokens=str(SENSEVOICE_DIR / "tokens.txt"),
                num_threads=THREADS, use_itn=True, language="auto")
    return _recognizer


def _get_tts():
    global _tts
    with _lock:
        if _tts is None:
            import sherpa_onnx
            d = KOKORO_DIR
            cfg = sherpa_onnx.OfflineTtsConfig(
                model=sherpa_onnx.OfflineTtsModelConfig(
                    kokoro=sherpa_onnx.OfflineTtsKokoroModelConfig(
                        model=str(_kokoro_model()), voices=str(d / "voices.bin"), tokens=str(d / "tokens.txt"),
                        data_dir=str(d / "espeak-ng-data"), dict_dir=str(d / "dict"),
                        lexicon=f"{d / 'lexicon-us-en.txt'},{d / 'lexicon-zh.txt'}"),
                    num_threads=THREADS),
                rule_fsts=f"{d / 'date-zh.fst'},{d / 'phone-zh.fst'},{d / 'number-zh.fst'}",
                max_num_sentences=1)
            _tts = sherpa_onnx.OfflineTts(cfg)
    return _tts


def warm_up():
    """后台预加载，避免第一次说话时卡几秒。"""
    if use_local_asr():
        _get_recognizer()
    if use_local_tts():
        _get_tts()


def _read_wav(data: bytes):
    with wave.open(io.BytesIO(data)) as w:
        sr, ch, width = w.getframerate(), w.getnchannels(), w.getsampwidth()
        raw = w.readframes(w.getnframes())
    if width != 2:
        raise VoiceError("只支持 16 位 WAV")
    samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768
    if ch > 1:
        samples = samples.reshape(-1, ch).mean(axis=1)
    return sr, samples


def _to_wav(samples, sr) -> bytes:
    pcm = (np.clip(np.asarray(samples), -1, 1) * 32767).astype(np.int16)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())
    return buf.getvalue()


def _tag(value):
    return (value or "").strip("<|>").strip()


def _local_asr(data: bytes) -> dict:
    sr, samples = _read_wav(data)
    rec = _get_recognizer()
    stream = rec.create_stream()
    stream.accept_waveform(sr, samples)
    rec.decode_stream(stream)
    r = stream.result
    emotion = _tag(getattr(r, "emotion", ""))
    event = _tag(getattr(r, "event", ""))
    return {"text": r.text.strip(), "emotion": EMOTION_ZH.get(emotion, ""), "event": EVENT_ZH.get(event, "")}


def _local_tts(text: str, voice: str, speed: float) -> bytes:
    sid = int(voice.split(":")[1]) if voice and voice.startswith("local:") else int(DEFAULT_LOCAL_VOICE.split(":")[1])
    text = re.sub(r"\s+", "，", text.strip())
    audio = _get_tts().generate(text, sid=sid, speed=speed)
    if len(audio.samples) == 0:
        raise VoiceError("合成结果为空")
    return _to_wav(audio.samples, audio.sample_rate)


# ---------- 智谱 GLM ----------
def _auth():
    if not GLM_API_KEY:
        raise VoiceError("未配置 GLM_API_KEY")
    return {"Authorization": f"Bearer {GLM_API_KEY}"}


async def _glm_tts(text, voice, speed):
    body = {"model": GLM_TTS_MODEL, "input": text[:1000], "voice": voice or GLM_TTS_VOICE,
            "response_format": "wav", "speed": speed}
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(f"{GLM_BASE_URL}/audio/speech", headers=_auth(), json=body)
    if r.status_code != 200 or "json" in r.headers.get("content-type", ""):
        raise VoiceError(f"TTS {r.status_code}: {r.text[:200]}")
    return r.content


async def _glm_asr(audio, filename):
    files = {"file": (filename, audio, "audio/wav")}
    data = {"model": GLM_ASR_MODEL, "stream": "false"}
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(f"{GLM_BASE_URL}/audio/transcriptions", headers=_auth(), data=data, files=files)
    if r.status_code != 200:
        raise VoiceError(f"ASR {r.status_code}: {r.text[:200]}")
    return {"text": (r.json().get("text") or "").strip(), "emotion": "", "event": ""}


# ---------- 微软神经语音（edge-tts）：免费、不要 key、很自然，但需要联网，文字会发给微软合成 ----------
# 格式：edge:音色|语速|音调
EDGE_VOICES = {
    "edge:zh-CN-XiaoyiNeural|-5%|+12Hz": "微软 · 晓伊（软萌）",
    "edge:zh-CN-XiaoyiNeural|+0%|+0Hz": "微软 · 晓伊（活泼）",
    "edge:zh-CN-XiaoxiaoNeural|-3%|+10Hz": "微软 · 晓晓（甜）",
    "edge:zh-CN-XiaoxiaoNeural|+0%|+0Hz": "微软 · 晓晓（温柔）",
    "edge:zh-TW-HsiaoChenNeural|+0%|+0Hz": "微软 · 曉臻（台湾腔·软）",
    "edge:zh-TW-HsiaoYuNeural|+0%|+0Hz": "微软 · 曉雨（台湾腔·温柔）",
    "edge:zh-CN-YunxiaNeural|+0%|+0Hz": "微软 · 云夏（可爱男孩）",
}


async def _edge_tts(text: str, voice: str) -> bytes:
    import edge_tts
    name, rate, pitch = (voice.split(":", 1)[1].split("|") + ["+0%", "+0Hz"])[:3]
    out = bytearray()
    async for chunk in edge_tts.Communicate(text[:1000], name, rate=rate, pitch=pitch).stream():
        if chunk["type"] == "audio":
            out += chunk["data"]
    if not out:
        raise VoiceError("微软语音没有返回音频")
    return bytes(out)


# ---------- 对外接口 ----------
def voices():
    out = dict(EDGE_VOICES)
    if use_local_tts():
        out.update(LOCAL_VOICES)
    out.update(GLM_VOICES)
    return out


async def tts(text: str, voice: str | None = None, speed: float = 1.0) -> bytes:
    """返回音频字节（微软语音是 mp3，其余是 wav）。"""
    if voice and voice.startswith("edge:"):
        try:
            return await _edge_tts(text, voice)
        except Exception:
            if not use_local_tts():
                raise
            voice = DEFAULT_LOCAL_VOICE  # 没网时退回本地
    if voice and not voice.startswith("local:") and voice in GLM_VOICES:
        try:
            return await _glm_tts(text, voice, speed)
        except Exception:
            if not use_local_tts():
                raise
            voice = DEFAULT_LOCAL_VOICE  # GLM 不可用时退回本地
    if use_local_tts():
        return await asyncio.to_thread(_local_tts, text, voice or DEFAULT_LOCAL_VOICE, speed)
    return await _glm_tts(text, voice, speed)


async def asr(audio: bytes, filename="speech.wav") -> dict:
    if use_local_asr():
        return await asyncio.to_thread(_local_asr, audio)
    return await _glm_asr(audio, filename)
