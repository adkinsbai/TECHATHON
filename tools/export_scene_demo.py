"""把世界工作室里生成好的场景导出成仓库里的只读示例（companion/demos/scenes/<名字>/）。

用法：python tools/export_scene_demo.py <场景编号> <示例名字> [--home %APPDATA%\\Xiaonuan]
- 复制 job.json、每个资产的 GLB，参考图缩成 512 像素的 JPEG 预览；
- 去掉服务商的任务编号、订阅令牌和下载地址（仓库是公开的），地址改成示例的编号；
- 每个 GLB 都做完整性校验，不完整就拒绝导出。
"""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'companion'))
from app.scene_assets import validate_glb  # noqa: E402

PRIVATE = ('upstream', 'download_url', 'message', 'image_started_at', 'model_started_at')


def export(home, job_id, name):
    if not re.fullmatch(r'[a-z0-9-]{2,32}', name):
        raise SystemExit('示例名字只能用小写字母、数字和连字符')
    source = Path(home) / 'world-studio' / job_id
    job = json.loads((source / 'job.json').read_text(encoding='utf-8'))
    if job.get('state') != 'ready' or any(a.get('state') != 'ready' for a in job['assets'].values()):
        raise SystemExit('场景还没有全部生成完成，不能导出')
    demo_id = 'demo-' + name
    target = ROOT / 'companion' / 'demos' / 'scenes' / name
    target.mkdir(parents=True, exist_ok=True)
    from PIL import Image
    assets = {}
    for asset_id, record in job['assets'].items():
        model = (source / f'{asset_id}.glb').read_bytes()
        validate_glb(model)
        (target / f'{asset_id}.glb').write_bytes(model)
        clean = {k: v for k, v in record.items() if k not in PRIVATE and not k.startswith('rig')}
        clean.update(model_sha256=hashlib.sha256(model).hexdigest(), model_bytes=len(model),
                     model_url=f'/api/scene-studio/{demo_id}/assets/{asset_id}/model', message='示例资产')
        image = source / f'{asset_id}.image'
        if image.exists():
            picture = Image.open(io.BytesIO(image.read_bytes())).convert('RGB')
            picture.thumbnail((512, 512))
            buffer = io.BytesIO()
            picture.save(buffer, 'JPEG', quality=85, optimize=True)
            (target / f'{asset_id}.image').write_bytes(buffer.getvalue())
            clean.update(image_url=f'/api/scene-studio/{demo_id}/assets/{asset_id}/image',
                         image_sha256=hashlib.sha256(buffer.getvalue()).hexdigest())
        assets[asset_id] = clean
    demo = {k: v for k, v in job.items() if k not in ('assets', 'error')}
    demo.update(id=demo_id, demo=True, state='ready', assets=assets, source_scene=job_id)
    (target / 'job.json').write_text(json.dumps(demo, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    size = sum(f.stat().st_size for f in target.iterdir())
    print(f'exported {demo_id}: {len(assets)} assets, {size / 1048576:.1f} MB -> {target}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('job_id')
    parser.add_argument('name')
    parser.add_argument('--home', default=os.environ.get('XIAONUAN_HOME') or str(Path(os.environ['APPDATA']) / 'Xiaonuan'))
    args = parser.parse_args()
    export(args.home, args.job_id, args.name)


if __name__ == '__main__':
    main()
