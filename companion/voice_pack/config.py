"""语音包的设置：模型放哪、用几个线程。可以用环境变量，也可以在代码里 configure()。"""
import os
import pathlib
from dataclasses import dataclass

SENSEVOICE_NAME = "sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2025-09-09"
SENSEVOICE_REPO = "csukuangfj/" + SENSEVOICE_NAME


@dataclass
class Settings:
    # Windows 下项目路径太长时，模型要放在短路径里（深层路径超过 260 字符会读写失败）
    models_dir: pathlib.Path = pathlib.Path(os.environ.get("VOICE_MODELS_DIR") or pathlib.Path.home() / ".companion" / "models")
    threads: int = max(2, min(8, (os.cpu_count() or 4) // 2))

    @property
    def sensevoice_dir(self) -> pathlib.Path:
        return self.models_dir / SENSEVOICE_NAME


settings = Settings()


def configure(models_dir=None, threads=None):
    if models_dir:
        settings.models_dir = pathlib.Path(models_dir)
    if threads:
        settings.threads = int(threads)
