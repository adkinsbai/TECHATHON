"""按白名单导出实际 Companion 源码；不读取 .env、用户数据或模型。"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from install_companion import _filesystem_path

EXCLUDED_DIRS = {'__pycache__', 'data', 'models', 'backups', 'runtime', '.git', '.body-backups'}
PRIVATE_NAMES = {'interaction-log.json', 'history.json', 'messages.json', 'persona.json', 'cookies.json'}
TEXT_SUFFIXES = {'.py', '.js', '.css', '.html', '.json', '.md', '.txt', '.svg'}
APP_SUFFIXES = {'.py', '.json'}
STATIC_SUFFIXES = TEXT_SUFFIXES | {'.glb', '.png', '.jpg', '.jpeg', '.webp', '.gif', '.woff', '.woff2', '.ttf', '.ico'}
SECRET_PATTERNS = (
    re.compile(r'\bsk-[A-Za-z0-9_-]{20,}\b'),
    re.compile(r'\bAIza[A-Za-z0-9_-]{30,}\b'),
    re.compile(r'\bAKIA[A-Z0-9]{16}\b'),
    re.compile(r'(?i)(?:[A-Z]:[\\/]Users[\\/]|/Users/|/home/)[^\\/\s"\']+'),
    re.compile(r'''(?ix)(?:api[_-]?key|secret[_-]?key|access[_-]?token|password)\s*[=:]\s*["'](?!["']|your|replace|example|placeholder|<|\$\{|os\.)([^"'\r\n]{8,})["']'''),
)

ENV_EXAMPLE = '''# Copy to .env locally. Never commit real credentials or model files.
DEEPSEEK_API_KEY=
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-flash
DEEPSEEK_EFFORT=low
GLM_API_KEY=
GLM_BASE_URL=https://open.bigmodel.cn/api/paas/v4
GLM_TTS_MODEL=glm-tts
GLM_TTS_VOICE=tongtong
GLM_ASR_MODEL=glm-asr
ASR_ENGINE=local
TTS_ENGINE=local
# Replace with your local model directory; keep models outside version control.
MODELS_DIR=./models
PORT=8765
'''.encode('utf-8')

REQUIREMENTS = '''# Generated from imports in the exported Companion source.
fastapi>=0.115,<1
uvicorn>=0.30,<1
httpx>=0.27,<1
pydantic>=2,<3
python-multipart>=0.0.9,<1
numpy>=1.26,<3
sherpa-onnx>=1.10,<2
edge-tts>=6,<8
huggingface-hub>=0.24,<2
'''.encode('utf-8')


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def export(source, destination):
    source, destination = _filesystem_path(source), _filesystem_path(destination)
    if destination.exists():
        raise RuntimeError('目标目录已存在，拒绝覆盖现有导出')
    files, excluded, suspicious = {}, [], []
    for folder in ('app', 'static'):
        base = source / folder
        if base.is_symlink() or base.is_junction() or not base.is_dir():
            raise RuntimeError('源代码目录无效')
        for path in sorted(base.rglob('*')):
            relative = path.relative_to(source).as_posix()
            if any(part in EXCLUDED_DIRS for part in path.relative_to(source).parts):
                continue
            if path.is_symlink() or path.is_junction():
                raise RuntimeError('拒绝导出重定向路径：' + relative)
            if not path.is_file():
                continue
            if path.name in PRIVATE_NAMES or path.name.startswith('.env') or path.suffix in {'.pyc', '.log', '.sqlite', '.sqlite3', '.db'}:
                excluded.append(relative)
                continue
            allowed = APP_SUFFIXES if folder == 'app' else STATIC_SUFFIXES
            if path.suffix.lower() not in allowed:
                excluded.append(relative)
                continue
            data = path.read_bytes()
            if path.suffix.lower() in TEXT_SUFFIXES:
                text = data.decode('utf-8', errors='replace')
                if any(pattern.search(text) for pattern in SECRET_PATTERNS):
                    suspicious.append(relative)
                    continue
            files[relative] = data
    if suspicious:
        # 不输出匹配内容，也不留下部分导出。
        raise RuntimeError('疑似私密内容，未复制：' + ', '.join(suspicious))
    for original, relative in (('download_models.py', 'download_models.py'), ('README.md', 'README.original.md')):
        path = source / original
        if not path.is_file():
            continue
        if path.is_symlink() or path.is_junction():
            raise RuntimeError('拒绝导出重定向路径：' + original)
        data = path.read_bytes()
        if any(pattern.search(data.decode('utf-8', errors='replace')) for pattern in SECRET_PATTERNS):
            excluded.append(original)
            continue
        files[relative] = data
    if not {'app/server.py', 'app/config.py', 'app/default_persona.json', 'static/index.html'} <= files.keys():
        raise RuntimeError('缺少独立运行所需的白名单源文件')
    generated = {'.env.example': ENV_EXAMPLE,
                 '.gitattributes': b'* -text whitespace=trailing-space,space-before-tab,cr-at-eol\n'}
    requirements = source / 'requirements.txt'
    if requirements.is_file():
        data = requirements.read_bytes()
        if any(pattern.search(data.decode('utf-8', errors='replace')) for pattern in SECRET_PATTERNS):
            raise RuntimeError('疑似私密内容，未复制：requirements.txt')
        files['requirements.txt'] = data
    else:
        generated['requirements.txt'] = REQUIREMENTS
    destination.mkdir(parents=True)
    manifest = {'schema_version': 1, 'exported_at_utc': datetime.now(timezone.utc).isoformat(),
                'source_description': 'Active Companion application source; app and static allowlist',
                'files': [], 'excluded_files': excluded,
                'model_upstreams': [
                    {'url': 'https://huggingface.co/csukuangfj/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2025-09-09',
                     'license': 'See upstream LICENSE; model weights are excluded'},
                    {'url': 'https://huggingface.co/csukuangfj/kokoro-int8-multi-lang-v1_1',
                     'license': 'See upstream LICENSE; model weights are excluded'}]}
    for relative, data in sorted({**files, **generated}.items()):
        path = destination / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        if sha256(path.read_bytes()) != sha256(data):
            raise RuntimeError('导出 SHA256 不匹配：' + relative)
        manifest['files'].append({'path': relative, 'bytes': len(data), 'sha256': sha256(data),
                                  'origin': 'generated_portable_configuration' if relative in generated else 'copied_exact_bytes'})
    (destination / 'SOURCE-MANIFEST.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return {'copied': len(files), 'generated': len(generated), 'excluded_files': excluded, 'sha256_verified': True}


def main():
    parser = argparse.ArgumentParser(description='导出可交接的 Companion 源码，不读取个人数据')
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--destination', type=Path, default=ROOT / 'companion')
    args = parser.parse_args()
    try:
        print(json.dumps(export(args.source, args.destination), ensure_ascii=False))
        return 0
    except RuntimeError as exc:
        print(str(exc))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
