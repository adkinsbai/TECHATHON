"""下载本地语音模型到 models/（只需运行一次）：
- SenseVoice-Small int8：语音识别，顺带识别说话情绪
- Kokoro int8 v1.1：语音合成，含中文音色
"""
import os
import pathlib
import time

# Xet 传输在国内网络下容易卡死，改用普通 HTTP（支持断点续传，中断后重跑即可）
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
from huggingface_hub import snapshot_download  # noqa: E402

# 和 app/config.py 一致：.env 里的 MODELS_DIR 优先，否则放在项目的 models/
ROOT = pathlib.Path(__file__).resolve().parent
_env = {}
if (ROOT / ".env").exists():
    for line in (ROOT / ".env").read_text(encoding="utf-8-sig").splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            _env[k.strip()] = v.strip()
MODELS = pathlib.Path(_env.get("MODELS_DIR") or (ROOT / "models"))

for repo, patterns in [
    ("csukuangfj/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2025-09-09", ["model.int8.onnx", "tokens.txt", "LICENSE", "README.md"]),
    ("csukuangfj/kokoro-int8-multi-lang-v1_1", None),
]:
    target = MODELS / repo.split("/")[1]
    print("下载", repo, "->", target, flush=True)
    for attempt in range(1, 61):  # 网络断了就接着续传
        try:
            snapshot_download(repo_id=repo, local_dir=target, allow_patterns=patterns)
            break
        except Exception as e:
            print(f"第 {attempt} 次中断（{type(e).__name__}），5 秒后续传…", flush=True)
            time.sleep(5)
    else:
        raise SystemExit("多次重试仍失败，请检查网络后重跑")
print("完成", flush=True)
