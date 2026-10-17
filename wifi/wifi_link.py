"""wifi_link.py - WiFi 音频链路的公共部分（板子端/电脑端/假板子都用它）

帧格式（TCP，双向一致）：
    MAGIC(4) AA 55 AA 55 | type(1) | len(2, 小端) | payload(len) | 校验和(2, 小端)
    校验和 = (sum(payload) + type*31 + len) & 0xFFFF

消息类型：
    电脑 → 板子   AUD(0x01) PCM 立体声 16bit / MODE(0x02) 1 字节模式 / PING(0x03)
    板子 → 电脑   MIC(0x81) I2S RX 原始 32bit 立体声槽 / STAT(0x82) 8 字节状态
                  PONG(0x83) / LOG(0x84) 文本

TCP 本身保证不丢、不重、不乱序，所以串口那种"丢一个字节就错位"的问题从根上没有了；
校验和留作兜底（万一将来换成 UDP 也能用）。
"""

import audioop
import os
import socket
import struct
import sys
import threading
import time
import wave

MAGIC = b"\xaa\x55\xaa\x55"
HEADER = 7
TAIL = 2
MAX_PAYLOAD = 4096

T_AUD = 0x01
T_MODE = 0x02
T_PING = 0x03

T_MIC = 0x81
T_STAT = 0x82
T_PONG = 0x83
T_LOG = 0x84
T_SENS = 0x86

MODE_IDLE, MODE_PLAY, MODE_REC = 0, 1, 2
MODE_NAME = {MODE_IDLE: "空闲", MODE_PLAY: "播放", MODE_REC: "录音"}

RATE = 24000                       # 和板子端一致
AUD_FRAMES = 1024                  # 每个 AUD 帧的帧数（1024 帧 = 42ms）
AUD_BYTES = AUD_FRAMES * 4         # 立体声 16bit -> 4 字节/帧


def checksum(mtype, payload):
    return (sum(payload) + mtype * 31 + len(payload)) & 0xFFFF


def build_frame(mtype, payload):
    n = len(payload)
    head = MAGIC + bytes((mtype, n & 0xFF, (n >> 8) & 0xFF))
    chk = checksum(mtype, payload)
    return head + bytes(payload) + bytes((chk & 0xFF, chk >> 8))


def parse_stat(payload):
    """STAT 8 字节 → dict。"""
    if len(payload) < 8:
        return {}
    rssi = payload[6] - 256 if payload[6] > 127 else payload[6]
    return {
        "mode": MODE_NAME.get(payload[0], str(payload[0])),
        "fill": payload[1],
        "underruns": payload[2] | (payload[3] << 8),
        "resyncs": payload[4] | (payload[5] << 8),
        "rssi": rssi,
        "drops": payload[7],
    }


class Link:
    """TCP 服务端：等板子连上来，收发帧，并记录最近发生的事。"""

    def __init__(self, port=5000, on_mic=None, verbose=True):
        self.port = port
        self.on_mic = on_mic
        self.verbose = verbose
        self.client = None
        self.client_addr = ""
        self.send_lock = threading.Lock()
        self.state_lock = threading.Lock()
        self.events = []                 # [(hh:mm:ss, text)]
        self.stats = {}
        self.rx_bytes = 0
        self.tx_bytes = 0
        self.mic_bytes = 0
        self.last_rx = 0.0
        self.bind_error = ""
        self.bad_frames = 0
        self.force = {}
        self.conn_id = 0          # 每次有新连接就 +1，用来发现"板子重连了"
        threading.Thread(target=self._serve, daemon=True).start()

    # ------------------------------------------------------------- 日志
    def log(self, text):
        line = (time.strftime("%H:%M:%S"), text)
        with self.state_lock:
            self.events.append(line)
            del self.events[:-60]
        if self.verbose:
            print("%s  %s" % line, flush=True)

    @property
    def connected(self):
        return self.client is not None

    # --------------------------------------------------------- 服务端
    def _serve(self):
        srv = socket.socket()
        # Windows 上 SO_REUSEADDR 会让第二个进程把端口"抢"过去，所以只在非 Windows 用
        if not sys.platform.startswith("win"):
            srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            srv.bind(("0.0.0.0", self.port))
            srv.listen(1)
        except OSError as exc:
            self.bind_error = "%s（端口 %d 已被占用：是不是 wifi_demo.py 或 agent_demo.py 已经在跑？）" % (exc, self.port)
            self.log("!! " + self.bind_error)
            return
        self.log("TCP 服务已启动，监听 0.0.0.0:%d（等板子连进来）" % self.port)
        while True:
            try:
                c, addr = srv.accept()
            except OSError as exc:
                self.log("accept 出错：%s" % exc)
                time.sleep(1)
                continue
            c.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            # 发送超时：板子重启/掉线时 sendall 会卡死，5 秒后必须能自己放手
            c.settimeout(5.0)
            with self.state_lock:
                if self.client is not None:
                    try:
                        self.client.close()
                    except OSError:
                        pass
                self.client = c
                self.client_addr = "%s:%d" % addr
                self.conn_id += 1
            self.log("板子已连上：%s" % self.client_addr)
            threading.Thread(target=self._reader, args=(c,), daemon=True).start()

    def _reader(self, c):
        buf = bytearray()
        while True:
            try:
                data = c.recv(8192)
            except TimeoutError:
                continue
            except OSError:
                data = b""
            if not data:
                with self.state_lock:
                    if self.client is c:
                        self.client = None
                self.log("板子断开了：%s" % self.client_addr)
                try:
                    c.close()
                except OSError:
                    pass
                return
            self.last_rx = time.monotonic()
            self.rx_bytes += len(data)
            buf += data
            for mtype, payload in self._split(buf):
                if mtype == T_MIC:
                    self.mic_bytes += len(payload)
                    if self.on_mic:
                        try:
                            self.on_mic(payload)
                        except Exception as exc:
                            self.log("麦克风处理出错：%s" % exc)
                elif mtype == T_STAT:
                    st = parse_stat(payload)
                    with self.state_lock:
                        self.stats = st
                elif mtype == T_LOG:
                    self.log("板子：%s" % payload.decode("utf-8", "replace"))
                elif mtype == T_SENS and len(payload) >= 4:
                    force = {
                        "raw": payload[0] | (payload[1] << 8),
                        "mv": payload[2] | (payload[3] << 8),
                        "at": time.time(),
                    }
                    if len(payload) >= 8:   # 第二个力传感器（GPIO9）
                        force["raw2"] = payload[4] | (payload[5] << 8)
                        force["mv2"] = payload[6] | (payload[7] << 8)
                    self.force = force
                elif mtype == T_PONG:
                    pass

    def _split(self, buf):
        """从缓冲里切出完整帧。"""
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
            if n > MAX_PAYLOAD:
                del buf[:4]
                continue
            total = HEADER + n + TAIL
            if len(buf) < total:
                return out
            payload = bytes(buf[7:7 + n])
            chk = buf[7 + n] | (buf[8 + n] << 8)
            del buf[:total]
            if chk == checksum(mtype, payload):
                out.append((mtype, payload))
            else:
                self.bad_frames += 1
                if self.bad_frames <= 10:
                    self.log("坏帧 type=%d len=%d chk=%04x 期望=%04x（已丢弃）"
                             % (mtype, n, chk, checksum(mtype, payload)))

    # ------------------------------------------------------------- 发送
    def send(self, mtype, payload=b""):
        c = self.client
        if c is None:
            return False
        frame = build_frame(mtype, payload)
        try:
            with self.send_lock:
                c.sendall(frame)
            self.tx_bytes += len(frame)
            return True
        except OSError as exc:
            self.log("发送失败：%s（等板子重连）" % exc)
            with self.state_lock:
                # 只清掉"自己用的那条"旧连接，别把刚重连上来的新 socket 顶掉
                if self.client is c:
                    self.client = None
            return False

    def send_audio(self, pcm):
        return self.send(T_AUD, pcm)

    def set_mode(self, mode):
        ok = self.send(T_MODE, bytes((mode,)))
        if ok:
            self.log("已通知板子切到「%s」模式" % MODE_NAME.get(mode, mode))
        return ok

    def ping(self):
        return self.send(T_PING)

    def snapshot(self):
        with self.state_lock:
            return {
                "connected": self.client is not None,
                "addr": self.client_addr,
                "port": self.port,
                "stats": dict(self.stats),
                "events": list(self.events[-14:]),
                "rx_kb": round(self.rx_bytes / 1024.0, 1),
                "tx_kb": round(self.tx_bytes / 1024.0, 1),
                "mic_kb": round(self.mic_bytes / 1024.0, 1),
                "force": dict(self.force),
            }


class MicSink:
    """板子回传的是已经转好的 16bit 单声道 PCM（板子端只取左声道）。

    这样上行只要 48 KB/s；之前发原始 32bit 立体声是 192 KB/s，热点会丢采样。
    """

    def __init__(self, out_dir):
        self.out_dir = out_dir
        self.path = None
        self.wav = None
        self.frames = 0
        self.level = 0.0
        self.peak = 0
        os.makedirs(out_dir, exist_ok=True)

    def start(self):
        name = time.strftime("mic_%Y%m%d-%H%M%S.wav")
        self.path = os.path.join(self.out_dir, name)
        self.wav = wave.open(self.path, "wb")
        self.wav.setnchannels(1)
        self.wav.setsampwidth(2)
        self.wav.setframerate(RATE)
        self.frames = 0
        self.peak = 0
        return self.path

    def feed(self, payload):
        """返回本次的 16bit 单声道 PCM（bytes）。"""
        usable = len(payload) - (len(payload) & 1)
        if usable <= 0:
            return b""
        pcm = payload[:usable]
        if self.wav is not None:
            self.wav.writeframes(pcm)
            self.frames += usable // 2
        self.level = audioop.rms(pcm, 2) / 32768.0
        peak = audioop.max(pcm, 2)
        if peak > self.peak:
            self.peak = peak
        return pcm

    def stop(self):
        if self.wav is not None:
            self.wav.close()
            self.wav = None
        return self.path

    @property
    def seconds(self):
        return self.frames / float(RATE)
