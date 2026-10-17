"""voice_pack：噜噜的“耳朵”和“嘴巴”。

- 识别（ASR）：本地离线 SenseVoice（sherpa-onnx），除了文字还能听出说话的情绪和笑声/哭声
- 合成（TTS）：微软神经语音·晓伊（edge-tts，免费、不要 key、需联网）；可直接输出 WAV 给玩偶播放

用法：
    import voice_pack as vp
    vp.configure(models_dir="C:/Users/me/.companion/models")   # 可选，默认 ~/.companion/models
    r = vp.transcribe(wav_bytes)          # {"text": ..., "emotion": "开心", "event": "笑了"}
    mp3 = await vp.synthesize("你好呀")    # 晓伊的 mp3
    wav = await vp.synthesize_wav("你好呀")
也可以单独起服务：python -m voice_pack.server --port 8770
"""
from .asr import asr_ready, transcribe, warm_up
from .config import configure, settings
from .tts import DEFAULT_VOICE, VOICES, TTSError, mp3_to_wav, synthesize, synthesize_wav

__all__ = [
    "configure", "settings", "transcribe", "asr_ready", "warm_up",
    "synthesize", "synthesize_wav", "mp3_to_wav", "VOICES", "DEFAULT_VOICE", "TTSError",
]
