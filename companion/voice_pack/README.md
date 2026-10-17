# voice_pack · 噜噜的耳朵和嘴巴

| | 用什么 | 特点 |
|---|---|---|
| 识别 ASR | 本地 **SenseVoice**（sherpa-onnx，int8） | 离线、纯 CPU、约 0.3 秒/句；还能听出说话的**情绪**（开心/难过/生气…）和**笑声、哭声** |
| 合成 TTS | 微软神经语音 **晓伊（活泼）**（edge-tts） | 免费、不要 key、很自然；需要联网，文字会发给微软合成 |

合成失败会自动重试；重试也失败就报错（这句不出声），**不会偷偷换成别的声音**。

## 安装

```bash
pip install -r voice_pack/requirements.txt
python -m voice_pack.download            # 下载识别模型（约 230MB，可断点续传）
```

模型默认放在 `~/.companion/models`，可以用 `--models-dir` 或环境变量 `VOICE_MODELS_DIR` 改。
Windows 下请放在短路径里（深层路径超过 260 字符会读写失败）。

## 当库用（伴侣后端、玩偶都这样调）

```python
import voice_pack as vp
r = vp.transcribe(wav_bytes)              # {"text": "...", "emotion": "开心", "event": "笑了"}
mp3 = await vp.synthesize("你好呀")       # 晓伊的 mp3（网页直接播）
wav = await vp.synthesize_wav("你好呀")   # 同一个声音的 WAV（24kHz/单声道/16 位，玩偶播）
```

## 当独立服务用（给 ESP32 或别的程序）

```bash
python -m voice_pack.server --port 8770
```

- `POST /asr`：multipart 上传 `file`（16 位 WAV）→ `{"text", "emotion", "event"}`
- `POST /tts`：`{"text": "你好呀", "format": "wav"}` → 音频（`format` 可选 `mp3`/`wav`，`voice` 可选）
- `GET /health`

## 伴侣里的“边说边合成”

伴侣后端（`app/speech_stream.py`）在回复还在生成时，每写完一句就调 `synthesize()` 合成这一句，
用 `audio` 事件一句句推给网页，网页排队播放。实测“说完一句话 → 听到第一句”从 7~9 秒降到约 4 秒。
