"""小暖团队测试版入口：一个进程里同时跑 Companion（网页/聊天）和实体桥接（TCP 5000）。

- 用户数据和密钥放在 %APPDATA%\\Xiaonuan（可用环境变量 XIAONUAN_HOME 改），不放进程序目录；
- 识别模型优先用程序目录旁边的 models/，其次 %APPDATA%\\Xiaonuan\\models；
- 第一次打开（还没有密钥）自动进入 http://127.0.0.1:8765/setup 。
源码运行：python -m xiaonuan_app
"""
import asyncio
import json
import os
import pathlib
import socket
import subprocess
import sys
import time
import webbrowser

import httpx

APP_PORT = 8765
BODY_PORT = 5000
VOLUME = 10
SENSEVOICE_NAME = "sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2025-09-09"

NO_WINDOW = 0x08000000   # CREATE_NO_WINDOW
FROZEN = getattr(sys, "frozen", False)
REPO = pathlib.Path(__file__).resolve().parent.parent
APP_DIR = pathlib.Path(sys.executable).resolve().parent if FROZEN else REPO


def _prepare_environment():
    home = pathlib.Path(os.environ.get("XIAONUAN_HOME") or pathlib.Path(os.environ["APPDATA"]) / "Xiaonuan")
    home.mkdir(parents=True, exist_ok=True)
    os.environ["XIAONUAN_HOME"] = str(home)
    for candidate in (APP_DIR / "models", home / "models"):
        if (candidate / SENSEVOICE_NAME / "model.int8.onnx").exists():
            os.environ.setdefault("XIAONUAN_MODELS_DIR", str(candidate))
            break
    else:
        os.environ.setdefault("XIAONUAN_MODELS_DIR", str(home / "models"))
    if not FROZEN:
        # 源码运行：companion/ 里是 app 和 voice_pack，仓库根目录里是 body_bridge 和 wifi。
        for path in (REPO / "companion", REPO):
            if str(path) not in sys.path:
                sys.path.insert(0, str(path))
    return home


def _port_in_use(port):
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def app_version():
    """打包版读 build-info.json（构建脚本写入）；源码运行读 git 提交。"""
    try:
        info = json.loads((APP_DIR / "build-info.json").read_text(encoding="utf-8-sig"))
        return f"{info['commit']} · {info['built']}"
    except (OSError, ValueError, KeyError):
        pass
    if not FROZEN:
        try:
            commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=REPO, capture_output=True,
                                    text=True, timeout=5).stdout.strip()
            return f"源码 {commit}" if commit else "源码"
        except (OSError, subprocess.SubprocessError):
            return "源码"
    return "未知版本"


def _running_version():
    """8765 上没有程序返回 None；是小暖返回它的版本（旧版没有版本号）；是别的程序就报错，不去动它。"""
    if not _port_in_use(APP_PORT):
        return None
    try:
        r = httpx.get(f"http://127.0.0.1:{APP_PORT}/api/setup/status", timeout=3, trust_env=False)
        data = r.json()
        if r.status_code == 200 and data.get("app") == "xiaonuan":
            return data.get("version") or "旧版（没有版本号）"
    except (httpx.HTTPError, ValueError):
        pass
    raise SystemExit(f"端口 {APP_PORT} 被别的程序占用了，请先关掉它（或之前手动启动的小暖）再打开。")


def _listener_pid(port):
    out = subprocess.run(["netstat", "-ano", "-p", "TCP"], capture_output=True, text=True,
                         timeout=10, creationflags=NO_WINDOW).stdout
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 5 and parts[1].endswith(f":{port}") and parts[3] == "LISTENING":
            return int(parts[4])
    return None


def _stop_old_instance():
    """先请旧版自己退出；旧版没有这个接口时，只结束确认是 Xiaonuan.exe 的那个进程。"""
    try:
        httpx.post(f"http://127.0.0.1:{APP_PORT}/api/setup/shutdown", headers={"X-Xiaonuan": "takeover"},
                   timeout=3, trust_env=False)
    except httpx.HTTPError:
        pass
    for _ in range(40):
        if not _port_in_use(APP_PORT):
            return
        time.sleep(0.25)
    pid = _listener_pid(APP_PORT)
    if pid:
        image = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"], capture_output=True,
                               text=True, timeout=10, creationflags=NO_WINDOW).stdout
        if image.strip().strip('"').lower().startswith("xiaonuan.exe"):
            subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True, timeout=10,
                           creationflags=NO_WINDOW)
            for _ in range(40):
                if not _port_in_use(APP_PORT):
                    return
                time.sleep(0.25)
    raise SystemExit("旧版小暖还开着，没能自动关掉。请先关掉旧的黑色窗口，再重新打开 Xiaonuan.exe。")


async def _serve(home):
    import uvicorn
    from app import brain, config
    from app.server import app, body_hub
    from body_bridge.client import CompanionClient
    from body_bridge.runtime import Bridge
    from wifi.wifi_link import Link

    from .setup_routes import attach_setup_routes

    url = f"http://127.0.0.1:{APP_PORT}"
    link = Link(port=BODY_PORT)
    client = CompanionClient(url)
    bridge = Bridge(link, client, VOLUME, BODY_PORT)
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=APP_PORT, log_level="warning"))

    def request_shutdown():
        print("新版小暖要接手，这个窗口里的旧版正在退出。", flush=True)
        server.should_exit = True

    attach_setup_routes(app, home=home, link=link, hub=body_hub, brain=brain, config=config,
                        body_port=BODY_PORT, bridge=bridge, version=app_version(),
                        request_shutdown=request_shutdown)
    serving = asyncio.create_task(server.serve())
    while not server.started:
        if serving.done():
            serving.result()
            raise SystemExit("网页服务没能启动")
        await asyncio.sleep(0.1)

    page = "/" if config.DEEPSEEK_API_KEY else "/setup"
    print(f"小暖已启动（版本 {app_version()}）：{url}{page}", flush=True)
    print(f"设置（密钥、两只手）：{url}/setup", flush=True)
    print(f"数据和密钥：{home}", flush=True)
    print(f"识别模型：{config.MODELS_DIR}", flush=True)
    print("关闭这个窗口就会退出小暖。", flush=True)
    webbrowser.open(url + page)

    async def run_bridge():
        # 桥接出错（例如板子发来异常数据）只重启桥接，网页继续可用。
        while True:
            try:
                await bridge.run()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                print("实体桥接出错，2 秒后重试：", exc, flush=True)
                await asyncio.sleep(2)

    bridging = asyncio.create_task(run_bridge())
    try:
        await serving
    finally:
        bridging.cancel()
        await asyncio.gather(bridging, return_exceptions=True)
        await client.close()


def main():
    try:
        home = _prepare_environment()
        running, mine = _running_version(), app_version()
        if running == mine:
            print("小暖已经在运行，直接打开页面。")
            webbrowser.open(f"http://127.0.0.1:{APP_PORT}/")
            time.sleep(1)
            return
        if running:
            print(f"发现正在运行的另一个版本（{running}），正在关闭它，换成这个版本（{mine}）……", flush=True)
            _stop_old_instance()
        asyncio.run(_serve(home))
    except KeyboardInterrupt:
        pass
    except SystemExit as exc:
        if exc.code not in (None, 0):
            print(exc.code if isinstance(exc.code, str) else f"退出码 {exc.code}")
            if FROZEN:
                input("按回车关闭…")
        raise
    except Exception:
        import traceback
        traceback.print_exc()
        if FROZEN:
            input("小暖启动失败，请把上面的错误发给队友。按回车关闭…")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
