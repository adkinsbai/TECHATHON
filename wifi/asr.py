"""asr.py - 本地中文语音识别（Vosk 小模型，离线）

模型目录：wifi/models/vosk-model-small-cn
用法：
    from asr import transcribe_wav
    print(transcribe_wav("recordings/xxx.wav"))

Vosk 只吃 16kHz / 单声道 / 16bit，这里会自动转换。
"""

import json
import os
import wave

import audioop

HERE = os.path.dirname(os.path.abspath(__file__))
MODEL_DIR = os.path.join(HERE, "models", "vosk-model-small-cn")
SR = 16000

_model = None


def model_ready():
    return os.path.isdir(MODEL_DIR) and os.path.exists(os.path.join(MODEL_DIR, "am", "final.mdl"))


def _get_model():
    global _model
    if _model is None:
        from vosk import Model, SetLogLevel
        SetLogLevel(-1)                       # 别往 stdout 刷日志
        _model = Model(MODEL_DIR)
    return _model


def pcm16k(path):
    """读 WAV -> 16kHz 单声道 16bit PCM。"""
    with wave.open(path, "rb") as w:
        ch, width, rate = w.getnchannels(), w.getsampwidth(), w.getframerate()
        data = w.readframes(w.getnframes())
    if width != 2:
        data = audioop.lin2lin(data, width, 2)
    if ch == 2:
        data = audioop.tomono(data, 2, 0.5, 0.5)
    if rate != SR:
        data, _ = audioop.ratecv(data, 2, 1, rate, SR, None)
    return data


def transcribe_wav(path, words=False):
    """返回识别出来的中文文本（可能为空）。"""
    import vosk
    if not model_ready():
        raise RuntimeError("找不到中文模型：%s" % MODEL_DIR)
    pcm = pcm16k(path)
    rec = vosk.KaldiRecognizer(_get_model(), SR)
    rec.SetWords(True)
    for off in range(0, len(pcm), 8000):     # 0.25 秒一块
        rec.AcceptWaveform(pcm[off:off + 8000])
    res = json.loads(rec.FinalResult())
    text = (res.get("text") or "").replace(" ", "")
    if words:
        return text, res.get("result", [])
    return text
