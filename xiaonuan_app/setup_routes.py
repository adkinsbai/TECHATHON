"""设置页 /setup：填 DeepSeek 密钥、看模型/热点/防火墙/板子状态。只给本机 127.0.0.1 用。"""
import asyncio
import ctypes
import os
import pathlib
import socket
import subprocess
import sys

import httpx
from fastapi import HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

FIREWALL_RULE = "Xiaonuan body TCP 5000"
HOTSPOT_IP = "192.168.137.1"   # Windows 移动热点里电脑自己的固定地址
NO_WINDOW = 0x08000000         # CREATE_NO_WINDOW：查询防火墙时不闪黑框


class KeyIn(BaseModel):
    key: str = Field(min_length=8, max_length=200)


def _static(name):
    base = pathlib.Path(getattr(sys, "_MEIPASS", pathlib.Path(__file__).resolve().parent.parent))
    return base / "xiaonuan_app" / "static" / name


def _local_ipv4():
    try:
        return sorted({a[4][0] for a in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)})
    except OSError:
        return []


def _firewall_rule_exists(port):
    try:
        r = subprocess.run(["netsh", "advfirewall", "firewall", "show", "rule", f"name={FIREWALL_RULE}"],
                           capture_output=True, timeout=10, creationflags=NO_WINDOW)
        return r.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return None


def _save_key(env_path: pathlib.Path, key: str):
    """只改 DEEPSEEK_API_KEY 这一行，其余设置保留。"""
    lines = env_path.read_text(encoding="utf-8-sig").splitlines() if env_path.exists() else []
    lines = [line for line in lines if not line.strip().startswith("DEEPSEEK_API_KEY=")]
    lines.insert(0, f"DEEPSEEK_API_KEY={key}")
    env_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = env_path.with_suffix(".tmp")
    tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.replace(tmp, env_path)


def attach_setup_routes(app, *, home, link, hub, brain, config, body_port):
    home = pathlib.Path(home)

    @app.get("/setup")
    async def setup_page():
        return FileResponse(_static("setup.html"))

    @app.get("/api/setup/status")
    async def setup_status():
        ips = _local_ipv4()
        body = hub.snapshot()
        snap = link.snapshot()
        models_ready = (pathlib.Path(config.MODELS_DIR)
                        / "sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2025-09-09" / "model.int8.onnx").exists()
        return {
            "app": "xiaonuan",
            "key_set": bool(brain.DEEPSEEK_API_KEY),
            "models_ready": models_ready,
            "models_dir": str(config.MODELS_DIR),
            "home": str(home),
            "hotspot_on": HOTSPOT_IP in ips,
            "lan_ips": [ip for ip in ips if not ip.startswith("198.18.")],
            "firewall_rule": await asyncio.to_thread(_firewall_rule_exists, body_port),
            "tcp_port": body_port,
            "tcp_error": link.bind_error,
            "board_tcp": snap["connected"],
            "board_addr": snap["addr"],
            "board_phase": body.get("phase"),
            "board_ready": bool(body.get("connected")),
            "calibrated": bool((body.get("stats") or {}).get("calibrated")),
            "events": [f"{t}  {msg}" for t, msg in snap["events"][-6:]],
        }

    @app.post("/api/setup/key")
    async def setup_key(body: KeyIn):
        key = body.key.strip()
        if not key.isascii() or any(c.isspace() for c in key):
            raise HTTPException(422, "密钥格式不对：不能有空格或中文")
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                r = await client.get(f"{config.DEEPSEEK_BASE_URL}/models",
                                     headers={"Authorization": f"Bearer {key}"})
        except httpx.HTTPError as exc:
            raise HTTPException(502, f"连不上 DeepSeek（{type(exc).__name__}），请检查这台电脑能否上网") from None
        if r.status_code in (401, 403):
            raise HTTPException(400, "DeepSeek 说这个密钥无效，请重新复制")
        if r.status_code != 200:
            raise HTTPException(502, f"DeepSeek 返回 {r.status_code}，请稍后再试")
        await asyncio.to_thread(_save_key, pathlib.Path(config.ENV_PATH), key)
        # brain 在导入时拷贝了密钥，这里同步更新，不用重启就能聊天。
        config.DEEPSEEK_API_KEY = brain.DEEPSEEK_API_KEY = key
        return {"ok": True}

    @app.post("/api/setup/firewall")
    async def setup_firewall():
        """弹出 Windows 管理员确认，添加只放行本地子网访问 TCP 5000 的规则。"""
        args = (f'advfirewall firewall add rule name="{FIREWALL_RULE}" dir=in action=allow '
                f'protocol=TCP localport={body_port} remoteip=localsubnet profile=any')
        code = ctypes.windll.shell32.ShellExecuteW(None, "runas", "netsh", args, None, 0)
        if code <= 32:
            raise HTTPException(400, "没有获得管理员确认，防火墙没有改动")
        return {"ok": True}

    @app.post("/api/setup/open-hotspot")
    async def open_hotspot():
        os.startfile("ms-settings:network-mobilehotspot")
        return {"ok": True}
