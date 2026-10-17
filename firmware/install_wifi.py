"""install_wifi.py - 把 WiFi 版写进板子（ESP32-S3 用 USB 线连着电脑）

这套写入分三步，专治"raw REPL 握手被开机日志搅乱"：
  1. 清场：中断正在跑的程序 → 把 main.py 改名挪开
  2. 硬复位：板子干净启动到 REPL（没有 main.py，不会再有报错刷屏）
  3. 分块写文件（每块 1KB，每块都等板子回 OK），只写大小不对的文件，最后核对大小

用法：
    python install_wifi.py                 # 自动找串口
    python install_wifi.py --port COM7
    python install_wifi.py --force         # 强制全部重写
    python install_wifi.py --check         # 只看板子上现在有什么
    python install_wifi.py --off           # 关掉 WiFi 版，回到有线版
"""

import argparse
import base64
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import serial
from serial.tools import list_ports

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
ES8311 = os.path.join(HERE, "board", "es8311.py")
BOARD_FILES = ["board_main.py", "main.py"]
CHUNK = 1024


def find_port():
    for p in list_ports.comports():
        if p.vid in (0x1A86, 0x303A, 0x10C4, 0x0403):
            return p.device
    return None


def open_board(port):
    s = serial.Serial()
    s.port = port
    s.baudrate = 115200
    s.timeout = 0.3
    s.dtr = False
    s.rts = False
    s.open()
    time.sleep(0.3)
    s.read(65536)
    return s


def hard_reset(s):
    s.dtr = False
    s.rts = True
    time.sleep(0.25)
    s.rts = False
    time.sleep(0.6)
    s.read(65536)


def friendly_line(s, line):
    s.write(line.encode() + b"\r")
    time.sleep(0.7)
    return s.read(4096)


def clean_start(s):
    """把正在跑的程序停掉、main.py 挪开，再硬复位到干净 REPL。"""
    for _ in range(2):
        s.write(b"\x03")
        time.sleep(0.25)
        s.read(8192)
    friendly_line(s, "import os")
    friendly_line(s,
                  "os.rename('main.py','main_bad.py') if 'main.py' in os.listdir() else None")
    friendly_line(s, "print('CLEAN-OK')")
    hard_reset(s)


def raw_enter(s):
    for _ in range(2):
        s.write(b"\x03")
        time.sleep(0.25)
        s.read(8192)
    s.write(b"\x01")
    time.sleep(0.35)
    s.read(4096)


def raw_exec(s, code, wait=10.0):
    s.write(code.encode() + b"\x04")
    buf = b""
    t0 = time.time()
    while time.time() - t0 < wait:
        d = s.read(4096)
        if d:
            buf += d
        if b"\x04>" in buf:
            break
    return buf


def remote_size(s, name):
    out = raw_exec(s,
                   "import os\n"
                   "try:\n print('SZ', os.stat('%s')[6])\n"
                   "except OSError:\n print('SZ', -1)\n" % name, wait=5.0)
    m = re.search(rb"SZ (-?\d+)", out)
    return int(m.group(1)) if m else None


def write_chunk(s, remote, mode, b64):
    code = ("import binascii\n"
            "f=open('%s','%s');f.write(binascii.a2b_base64('%s'));f.close()\n"
            "print('CHUNK')\n" % (remote, mode, b64))
    out = raw_exec(s, code, wait=8.0)
    if b"CHUNK" in out:
        return True
    raw_enter(s)                       # 可能握手丢了：重进 raw REPL 再试一次
    out = raw_exec(s, code, wait=8.0)
    return b"CHUNK" in out


def write_file(s, local, remote):
    """先写 remote.tmp，核对大小无误后才改名成 remote —— 传一半断了也不会污染原文件。"""
    data = open(local, "rb").read()
    tmp = remote + ".tmp"
    raw_exec(s, "import os\n"
                "os.remove('%s') if '%s' in os.listdir() else None\n"
                "print('RM-OK')\n" % (tmp, tmp), wait=4.0)
    done = 0
    first = True
    while done < len(data):
        piece = data[done:done + CHUNK]
        if not write_chunk(s, tmp, "wb" if first else "ab",
                           base64.b64encode(piece).decode()):
            print("  !! %s 在 %d 字节处失败" % (remote, done))
            raw_exec(s, "import os\n"
                        "os.remove('%s') if '%s' in os.listdir() else None\n" % (tmp, tmp),
                     wait=4.0)
            return False
        done += len(piece)
        first = False
    got = remote_size(s, tmp)
    ok = got == len(data)
    if ok:
        out = raw_exec(s, "import os\nos.rename('%s','%s')\nprint('RN-OK')\n" % (tmp, remote),
                       wait=4.0)
        ok = b"RN-OK" in out
    if ok:
        got = remote_size(s, remote)
        ok = got == len(data)
    print("  %-14s %6d 字节  %s" % (remote, len(data),
                                    "OK" if ok else "失败（板上 %s）" % got))
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", default=None)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--off", action="store_true")
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()

    port = args.port or find_port()
    if not port:
        print("找不到 ESP32 串口，插好 USB 或加 --port COMx")
        return 1
    print("串口：%s" % port)
    s = open_board(port)

    if args.check:
        clean_start(s)
        raw_enter(s)
        out = raw_exec(s, "import os\nprint('FILES', sorted(os.listdir()))\n")
        print(out.decode("utf-8", "replace")[-600:])
        s.close()
        return 0

    if args.off:
        clean_start(s)
        raw_enter(s)
        out = raw_exec(s,
                       "import os\n"
                       "os.remove('wifi_on.txt') if 'wifi_on.txt' in os.listdir() else None\n"
                       "f=open('player_on.txt','w');f.write('1');f.close()\n"
                       "print('OFF-OK')\n")
        print("已关闭 WiFi 版" if b"OFF-OK" in out else out[-300:])
        s.close()
        return 0

    if not os.path.exists(os.path.join(HERE, "wifi.json")):
        print("缺少 wifi.json：先跑 python set_wifi.py --ssid \"你的热点\"")
        s.close()
        return 1

    print("--- 清场（停程序、挪走 main.py、硬复位） ---")
    clean_start(s)
    print("--- 进入 raw REPL ---")
    raw_enter(s)

    todo = []
    if os.path.exists(ES8311):
        todo.append((ES8311, "es8311.py"))
    todo += [(os.path.join(HERE, "board", n), n) for n in BOARD_FILES]
    todo.append((os.path.join(HERE, "wifi.json"), "wifi.json"))

    ok = True
    for local, name in todo:
        size = os.path.getsize(local)
        if not args.force and remote_size(s, name) == size:
            print("  %-14s 已经是 %d 字节，跳过" % (name, size))
            continue
        print("  -- 写 %s --" % name)
        ok &= write_file(s, local, name)

    print("--- 打开机标志 ---")
    out = raw_exec(s,
                   "import os\n"
                   "f=open('wifi_on.txt','w');f.write('1');f.close()\n"
                   "os.remove('player_on.txt') if 'player_on.txt' in os.listdir() else None\n"
                   "print('FLAG-OK', 'wifi_on.txt' in os.listdir())\n")
    flag_ok = b"FLAG-OK True" in out
    print("  %s" % ("OK" if flag_ok else out[-200:]))

    print("--- 软复位 ---")
    raw_exec(s, "import machine\nmachine.soft_reset()\n", wait=2.0)
    s.close()

    if ok and flag_ok:
        print("写入完成：板子会连 WiFi，然后连电脑的 5000 端口。")
        print("电脑端要跑着 python wifi_demo.py（控制台 http://127.0.0.1:8081/）")
        return 0
    print("有文件没写成功，把上面的报错发出来。")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
