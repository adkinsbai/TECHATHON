"""读取 .env 配置。"""
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)


def _load_env() -> dict:
    env = {}
    path = ROOT / ".env"
    if path.exists():
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return env


ENV = _load_env()

DEEPSEEK_API_KEY = ENV.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = ENV.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/")
DEEPSEEK_MODEL = ENV.get("DEEPSEEK_MODEL", "deepseek-flash")
DEEPSEEK_EFFORT = ENV.get("DEEPSEEK_EFFORT", "low")

GLM_API_KEY = ENV.get("GLM_API_KEY", "")
GLM_BASE_URL = ENV.get("GLM_BASE_URL", "https://open.bigmodel.cn/api/paas/v4").rstrip("/")
GLM_TTS_MODEL = ENV.get("GLM_TTS_MODEL", "glm-tts")
GLM_TTS_VOICE = ENV.get("GLM_TTS_VOICE", "tongtong")
GLM_ASR_MODEL = ENV.get("GLM_ASR_MODEL", "glm-asr")

# 本地语音模型目录（Windows 路径太长时可放到短路径下）
MODELS_DIR = pathlib.Path(ENV.get("MODELS_DIR") or (ROOT / "models"))

# auto：本地模型在就用本地，不在就用 GLM；也可以写 local / glm 强制指定
TTS_ENGINE = ENV.get("TTS_ENGINE", "auto")
ASR_ENGINE = ENV.get("ASR_ENGINE", "auto")

PORT = int(ENV.get("PORT", "8765"))
