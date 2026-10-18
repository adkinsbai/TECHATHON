# PyInstaller 配置：打包成 dist/Xiaonuan/Xiaonuan.exe（目录模式）。用 packaging/build_app.ps1 调用。
import os
from PyInstaller.utils.hooks import collect_all, collect_submodules

REPO = os.path.abspath(os.path.join(SPECPATH, '..'))
COMPANION = os.path.join(REPO, 'companion')

datas = [
    (os.path.join(COMPANION, 'static'), 'static'),
    (os.path.join(COMPANION, 'app', 'default_persona.json'), 'app'),
    (os.path.join(COMPANION, 'demos'), 'demos'),   # 自带的对话生成世界示例（只读）
    (os.path.join(REPO, 'xiaonuan_app', 'static'), os.path.join('xiaonuan_app', 'static')),
]
binaries = []
hiddenimports = (collect_submodules('uvicorn') + collect_submodules('app') + collect_submodules('voice_pack')
                 + collect_submodules('body_bridge') + ['wifi.wifi_link', 'multipart', 'python_multipart', '_cffi_backend'])
for package in ('sherpa_onnx', 'edge_tts', 'miniaudio'):
    d, b, h = collect_all(package)
    datas += d
    binaries += b
    hiddenimports += h

a = Analysis(
    [os.path.join(SPECPATH, 'xiaonuan_entry.py')],
    pathex=[REPO, COMPANION],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=['tkinter', 'matplotlib', 'PyQt5', 'PySide6', 'IPython', 'pytest'],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='Xiaonuan', console=True,
          upx=False)
coll = COLLECT(exe, a.binaries, a.datas, name='Xiaonuan', upx=False)
