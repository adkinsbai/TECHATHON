"""下载语音识别模型（SenseVoice int8，约 230MB）：python -m voice_pack.download [--models-dir 目录]

来源：Hugging Face 上 sherpa-onnx 官方作者 csukuangfj 发布的模型。网络断了会自动续传重试。
（语音合成用微软晓伊，不需要下载模型。）
"""
import argparse
import os
import time

os.environ.setdefault("HF_HUB_DISABLE_XET", "1")   # Xet 传输在国内网络下容易卡死，用普通 HTTP（可续传）

from .config import SENSEVOICE_REPO, configure, settings  # noqa: E402


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--models-dir")
    a = p.parse_args()
    configure(models_dir=a.models_dir)
    from huggingface_hub import snapshot_download
    target = settings.sensevoice_dir
    print("下载", SENSEVOICE_REPO, "->", target, flush=True)
    for attempt in range(1, 61):
        try:
            snapshot_download(repo_id=SENSEVOICE_REPO, local_dir=target, allow_patterns=["model.int8.onnx", "tokens.txt", "LICENSE", "README.md"])
            print("完成", flush=True)
            return
        except Exception as e:
            print(f"第 {attempt} 次中断（{type(e).__name__}），5 秒后续传…", flush=True)
            time.sleep(5)
    raise SystemExit("多次重试仍失败，请检查网络后重跑")


if __name__ == "__main__":
    main()
