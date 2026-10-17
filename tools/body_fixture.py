"""Isolated Companion fixture. Copies only source/assets, never personal data or keys."""
import argparse
import asyncio
import io
import math
from pathlib import Path
import shutil
import struct
import sys
import wave


def prepare(source, root):
    root.mkdir(parents=True, exist_ok=True)
    for folder in ("app", "static"):
        shutil.copytree(source / folder, root / folder, dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from install_companion import install
    return install(root)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--port", default=18765, type=int)
    args = parser.parse_args()
    prepare(args.source, args.root)
    sys.path.insert(0, str(args.root.resolve()))
    from app import server, brain, voice
    import uvicorn

    state = {"asr_count": 0, "tts_count": 0, "last_audio": None}

    async def fake_chat(messages, **kwargs):
        for part in ("[happy 0.7]\n", "收到，实体里的小暖听见了。"):
            await asyncio.sleep(.02)
            yield part

    async def fake_json(*args, **kwargs):
        return {"add": [], "update": [], "episode": "实体接口测试"}

    async def fake_asr(data, filename="body.wav"):
        with wave.open(io.BytesIO(data), "rb") as wav:
            state["last_audio"] = {"rate": wav.getframerate(), "channels": wav.getnchannels(),
                                   "width": wav.getsampwidth(), "frames": wav.getnframes()}
        state["asr_count"] += 1
        return {"text": "小暖你好，实体连接测试", "emotion": "平静", "event": ""}

    async def fake_tts(text, *args, **kwargs):
        state["tts_count"] += 1
        buf = io.BytesIO()
        # Exactly +/-5000, therefore expected hardware amplitude at 10% is +/-500.
        samples = b"".join(struct.pack("<h", 5000 if i % 48 < 24 else -5000) for i in range(7200))
        with wave.open(buf, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(24000)
            wav.writeframes(samples)
        return buf.getvalue()

    brain.stream_chat = fake_chat
    brain.complete_json = fake_json
    voice.asr, voice.tts, voice.warm_up = fake_asr, fake_tts, lambda: None

    @server.app.get("/__fixture")
    async def fixture_state():
        return state

    uvicorn.run(server.app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
