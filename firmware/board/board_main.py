"""board_main.py - 板子端：音频数据走 WiFi（TCP），ESP32-S3 + ES8311 音箱 + INMP441 麦克风

和有线版的区别只有"数据从哪来"，音频那套（ES8311 初始化顺序、MCLK 用 I2S1 生成、
音量寄存器映射）一个字都没改。

播放：TCP 收到 AUD 帧 → 写进 PSRAM 环形缓冲（默认 1 秒）→ I2S0 输出
录音：I2S0 切成 RX（INMP441 和音箱共用 BCLK/WS）→ MIC 帧回传电脑
半双工：一路 I2S 不能同时收发，由电脑发 MODE 帧切换（0 空闲 / 1 播放 / 2 录音）

配置在 wifi.json：{"ssid":..., "password":..., "host":"电脑IP", "port":5000}
"""

import gc
import json
import select
import socket
import struct
import time

from machine import ADC, I2S, Pin

from es8311 import ES8311

# ------------------------------------------------------------------ 协议
MAGIC = b"\xaa\x55\xaa\x55"
HEADER = 7                      # MAGIC(4) + type(1) + len(2)
TAIL = 2                        # 校验和(2)

T_AUD = 0x01                    # 电脑 -> 板子：PCM 立体声 16bit
T_MODE = 0x02                   # 电脑 -> 板子：1 字节模式
T_PING = 0x03

T_MIC = 0x81                    # 板子 -> 电脑：I2S RX 原始数据（32bit 立体声槽）
T_STAT = 0x82
T_PONG = 0x83
T_LOG = 0x84
T_SENS = 0x86                   # 板子 -> 电脑：力传感器 raw + 毫伏

FSR_PIN = 8                     # 力传感器信号 -> GPIO8 (ADC1_CH7)

# ------------------------------------------------------------------ 音频
RATE = 24000
RING_SECONDS = 2.0                      # 2 秒：给"提前量 1 秒 + 网络抖动"留出余量，避免冲满丢帧
BUF_SIZE = int(RATE * 4 * RING_SECONDS)     # 立体声 16bit：4 字节/帧 -> 96 KB
WRITE_CHUNK = 4096                          # 每次交给 I2S 的字节数
MIC_READ = 2048                             # 每次从麦克风读进来的字节数
MAX_PAYLOAD = 4096

MODE_IDLE, MODE_PLAY, MODE_REC = 0, 1, 2


def checksum(mtype, payload):
    return (sum(payload) + mtype * 31 + len(payload)) & 0xFFFF


def build_frame(mtype, payload, buf):
    """把一帧写进预分配的 buf，返回写好的长度。"""
    n = len(payload)
    buf[0:4] = MAGIC
    buf[4] = mtype
    buf[5] = n & 0xFF
    buf[6] = (n >> 8) & 0xFF
    buf[7:7 + n] = payload
    chk = checksum(mtype, payload)
    buf[7 + n] = chk & 0xFF
    buf[8 + n] = chk >> 8
    return HEADER + n + TAIL


def send_all(sock, data):
    """非阻塞 socket 的 send() 可能只发出去一部分，必须循环到发完。
    （之前只调用一次 send，缓冲区一满就会把一帧截断，电脑端就整条流错位。）"""
    mv = memoryview(data)
    tries = 0
    while len(mv):
        try:
            n = sock.send(mv)
        except OSError:
            n = 0
        if n:
            mv = mv[n:]
            tries = 0
        else:
            tries += 1
            if tries > 500:          # 约 1 秒还没发出去，放弃这一帧
                return False
            time.sleep_ms(2)
    return True


class Ring:
    """播放环形缓冲：电脑先灌进来，I2S 慢慢取。"""

    def __init__(self, size):
        self.buf = bytearray(size)
        self.size = size
        self.head = 0            # 写入位置
        self.tail = 0            # 读出位置
        self.starved_at = time.ticks_ms()
        self.underruns = 0
        self.played = False

    def level(self):
        return (self.head - self.tail) % self.size

    def clear(self):
        """模式切换时丢掉旧语音，不在下一次播放中重放。"""
        self.head = 0
        self.tail = 0
        self.played = False
        self.starved_at = time.ticks_ms()

    def free(self):
        return self.size - 1 - self.level()

    def write(self, data):
        n = len(data)
        if n > self.free():
            return False                      # 缓冲满：电脑发太快了，丢掉这一帧
        end = self.head + n
        if end <= self.size:
            self.buf[self.head:end] = data
        else:
            cut = self.size - self.head
            self.buf[self.head:] = data[:cut]
            self.buf[:n - cut] = data[cut:]
        self.head = end % self.size
        return True

    def take(self, n):
        """取出最多 n 字节并推进 tail，返回 memoryview（可能跨回绕处一段）。"""
        avail = self.level()
        if avail == 0:
            return None
        n = min(n, avail)
        end = self.tail + n
        if end <= self.size:
            mv = memoryview(self.buf)[self.tail:end]
            self.tail = end % self.size
            return mv
        cut = self.size - self.tail
        mv = memoryview(self.buf)[self.tail:self.size]
        self.tail = 0                         # 只交出回绕前那一段，剩下的下一轮再取
        return mv

    def note_starved(self):
        """缓冲空了：算一次欠载（每停一次只记一次）。"""
        if not self.played:
            return
        now = time.ticks_ms()
        if time.ticks_diff(now, self.starved_at) > 400:
            self.underruns += 1
            self.starved_at = now


class Audio:
    """播放/录音两种模式，切换时重建 I2S0（MCLK 那条 I2S1 一直不停）。"""

    def __init__(self, codec):
        self.codec = codec
        self.port = None
        self.mode = MODE_IDLE

    def _make_tx(self):
        # 32KB ≈ 0.34 秒（有线版验证过的值）。再大（64KB）DMA 会填满后不排空，直接卡死。
        return I2S(0, sck=Pin(14), ws=Pin(12), sd=Pin(11), mode=I2S.TX,
                   bits=16, format=I2S.STEREO, rate=RATE, ibuf=32768)

    def prepare(self):
        """在 WiFi 起来之前把播放用的 I2S 建好（WiFi 之后再分配容易失败）。"""
        try:
            self.port = self._make_tx()
            self.mode = MODE_PLAY
            print("I2S-TX-READY")
            return True
        except Exception as exc:
            print("I2S-TX-FAIL", repr(exc))
            return False

    def set_mode(self, mode):
        if mode == self.mode:
            return
        # 注意：MCLK 开起来之后绝对不能再写 ES8311 的 I2C（会 NACK/ENODEV），
        # 所以这里只切 I2S，不动 codec 寄存器。静音靠"不喂数据"实现。
        if self.port is not None:
            try:
                self.port.deinit()
            except Exception:
                pass
            self.port = None
            time.sleep_ms(20)
        if mode == MODE_PLAY:
            self.port = self._make_tx()
            print("MODE-PLAY")
        elif mode == MODE_REC:
            # 32 位槽 = 64 个 BCLK/帧，正是 INMP441 要求的时序
            self.port = I2S(0, sck=Pin(14), ws=Pin(12), sd=Pin(13), mode=I2S.RX,
                            bits=32, format=I2S.STEREO, rate=RATE, ibuf=8192)
            print("MODE-REC")
        self.mode = mode

    def read_mic(self, buf):
        if self.port is None:
            return 0
        return self.port.readinto(buf)


def init_codec():
    """和有线版完全一样的初始化顺序：先 I2C 配 codec，再开 MCLK/I2S。"""
    codec = ES8311()
    codec.init(sample_rate=RATE, use_mclk=True)
    codec.start()
    codec.mute(False)
    codec.volume(0)                       # 全量输出，音量在电脑端做
    mclk = I2S(1, sck=Pin(6), ws=Pin(21), sd=Pin(47), mode=I2S.TX,
               bits=32, format=I2S.STEREO, rate=96000, ibuf=1024)   # BCLK=6.144MHz
    time.sleep_ms(80)
    return codec, mclk


def wifi_connect(cfg):
    import network
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    try:
        # 关掉 WiFi 省电：不然射频会周期性打盹，音频会一顿一顿的
        wlan.config(pm=network.WLAN.PM_NONE)
        print("wifi pm: NONE")
    except Exception as exc:
        print("wifi pm set failed:", exc)
    if wlan.isconnected():
        return wlan
    for attempt in range(4):
        print("connecting wifi:", cfg["ssid"], "attempt", attempt + 1)
        try:
            wlan.connect(cfg["ssid"], cfg["password"])
        except OSError as exc:
            # 常见于上一次连接还没结束（sta is connecting），等一下再来
            print("wifi connect error:", exc)
        t0 = time.time()
        while not wlan.isconnected() and time.time() - t0 < 15:
            time.sleep(0.3)
        if wlan.isconnected():
            print("wifi ok:", wlan.ifconfig())
            return wlan
        print("wifi retry after status", wlan.status())
        try:
            wlan.disconnect()
        except Exception:
            pass
        try:
            wlan.active(False)
            time.sleep(0.6)
            wlan.active(True)
            time.sleep(1.5)
        except Exception:
            pass
    print("wifi failed, last status", wlan.status())
    return wlan


def tcp_connect(cfg):
    try:
        s = socket.socket()
        # 尽量把接收窗口开大：lwIP 的窗口大小跟着 SO_RCVBUF 走，
        # 这样 WiFi 抖一下时数据还躺在板子的 TCP 缓冲里。
        try:
            # 这个固件没有导出 SOL_SOCKET / SO_RCVBUF 常量，用 lwIP 的数值
            s.setsockopt(1, 0x1002, 32768)          # SOL_SOCKET=1, SO_RCVBUF=0x1002
            print("rcvbuf", s.getsockopt(1, 0x1002))
        except Exception as exc:
            print("rcvbuf set failed:", exc)
        s.settimeout(3)
        s.connect((cfg["host"], int(cfg["port"])))
        s.settimeout(0)
        s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        print("tcp ok ->", cfg["host"], cfg["port"])
        return s
    except Exception as exc:
        print("tcp connect failed:", exc)
        try:
            s.close()
        except Exception:
            pass
        return None


def parse_frames(rx, stats, out):
    """从 rx(bytes) 里切出完整帧，返回还剩的字节。顺带统计失步次数。

    注意：这个 MicroPython 版本的 bytearray 不支持 del，所以这里全程用 bytes 切片。
    """
    while True:
        i = rx.find(MAGIC)
        if i < 0:
            return rx[-4:] if len(rx) > 4 else rx   # 可能剩半个 MAGIC，留着
        if i:
            rx = rx[i:]
            stats["resyncs"] += 1
        if len(rx) < HEADER:
            return rx
        mtype = rx[4]
        n = rx[5] | (rx[6] << 8)
        total = HEADER + n + TAIL
        if n > MAX_PAYLOAD:
            rx = rx[4:]                       # 长度不合理：丢掉一个 MAGIC 重新找
            stats["resyncs"] += 1
            continue
        if len(rx) < total:
            return rx
        payload = rx[7:7 + n]
        chk = rx[7 + n] | (rx[8 + n] << 8)
        rx = rx[total:]
        if chk == checksum(mtype, payload):
            out.append((mtype, payload))
        else:
            stats["resyncs"] += 1


def run():
    cfg = json.load(open("wifi.json"))
    rate = int(cfg.get("rate", RATE))
    assert rate == RATE, "采样率要跟电脑端一致（24000）"

    codec, mclk = init_codec()
    audio = Audio(codec)
    ring = Ring(BUF_SIZE)
    print("RING", len(ring.buf))
    audio.prepare()                 # 先把 I2S0 TX 建好，再开 WiFi
    wlan = wifi_connect(cfg)

    sock = None
    rx = b""
    frames = []
    txbuf = bytearray(HEADER + MIC_READ + TAIL)
    micbuf = bytearray(MIC_READ)
    stats = {"resyncs": 0, "drops": 0, "mode": MODE_IDLE}
    sent_mic = 0
    last_stat = time.ticks_ms()
    last_log = time.ticks_ms()
    last_write_ms = time.ticks_ms()
    last_sens = time.ticks_ms()
    try:
        fsr = ADC(Pin(FSR_PIN))
        fsr.atten(ADC.ATTN_11DB)       # 量程约 0–3.3V
        print("FSR on GPIO%d ready" % FSR_PIN)
    except Exception as exc:
        fsr = None
        print("FSR init failed:", repr(exc))

    while True:
        # ---------------------------------------------------- 1) 网络
        if sock is None:
            if not wlan.isconnected():
                wifi_connect(cfg)
            sock = tcp_connect(cfg)
            if sock is None:
                time.sleep_ms(int(cfg.get("reconnect_ms", 2000)))
                continue
            rx = b""
            ring = Ring(BUF_SIZE)
            audio.set_mode(MODE_IDLE)
            n = build_frame(T_LOG, b"board online", txbuf)
            try:
                sock.send(txbuf[:n])
            except Exception:
                pass
            last_log = time.ticks_ms()

        try:
            r, _, _ = select.select([sock], [], [], 0)
        except Exception:
            r = []

        if r:
            # 关键：把 socket 里排队的包一次读干（非阻塞，读空为止）。
            # 只读一块就去写 I2S 的话，写会阻塞 42ms，收数据就被钉死在实时速率上，
            # 电脑端提前灌进来的 1 秒余量永远进不了 ring。
            peer_gone = False
            for _ in range(64):
                try:
                    data = sock.recv(4096)
                except OSError:
                    break                      # 读空了（非阻塞）
                if not data:
                    peer_gone = True
                    break
                rx = rx + data
            if peer_gone:
                print("peer closed, reconnecting")
                try:
                    sock.close()
                except Exception:
                    pass
                sock = None
                continue
            frames.clear()
            rx = parse_frames(rx, stats, frames)
            for mtype, payload in frames:
                try:
                    if mtype == T_AUD:
                        if not ring.write(payload):
                            stats["drops"] += 1       # 缓冲满：电脑发太快了
                    elif mtype == T_MODE:
                        mode = payload[0] if payload else MODE_IDLE
                        if mode != audio.mode:
                            ring.clear()
                        audio.set_mode(mode)
                        stats["mode"] = audio.mode
                    elif mtype == T_PING:
                        n = build_frame(T_PONG, b"", txbuf)
                        if not send_all(sock, txbuf[:n]):
                            sock = None
                except Exception as exc:
                    # 一帧出错不该把整个程序带走
                    print("FRAME-ERR", mtype, repr(exc))

        # ---------------------------------------------------- 2) 播放
        if audio.mode == MODE_PLAY:
            if ring.level() >= WRITE_CHUNK:
                piece = ring.take(WRITE_CHUNK)
                if piece is not None:
                    try:
                        audio.port.write(piece)
                        last_write_ms = time.ticks_ms()
                    except Exception as exc:
                        print("I2S-WRITE-ERR", repr(exc))
                        try:
                            audio.set_mode(MODE_IDLE)
                        except Exception:
                            pass
            elif ring.level() == 0:
                # 真的断粮：超过 120ms 没有任何数据写进 I2S（每段只记一次）
                if time.ticks_diff(time.ticks_ms(), last_write_ms) > 120:
                    stats["underruns"] = stats.get("underruns", 0) + 1
                    last_write_ms = time.ticks_ms()

        # ---------------------------------------------------- 3) 录音
        elif audio.mode == MODE_REC:
            try:
                n = audio.read_mic(micbuf)
                if n == 0 and time.ticks_diff(time.ticks_ms(), last_log) > 2000:
                    last_log = time.ticks_ms()
                    print("MIC-ZERO port=", audio.port is not None)
                if n >= 8:
                    # I2S RX 是 32bit 立体声槽，左槽是麦克风。只发 16bit 单声道：
                    # 192KB/s -> 48KB/s，热点才扛得住（之前丢 30% 采样就是这么来的）。
                    # 注意：这个 MicroPython 不支持带步长的切片（vals[0::2]），只能老老实实循环。
                    usable = n - (n % 8)
                    vals = struct.unpack("<%di" % (usable // 4), micbuf[:usable])
                    nframes = usable // 8
                    pcm = bytearray(nframes * 2)
                    k = 0
                    for i in range(nframes):
                        v = (vals[i * 2] >> 16) & 0xFFFF
                        pcm[k] = v & 0xFF
                        pcm[k + 1] = v >> 8
                        k += 2
                    ln = build_frame(T_MIC, pcm, txbuf)
                    if send_all(sock, txbuf[:ln]):
                        sent_mic += len(pcm)
                    else:
                        sock = None
            except Exception as exc:
                print("MIC-ERR", repr(exc))

        # ---------------------------------------------------- 4) 力传感器
        now = time.ticks_ms()
        if sock is not None and fsr is not None and time.ticks_diff(now, last_sens) > 100:
            last_sens = now
            try:
                raw = fsr.read()
                try:
                    mv = fsr.read_uv() // 1000
                except Exception:
                    mv = 0
                fs = bytearray(4)
                fs[0] = raw & 0xFF
                fs[1] = (raw >> 8) & 0xFF
                fs[2] = mv & 0xFF
                fs[3] = (mv >> 8) & 0xFF
                n = build_frame(T_SENS, fs, txbuf)
                if not send_all(sock, txbuf[:n]):
                    sock = None
            except Exception as exc:
                print("FSR-ERR", repr(exc))

        # ---------------------------------------------------- 5) 状态回报
        now = time.ticks_ms()
        if sock is not None and time.ticks_diff(now, last_stat) > 1000:
            last_stat = now
            try:
                rssi = wlan.status("rssi") if wlan.isconnected() else -127
            except Exception:
                rssi = -127
            st = bytearray(8)
            st[0] = audio.mode
            st[1] = min(100, ring.level() * 100 // max(1, BUF_SIZE))
            st[2] = stats.get("underruns", 0) & 0xFF
            st[3] = (stats.get("underruns", 0) >> 8) & 0xFF
            st[4] = stats["resyncs"] & 0xFF
            st[5] = (stats["resyncs"] >> 8) & 0xFF
            st[6] = rssi & 0xFF
            st[7] = min(255, stats["drops"])
            n = build_frame(T_STAT, st, txbuf)
            if not send_all(sock, txbuf[:n]):
                sock = None

        time.sleep_ms(1)
