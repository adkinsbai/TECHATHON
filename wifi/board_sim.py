"""board_sim.py - 假板子：没有硬件时用来验电脑端

它模仿真板子的行为：连上电脑的 TCP 端口、收 AUD 帧并按实时速度"消耗"掉、
每秒回一帧 STAT；被切到录音模式时回传一段 440Hz 测试音（放在左声道），
所以电脑端存下来的 WAV 应该是一段能听出来的"滴滴"声。

用法：
    python board_sim.py                     # 读同目录 wifi.json 里的 host / port
    python board_sim.py --host 127.0.0.1 --port 5000
    python board_sim.py --silent            # 录音时回传静音，不生成测试音
"""

import argparse
import json
import math
import os
import select
import socket
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from wifi_link import (HEADER, MAGIC, MODE_IDLE, MODE_NAME, MODE_PLAY, MODE_REC,
                       RATE, T_AUD, T_LOG, T_MIC, T_MODE, T_PING, T_PONG, T_STAT,
                       TAIL, build_frame, checksum)

RING_SECONDS = 1.0
BUF_BYTES = int(RATE * 4 * RING_SECONDS)
CHUNK = 1024 * 4                       # 每次回传的麦克风字节数

# 440Hz 正弦表，避免每个采样都现算 sin
TABLE = [int(0.35 * 32767 * math.sin(2 * math.pi * i / 256)) for i in range(256)]


def make_mic_chunk(nbytes, phase, silent):
    """生成 I2S RX 那种 32bit 立体声槽数据：左槽有声音，右槽 0。"""
    frames = nbytes // 8
    out = bytearray(nbytes)
    if silent:
        return bytes(out), phase
    step = 256 * 440.0 / RATE
    for i in range(frames):
        t = (phase / (256 * 440.0)) % 1.6      # 1 秒响、0.6 秒停
        v = 0 if t > 1.0 else TABLE[int(phase) & 0xFF]
        # INMP441 输出 24 位数据、MSB 对齐：32 位槽里就是 v24<<8，这里 v 已经是 16 位幅度
        s32 = (v << 16) & 0xFFFFFFFF
        off = i * 8
        out[off] = s32 & 0xFF
        out[off + 1] = (s32 >> 8) & 0xFF
        out[off + 2] = (s32 >> 16) & 0xFF
        out[off + 3] = (s32 >> 24) & 0xFF
        phase += step
    return bytes(out), phase


def split(buf):
    out = []
    while True:
        i = buf.find(MAGIC)
        if i < 0:
            del buf[:max(0, len(buf) - 4)]
            return out
        if i:
            del buf[:i]
        if len(buf) < HEADER:
            return out
        mtype = buf[4]
        n = buf[5] | (buf[6] << 8)
        total = HEADER + n + TAIL
        if len(buf) < total:
            return out
        payload = bytes(buf[7:7 + n])
        chk = buf[7 + n] | (buf[8 + n] << 8)
        del buf[:total]
        if chk == checksum(mtype, payload):
            out.append((mtype, payload))


def connect(host, port):
    while True:
        try:
            s = socket.socket()
            s.settimeout(3)
            s.connect((host, port))
            s.settimeout(0)
            s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            return s
        except OSError as exc:
            print("连不上 %s:%d（%s），2 秒后重试" % (host, port, exc), flush=True)
            time.sleep(2)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default=None)
    ap.add_argument("--port", type=int, default=None)
    ap.add_argument("--silent", action="store_true")
    args = ap.parse_args()

    cfg = {}
    path = os.path.join(HERE, "wifi.json")
    if os.path.exists(path):
        cfg = json.load(open(path, encoding="utf-8"))
    host = args.host or cfg.get("host", "127.0.0.1")
    port = args.port or int(cfg.get("port", 5000))

    s = connect(host, port)
    print("已连上 %s:%d，开始模仿板子" % (host, port), flush=True)
    s.sendall(build_frame(T_LOG, "board-sim online".encode()))

    mode = MODE_IDLE
    buffered = 0.0
    rx = bytearray()
    phase = 0.0
    last = time.monotonic()
    last_stat = 0.0
    played = 0
    underruns = 0
    starved_at = 0.0
    rec_start = None
    rec_frames = 0

    while True:
        try:
            r, _, _ = select.select([s], [], [], 0.004)
        except OSError:
            r = []
        if r:
            try:
                data = s.recv(8192)
            except OSError:
                data = b""
            if not data:
                print("电脑端断开了", flush=True)
                return 0
            rx += data
            for mtype, payload in split(rx):
                if mtype == T_AUD:
                    buffered += len(payload)
                    played += len(payload)
                    if buffered > BUF_BYTES:
                        buffered = float(BUF_BYTES)
                elif mtype == T_MODE:
                    mode = payload[0] if payload else MODE_IDLE
                    print("模式 -> %s" % MODE_NAME.get(mode, mode), flush=True)
                    if mode == MODE_REC:
                        rec_start = time.monotonic()
                        rec_frames = 0
                elif mtype == T_PING:
                    s.sendall(build_frame(T_PONG, b""))

        now = time.monotonic()
        dt = now - last
        last = now
        if mode == MODE_PLAY:
            buffered -= dt * RATE * 4
            if buffered <= 0:
                buffered = 0.0
                if played and now - starved_at > 0.4:
                    underruns += 1
                    starved_at = now
        elif mode == MODE_REC:
            # 按 24kHz 实时速度回传，别比真板子跑得快
            if rec_start is None:
                rec_start = now
                rec_frames = 0
            ahead = rec_frames / float(RATE) - (now - rec_start)
            if ahead > 0.02:
                time.sleep(ahead)
                continue
            chunk, phase = make_mic_chunk(CHUNK, phase, args.silent)
            rec_frames += CHUNK // 8
            try:
                s.sendall(build_frame(T_MIC, chunk))
            except OSError:
                return 0

        if now - last_stat >= 1.0:
            last_stat = now
            st = bytearray(8)
            st[0] = mode
            st[1] = min(100, int(buffered * 100 // BUF_BYTES))
            st[2] = underruns & 0xFF
            st[3] = (underruns >> 8) & 0xFF
            st[6] = 256 - 45                      # 假装 RSSI = -45dBm
            s.sendall(build_frame(T_STAT, st))
            print("STAT 模式=%s 缓冲=%d%% 已收=%dKB 欠载=%d"
                  % (MODE_NAME.get(mode, mode), st[1], played // 1024, underruns),
                  flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
