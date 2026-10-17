"""独立语音服务：python -m voice_pack.server --port 8770

POST /asr      上传 WAV（multipart 字段 file）→ {"text", "emotion", "event"}
POST /tts      {"text": "...", "voice": 可选, "format": "mp3" | "wav"} → 音频
GET  /health   模型和音色状态
"""
import argparse
import asyncio

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field

from . import asr, tts
from .config import configure, settings

app = FastAPI(title="voice_pack")


class TTSIn(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    voice: str | None = None
    format: str = Field(default="mp3", pattern="^(mp3|wav)$")


@app.get("/health")
async def health():
    return {"asr_ready": asr.asr_ready(), "models_dir": str(settings.models_dir), "default_voice": tts.DEFAULT_VOICE}


@app.post("/asr")
async def do_asr(file: UploadFile = File(...)):
    data = await file.read(4_000_001)
    if len(data) > 4_000_000:
        raise HTTPException(413, "录音太长")
    try:
        return await asyncio.to_thread(asr.transcribe, data)
    except Exception as e:
        raise HTTPException(503, f"识别失败：{e}") from e


@app.post("/tts")
async def do_tts(body: TTSIn):
    try:
        if body.format == "wav":
            return Response(await tts.synthesize_wav(body.text, body.voice), media_type="audio/wav")
        return Response(await tts.synthesize(body.text, body.voice), media_type="audio/mpeg")
    except Exception as e:
        raise HTTPException(503, f"合成失败：{e}") from e


def main():
    p = argparse.ArgumentParser(description="噜噜的语音服务（识别 + 合成）")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8770)
    p.add_argument("--models-dir")
    a = p.parse_args()
    configure(models_dir=a.models_dir)
    asr.warm_up()
    import uvicorn
    uvicorn.run(app, host=a.host, port=a.port)


if __name__ == "__main__":
    main()
