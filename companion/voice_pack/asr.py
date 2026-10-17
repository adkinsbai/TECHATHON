"""语音识别：本地 SenseVoice（sherpa-onnx，纯 CPU、离线）。约 0.3 秒识别一句话。"""
import io
import threading
import wave

import numpy as np

from .config import settings

EMOTION_ZH = {"HAPPY": "开心", "SAD": "难过", "ANGRY": "生气", "FEARFUL": "害怕", "DISGUSTED": "厌烦",
              "SURPRISED": "惊讶", "NEUTRAL": "平静"}
EVENT_ZH = {"Laughter": "笑了", "Cry": "在哭", "Cough": "咳嗽", "Sneeze": "打喷嚏"}

_lock = threading.Lock()
_recognizer = None


def asr_ready() -> bool:
    return (settings.sensevoice_dir / "model.int8.onnx").exists()


def _get():
    global _recognizer
    with _lock:
        if _recognizer is None:
            import sherpa_onnx
            d = settings.sensevoice_dir
            _recognizer = sherpa_onnx.OfflineRecognizer.from_sense_voice(
                model=str(d / "model.int8.onnx"), tokens=str(d / "tokens.txt"),
                num_threads=settings.threads, use_itn=True, language="auto")
    return _recognizer


def warm_up():
    """提前加载模型（约几秒），第一次识别就不会卡。"""
    if asr_ready():
        _get()


def _read_wav(data: bytes):
    with wave.open(io.BytesIO(data)) as w:
        sr, ch, width = w.getframerate(), w.getnchannels(), w.getsampwidth()
        raw = w.readframes(w.getnframes())
    if width != 2:
        raise ValueError("只支持 16 位 PCM WAV")
    samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768
    if ch > 1:
        samples = samples.reshape(-1, ch).mean(axis=1)
    return sr, samples


def _tag(v):
    return (v or "").strip("<|>").strip()


def transcribe(wav_bytes: bytes) -> dict:
    """WAV（16 位，任意采样率）→ {"text", "emotion"（中文，如“开心”）, "event"（如“笑了”）}"""
    if not asr_ready():
        raise RuntimeError(f"语音识别模型不在 {settings.sensevoice_dir}，先运行 python -m voice_pack.download")
    sr, samples = _read_wav(wav_bytes)
    rec = _get()
    stream = rec.create_stream()
    stream.accept_waveform(sr, samples)
    rec.decode_stream(stream)
    r = stream.result
    return {
        "text": r.text.strip(),
        "emotion": EMOTION_ZH.get(_tag(getattr(r, "emotion", "")), ""),
        "event": EVENT_ZH.get(_tag(getattr(r, "event", "")), ""),
    }
