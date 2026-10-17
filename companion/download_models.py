"""下载语音识别模型（只需运行一次）。等同于：python -m voice_pack.download

模型目录：.env 里的 MODELS_DIR 优先，否则 ~/.companion/models。
（语音合成用微软晓伊，不需要下载模型。）
"""
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

_env = {}
if (ROOT / ".env").exists():
    for line in (ROOT / ".env").read_text(encoding="utf-8-sig").splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            _env[k.strip()] = v.strip()

if _env.get("MODELS_DIR") and "--models-dir" not in sys.argv:
    sys.argv += ["--models-dir", _env["MODELS_DIR"]]

from voice_pack.download import main  # noqa: E402

main()
