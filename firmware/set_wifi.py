"""set_wifi.py - 一条命令写好 wifi.json（自动填本机 WLAN 的局域网 IP）

用法：
    python set_wifi.py --ssid "Xiaomi 15 Pro"            # 会提示你输密码（不回显）
    python set_wifi.py --ssid "Xiaomi 15 Pro" --ip 192.168.43.12
    python set_wifi.py --show                            # 只看现在配置了什么（密码打码）

密码只写进本机的 wifi.json，不会打印出来。
"""

import argparse
import getpass
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CFG = os.path.join(HERE, "wifi.json")


def wlan_ip():
    """取 WLAN 网卡的 IPv4（连手机热点时就是这个）。"""
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-NetIPAddress -AddressFamily IPv4 | "
             "Where-Object { $_.InterfaceAlias -like '*WLAN*' -or $_.InterfaceAlias -like '*Wi-Fi*' } | "
             "Select-Object -ExpandProperty IPAddress"],
            capture_output=True, text=True, timeout=15).stdout
        ips = [l.strip() for l in out.splitlines() if re.match(r"^\d+\.\d+\.\d+\.\d+$", l.strip())]
        return ips[0] if ips else ""
    except Exception:
        return ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ssid", default=None)
    ap.add_argument("--password", default=None, help="不给就交互输入（推荐，避免留在命令历史里）")
    ap.add_argument("--ip", default=None, help="电脑的局域网 IP，不给就自动找 WLAN 的")
    ap.add_argument("--port", type=int, default=5000)
    ap.add_argument("--show", action="store_true")
    args = ap.parse_args()

    cfg = {}
    if os.path.exists(CFG):
        try:
            cfg = json.load(open(CFG, encoding="utf-8"))
        except Exception:
            cfg = {}

    if args.show:
        pw = cfg.get("password", "")
        print("ssid    :", cfg.get("ssid", "(未设置)"))
        print("password:", ("*" * len(pw)) if pw else "(未设置)")
        print("host    :", cfg.get("host", "(未设置)"), " port:", cfg.get("port", 5000))
        return 0

    if not args.ssid:
        print('用法示例：python set_wifi.py --ssid "Xiaomi 15 Pro"')
        return 1
    password = args.password
    if password is None:
        password = getpass.getpass("WiFi 密码（输入时不显示）：")
    ip = args.ip or wlan_ip()
    if not ip:
        ip = cfg.get("host", "")
        print("!! 没找到 WLAN 的 IPv4，沿用旧值：%s" % ip)
        if not ip:
            print("   请手动加 --ip <电脑IP>")
            return 1

    cfg.update({
        "_说明": "ssid/password 是板子要连的 WiFi；host 是这台电脑在同一网络里的 IP。改完跑 python install_wifi.py",
        "ssid": args.ssid,
        "password": password,
        "host": ip,
        "port": args.port,
        "rate": 24000,
        "reconnect_ms": 2000,
    })
    with open(CFG, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    print("已写入 %s" % CFG)
    print("  网络 : %s" % args.ssid)
    print("  电脑 : %s:%d" % (ip, args.port))
    print("  密码 : %s（%d 位，不显示）" % ("*" * len(password), len(password)))
    print("下一步：python install_wifi.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
