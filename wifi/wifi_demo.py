"""wifi_demo.py - 电脑端：WiFi 音频链路 + 网页控制台（http://127.0.0.1:8081）

和有线版（根目录 web_demo.py）的区别只有"数据怎么发出去"：
音频走 TCP 到板子，板子回传麦克风数据。曲库、音量、解码还是同一套。

跑：python wifi_demo.py
没硬件时先验电脑端：另开一个窗口跑 python board_sim.py
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import wave
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import audioop
import miniaudio

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

from wifi_link import (AUD_BYTES, AUD_FRAMES, MODE_IDLE, MODE_PLAY, MODE_REC, RATE,
                       Link, MicSink)


def tts_to_wav(text, path):
    """用 Windows 自带语音合成把文字转成 WAV（离线，不需要 key）。优先挑中文音色。"""
    txt = path + ".txt"
    with open(txt, "w", encoding="utf-8") as f:
        f.write(text)
    ps = path + ".ps1"
    lines = [
        "Add-Type -AssemblyName System.Speech",
        "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer",
        "$v = $s.GetInstalledVoices() | ForEach-Object { $_.VoiceInfo.Name }",
        "$zh = $v | Where-Object { $_ -match 'Chinese|Huihui|Yaoyao|Kangkang|Xiaoxiao|Tingting' } | Select-Object -First 1",
        "if ($zh) { $s.SelectVoice($zh) }",
        "$s.Rate = 0",
        "$s.SetOutputToWaveFile('%s')" % path,
        "$s.Speak([IO.File]::ReadAllText('%s', [Text.Encoding]::UTF8))" % txt,
        "$s.Dispose()",
    ]
    with open(ps, "w", encoding="utf-8-sig") as f:
        f.write("\n".join(lines))
    subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", ps],
                   check=True, capture_output=True)
    for p in (txt, ps):
        try:
            os.remove(p)
        except OSError:
            pass
    return path

HTTP_PORT = 8081
TCP_PORT = 5000

MUSIC_ROOTS = [
    r"D:\CloudMusic",
    os.path.join(ROOT, "music"),
]
REC_DIR = os.path.join(HERE, "recordings")
INBOX = os.path.join(HERE, "inbox")          # 录完自动放这里，方便直接拖进对话
REPLY_FILE = os.path.join(HERE, "reply.txt")  # 外界（Codex / 你自己）写一句话，音箱自动念
# 复用有线版那份"哪些文件能播"的校验缓存，省得重新探一遍
PROBE_CACHE = os.path.join(HERE, "probe_cache.json")   # 本目录下，首次运行会自动生成
SKIP_DIRS = {"cache"}
AUDIO_EXT = (".mp3", ".flac", ".wav", ".ogg")

CHUNK = AUD_BYTES                  # 每个 AUD 帧的字节数
LEAD_SECONDS = 1.0                 # 提前量：板子 DMA 0.34s + socket/内核缓冲，一起抗抖动
FEED_GAP_WARN = 0.35


def split_name(filename):
    base = os.path.splitext(filename)[0]
    if " - " in base:
        left, right = base.split(" - ", 1)
        return left.strip(), right.strip()
    return "", base.strip()


def fingerprint(path):
    st = os.stat(path)
    return [st.st_size, int(st.st_mtime)]


class Player:
    def __init__(self):
        self.lock = threading.RLock()
        self.wake = threading.Event()
        self.tracks = []
        self.index = 0
        self.state = "stopped"
        self.volume = 10
        self.error = ""
        self.unsupported = 0
        self.pos_frames = 0
        self.durations = {}
        self.playable = {}
        self.probe = {}
        self.cache = self._load_cache()
        self.stage = ("idle", time.monotonic())
        self.gaps = []
        self.recording = False
        self.speaking = False
        self.inbox_latest = {}
        self.reply_text = ""
        self.transcript = ""
        self.auto_reply = True
        self.reply_mode = "agent"        # agent = 交给 Codex（写 reply.txt）；local = 本地规则
        self.lead = LEAD_SECONDS        # 自适应提前量（按板子回报的缓冲水位调）
        self.mic = MicSink(REC_DIR)
        self.link = Link(TCP_PORT, on_mic=self._on_mic)
        self.scan()
        threading.Thread(target=self._loop, daemon=True).start()
        threading.Thread(target=self._rescan_loop, daemon=True).start()
        threading.Thread(target=self._probe_loop, daemon=True).start()
        threading.Thread(target=self._reply_loop, daemon=True).start()

    # ---------------------------------------------------------------- 曲库
    def scan(self):
        found = []
        seen = set()
        unsupported = 0
        for root in MUSIC_ROOTS:
            if not os.path.isdir(root):
                continue
            for dirpath, dirnames, filenames in os.walk(root):
                dirnames[:] = [d for d in dirnames if d.lower() not in SKIP_DIRS]
                for name in filenames:
                    ext = os.path.splitext(name)[1].lower()
                    if ext in AUDIO_EXT:
                        key = name.lower()
                        if key in seen:
                            continue
                        seen.add(key)
                        artist, title = split_name(name)
                        found.append({"title": title, "artist": artist,
                                      "path": os.path.join(dirpath, name)})
                    elif ext in (".ncm", ".uc", ".uc!", ".mflac", ".mgg"):
                        unsupported += 1
        found.sort(key=lambda t: (t["artist"].lower(), t["title"].lower()))
        known = {}
        for i, t in enumerate(found):
            ok = self.probe.get(t["path"])
            if ok is None:
                ent = self.cache.get(t["path"])
                if ent:
                    try:
                        if (ent[0] == os.path.getsize(t["path"])
                                and ent[1] == int(os.path.getmtime(t["path"]))):
                            ok = bool(ent[2])
                            self.probe[t["path"]] = ok
                    except OSError:
                        pass
            if ok is not None:
                known[i] = ok
        with self.lock:
            self.tracks = found
            self.unsupported = unsupported
            self.playable = known
            if self.index >= len(found):
                self.index = 0

    def _load_cache(self):
        try:
            with open(PROBE_CACHE, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _save_cache(self):
        try:
            with self.lock:
                data = dict(self.cache)
            tmp = PROBE_CACHE + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f)
            os.replace(tmp, PROBE_CACHE)
        except Exception:
            pass

    def _rescan_loop(self):
        while True:
            time.sleep(20)
            try:
                self.scan()
            except Exception:
                pass

    def _probe_loop(self):
        saved = 0
        while True:
            try:
                with self.lock:
                    pending = [(i, t["path"]) for i, t in enumerate(self.tracks)
                               if t["path"] not in self.probe]
                    busy = self.state == "playing"
                if busy or not pending:
                    time.sleep(3)
                    continue
                for idx, path in pending:
                    ok = True
                    try:
                        miniaudio.decode_file(path, output_format=miniaudio.SampleFormat.SIGNED16,
                                              nchannels=1, sample_rate=8000)
                    except Exception:
                        ok = False
                    with self.lock:
                        self.playable[idx] = ok
                        self.probe[path] = ok
                    try:
                        self.cache[path] = fingerprint(path) + [ok]
                        saved += 1
                    except OSError:
                        pass
                    if saved >= 10:
                        self._save_cache()
                        saved = 0
                    if not ok:
                        print("unplayable (skipped):", os.path.basename(path))
                    time.sleep(0.05)
                if saved:
                    self._save_cache()
                    saved = 0
            except Exception:
                time.sleep(3)

    # -------------------------------------------------------------- 麦克风
    def _on_mic(self, payload):
        if not self.recording:
            return
        self.mic.feed(payload)

    def toggle_record(self):
        if self.recording:
            self.link.set_mode(MODE_IDLE)
            path = self.mic.stop()
            self.recording = False
            self.link.log("录音结束：%s（%.1f 秒）"
                          % (os.path.basename(path or ""), self.mic.seconds))
            inbox_path = self._deliver_to_inbox(path)
            self.link.log("正在识别……（本地 Vosk，小模型）")
            threading.Thread(target=self._understand, args=(inbox_path or path,),
                             daemon=True).start()
        else:
            with self.lock:
                self.state = "paused"
            self.wake.set()
            time.sleep(0.15)                    # 让播放线程先把播放模式收掉
            self.mic.start()
            self.recording = True
            self.link.set_mode(MODE_REC)
        return self.recording

    # ------------------------------------------------------------ 听懂+回话
    def _understand(self, path):
        """录音落盘后：本地识别 → 生成回复 → 推给板子念出来。"""
        if not path or not os.path.exists(path):
            return
        t0 = time.time()
        try:
            from asr import transcribe_wav
            text = transcribe_wav(path)
        except Exception as exc:
            self.link.log("识别失败：%r" % exc)
            return
        cost = time.time() - t0
        with self.lock:
            self.transcript = text
        self.link.log("听到（%.2fs）：%s" % (cost, text or "（没听清）"))
        if not text:
            return
        if self.reply_mode == "agent":
            # 把识别结果交给 Codex：写一个 pending.txt，等 Codex 往 reply.txt 里写回复
            try:
                with open(os.path.join(INBOX, "pending.txt"), "w", encoding="utf-8") as f:
                    f.write("时间: %s\n文件: %s\n识别: %s\n\n"
                            "请把回复写进 wifi\\reply.txt（一句话即可，音箱会念出来）。\n"
                            % (time.strftime("%Y-%m-%d %H:%M:%S"),
                               os.path.basename(path), text))
            except Exception as exc:
                self.link.log("写 pending.txt 失败：%r" % exc)
            self.link.log("已交给 Codex（识别结果在 inbox\\pending.txt）")
            return
        if not self.auto_reply:
            self.link.log("自动回复已关闭：把想说的话写进 reply.txt 就行")
            return
        try:
            from brain import reply_for
            reply, action = reply_for(text, self)
        except Exception as exc:
            self.link.log("生成回复失败：%r" % exc)
            return
        if not reply:
            return
        with self.lock:
            self.reply_text = reply
        self.link.log("回复：%s" % reply)
        self.speak(reply)
        if action == "play":
            with self.lock:
                self.state = "playing"
            self.wake.set()
        elif action == "pause":
            with self.lock:
                self.state = "paused"
            self.wake.set()
        elif action in ("louder", "quieter"):
            with self.lock:
                self.volume = max(0, min(100, self.volume + (10 if action == "louder" else -10)))
            self.link.log("音量 -> %d%%" % self.volume)

    # ------------------------------------------------------------ 对话文件
    def _deliver_to_inbox(self, path):
        """录完自动复制一份到 inbox（带一个 .json 说明），方便直接拖进对话。"""
        if not path or not os.path.exists(path):
            return None
        try:
            os.makedirs(INBOX, exist_ok=True)
            name = "rec_%s.wav" % time.strftime("%Y%m%d-%H%M%S")
            dst = os.path.join(INBOX, name)
            shutil.copy2(path, dst)
            meta = {
                "file": name,
                "at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "seconds": round(self.mic.seconds, 2),
                "peak": self.mic.peak,
                "note": "把这个 wav 拖进 Codex 对话，然后把回复写进 reply.txt",
            }
            with open(os.path.join(INBOX, name + ".json"), "w", encoding="utf-8") as f:
                json.dump(meta, f, ensure_ascii=False, indent=2)
            with self.lock:
                self.inbox_latest = meta
            self.link.log("已放进 inbox：%s（%.1f 秒）" % (name, self.mic.seconds))
            return dst
        except Exception as exc:
            self.link.log("放进 inbox 失败：%r" % exc)
            return None

    def _reply_loop(self):
        """盯 reply.txt：谁往里写一句话，音箱就念出来。"""
        last = None
        while True:
            try:
                if os.path.exists(REPLY_FILE) and time.time() - os.stat(REPLY_FILE).st_mtime > 0.6:
                    with open(REPLY_FILE, encoding="utf-8") as f:
                        txt = f.read().strip()
                    if txt and txt != last:
                        last = txt
                        with self.lock:
                            self.reply_text = txt
                        if self.recording:
                            self.link.log("现在正在录音，reply.txt 的话等录完再说")
                            last = None
                        else:
                            self.link.log("reply.txt -> 音箱：%s" % txt[:40])
                            if self.speak(txt):
                                pend = os.path.join(INBOX, "pending.txt")
                                if os.path.exists(pend):
                                    try:
                                        os.replace(pend, os.path.join(
                                            INBOX, "done_%s.txt" % time.strftime("%H%M%S")))
                                    except OSError:
                                        pass
            except Exception as exc:
                self.link.log("reply 监看出错：%r" % exc)
            time.sleep(0.7)

    # ---------------------------------------------------------------- 说话
    def speak(self, text):
        """用 Windows 自带 TTS 把文字念出来，推给板子播放。"""
        text = (text or "").strip()
        if not text:
            return False
        with self.lock:
            self.state = "paused"           # 先把音乐停掉（半双工）
            self.speaking = True
        self.wake.set()
        time.sleep(0.2)
        tmp = os.path.join(tempfile.gettempdir(), "esp32_say.wav")
        try:
            tts_to_wav(text, tmp)
            with wave.open(tmp, "rb") as w:
                ch, width, rate = w.getnchannels(), w.getsampwidth(), w.getframerate()
                data = w.readframes(w.getnframes())
            if width != 2:
                data = audioop.lin2lin(data, width, 2)
            if ch == 2:
                data = audioop.tomono(data, 2, 0.5, 0.5)
            if rate != RATE:
                data, _ = audioop.ratecv(data, 2, 1, rate, RATE, None)
            with self.lock:
                vol = self.volume / 100.0
            data = audioop.mul(data, 2, vol)
            stereo = audioop.tostereo(data, 2, 1.0, 1.0)
            self.link.set_mode(MODE_PLAY)
            time.sleep(0.2)
            start = time.monotonic()
            sent = 0
            for off in range(0, len(stereo), AUD_BYTES):
                piece = stereo[off:off + AUD_BYTES]
                piece = piece.ljust(AUD_BYTES, b"\x00")
                # A failed send may have transmitted a partial frame. Abort rather than replay.
                if not self.link.send_audio(piece):
                    raise OSError("audio link disconnected during speech")
                sent += len(piece)
                target = sent / 4.0 / RATE - 0.3
                elapsed = time.monotonic() - start
                if target > elapsed:
                    time.sleep(target - elapsed)
            # Include the paced lead and the I2S DMA tail before clearing playback mode.
            time.sleep(max(0.0, sent / 4.0 / RATE - (time.monotonic() - start)) + 0.35)
            self.link.log("说了一句：%s" % text[:40])
            return True
        except Exception as exc:
            self.link.log("说话失败：%r" % exc)
            return False
        finally:
            self.link.set_mode(MODE_IDLE)
            with self.lock:
                self.speaking = False

    # -------------------------------------------------------------- 解码
    def duration(self, idx):
        with self.lock:
            if idx in self.durations:
                return self.durations[idx]
            path = self.tracks[idx]["path"]
        try:
            info = miniaudio.get_file_info(path)
            dur = round(info.num_frames / float(info.sample_rate or 1), 1)
        except Exception:
            dur = 0.0
        with self.lock:
            self.durations[idx] = dur
        return dur

    def stream(self, idx):
        with self.lock:
            path = self.tracks[idx]["path"]
        return miniaudio.stream_file(path, output_format=miniaudio.SampleFormat.SIGNED16,
                                     nchannels=1, sample_rate=RATE)

    # ------------------------------------------------------------ 播放循环
    def _stage(self, label):
        self.stage = (label, time.monotonic())

    def _loop(self):
        gen = None
        cur = None
        last_send = None
        prev_playing = False
        mode_conn = -1
        while True:
            with self.lock:
                state = self.state
                has = bool(self.tracks)
                idx = self.index
                recording = self.recording
            if state != "playing" or not has or recording:
                if prev_playing and not recording:      # 录音时不许把模式顶回空闲
                    self.link.set_mode(MODE_IDLE)
                    prev_playing = False
                last_send = None
                self.wake.wait(0.2)
                self.wake.clear()
                continue
            if self.link.client is None:
                if prev_playing:
                    prev_playing = False
                self.wake.wait(0.3)
                self.wake.clear()
                continue
            # 开始/恢复播放，或者板子重连过（重连会回到 IDLE），都要重新发 MODE_PLAY
            if not prev_playing or self.link.conn_id != mode_conn:
                self.link.set_mode(MODE_PLAY)
                mode_conn = self.link.conn_id
                pace_start = time.monotonic()
                pace_bytes = 0
                last_send = None
                prev_playing = True
            if gen is None or cur != idx:
                try:
                    self._stage("open idx=%d" % idx)
                    gen = self.stream(idx)
                    cur = idx
                    last_send = None
                    self._stage("idle")
                    self.link.log("NEWGEN idx=%d %s" % (idx, self.tracks[idx]["title"][:20]))
                    with self.lock:
                        self.pos_frames = 0
                        self.error = ""
                except Exception as exc:
                    self.error = "打不开这个文件: %s" % exc
                    with self.lock:
                        self.state = "stopped"
                    prev_playing = False
                    continue
            t_dec = time.monotonic()
            self._stage("decode idx=%d" % idx)
            try:
                chunk = next(gen)
                self._stage("idle")
            except StopIteration:
                gen = None
                self.link.log("EOF idx=%d pos=%.1fs" % (idx, self.pos_frames / float(RATE)))
                if self.index != idx:
                    continue
                self.error = ""
                with self.lock:
                    self.index = self._next_index(idx)
                continue
            except Exception as exc:
                gen = None
                pos_s = self.pos_frames / float(RATE)
                if self.index != idx:
                    continue
                self.link.log("解码出错 idx=%d pos=%.1fs: %r" % (idx, pos_s, exc))
                with self.lock:
                    self.index = self._next_index(idx)
                continue
            decode_time = time.monotonic() - t_dec
            if decode_time > FEED_GAP_WARN:
                self.link.log("解码慢了 %.2fs（idx=%d）" % (decode_time, idx))
            with self.lock:
                vol = self.volume
            factor = vol / 100.0
            raw = chunk.tobytes() if hasattr(chunk, "tobytes") else bytes(chunk)
            if factor < 0.9999:
                raw = audioop.mul(raw, 2, factor)
            chunk = audioop.tostereo(raw, 2, 1.0, 1.0)
            off = 0
            while off < len(chunk):
                with self.lock:
                    if self.state != "playing" or self.index != idx or self.recording:
                        break
                piece = chunk[off:off + CHUNK]
                self._stage("send idx=%d" % idx)
                if not self.link.send_audio(piece):
                    self._stage("idle")
                    # 连接断了：回到外层等重连，并且让外层重新发 MODE_PLAY
                    # （以前在这里原地重试，重连后板子还是 IDLE，就变成"显示播放但没声音"）
                    prev_playing = False
                    break
                self._stage("idle")
                off += len(piece)
                pace_bytes += len(piece)
                with self.lock:
                    self.pos_frames += len(piece) // 4
                now = time.monotonic()
                if last_send is not None and now - last_send > FEED_GAP_WARN:
                    gap = now - last_send
                    self.gaps.append((time.strftime("%H:%M:%S"), round(gap, 2)))
                    del self.gaps[:-20]
                    self.link.log("喂数据中断 %.2fs（idx=%d）" % (gap, idx))
                last_send = now
                # 自适应节流：板子缓冲 >75% 说明发快了（多睡一点），<25% 说明发慢了（少睡一点），
                # 目标是把板子的环形缓冲稳定在 50% 左右 —— 既不溢出也不断粮。
                fill = self.link.stats.get("fill", 50)
                # 提前量越大 = 电脑端越"抢跑" = 板子缓冲越高。
                # 所以缓冲太满要减小提前量，太空要加大（之前写反了，导致缓冲在 0 和 100% 之间振荡）
                if fill > 65:
                    self.lead = max(0.15, self.lead - 0.01)
                elif fill < 35:
                    self.lead = min(1.5, self.lead + 0.01)
                target = pace_bytes / 4.0 / RATE - self.lead
                elapsed = time.monotonic() - pace_start
                self.pace = (pace_bytes / 4.0 / RATE, elapsed, target)
                if target > elapsed:
                    time.sleep(target - elapsed)

    # ------------------------------------------------------------- 控制
    def _next_index(self, idx, step=1):
        n = len(self.tracks)
        unknown = None
        for k in range(1, n + 1):
            cand = (idx + k * step) % n
            status = self.playable.get(cand)
            if status is True:
                return cand
            if status is None and unknown is None:
                unknown = cand
        return unknown if unknown is not None else idx

    def play_index(self, idx):
        with self.lock:
            if not self.tracks:
                self.error = "没有找到可播放的音频文件"
                return
            if self.recording:
                self.error = "正在录音，先停止录音再播放"
                return
            idx = max(0, min(idx, len(self.tracks) - 1))
            if self.playable.get(idx) is False:
                self.error = "这首是加密/损坏文件，无法播放，已跳到下一首"
                self.index = self._next_index(idx)
            else:
                self.error = ""
                self.index = idx
            self.state = "playing"
        self.wake.set()

    def play_path(self, path):
        with self.lock:
            idx = None
            for i, t in enumerate(self.tracks):
                if t["path"] == path:
                    idx = i
                    break
        if idx is None:
            with self.lock:
                self.error = "这首歌已经不在音乐目录里了"
            return
        self.play_index(idx)

    def toggle(self):
        with self.lock:
            if self.recording:
                self.error = "正在录音，先停止录音再播放"
                return
            self.state = "paused" if self.state == "playing" else "playing"
        self.wake.set()

    def skip(self, step):
        with self.lock:
            if not self.tracks or self.recording:
                return
            self.index = self._next_index(self.index, step)
            self.state = "playing"
        self.wake.set()

    def set_volume(self, percent):
        with self.lock:
            self.volume = max(0, min(100, int(percent)))

    # -------------------------------------------------------------- 状态
    def state_json(self):
        with self.lock:
            cur = self.tracks[self.index] if self.tracks else None
            idx = self.index
            pos = self.pos_frames / float(RATE)
            stage, stamp = self.stage
            recording = self.recording
        dur = self.duration(idx) if cur else 0.0
        files = []
        if os.path.isdir(REC_DIR):
            files = sorted((f for f in os.listdir(REC_DIR) if f.endswith(".wav")),
                           reverse=True)[:6]
        with self.lock:
            return {
                "count": len(self.tracks),
                "unsupported": self.unsupported,
                "index": idx,
                "title": cur["title"] if cur else "",
                "artist": cur["artist"] if cur else "",
                "state": self.state,
                "position": round(pos, 1),
                "duration": dur,
                "volume": self.volume,
                "probing": sum(1 for i in range(len(self.tracks))
                               if i not in self.playable),
                "playlist": [{"i": i, "t": t["title"], "a": t["artist"], "p": t["path"]}
                             for i, t in enumerate(self.tracks)
                             if self.playable.get(i) is True],
                "error": self.error,
                "stage": "%s (%.1fs)" % (stage, time.monotonic() - stamp),
                "pace": [round(v, 2) for v in getattr(self, "pace", (0.0, 0.0, 0.0))],
                "gaps": list(self.gaps),
                "recording": recording,
                "mic": {
                    "level": round(self.mic.level, 3),
                    "peak": self.mic.peak,
                    "seconds": round(self.mic.seconds, 1),
                    "file": os.path.basename(self.mic.path or ""),
                },
                "recordings": files,
                "inbox": dict(self.inbox_latest),
                "reply": self.reply_text,
                "transcript": self.transcript,
                "auto_reply": self.auto_reply,
                "reply_mode": self.reply_mode,
                "speaking": self.speaking,
                "link": self.link.snapshot(),
            }


PLAYER = None


PAGE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ESP32 WiFi 音箱控制台</title>
<style>
  :root{--bg:#0b0d13;--panel:#151a24;--line:#252b39;--text:#e8edf5;--dim:#8b97ad;--accent:#00b894;--warn:#ff7b72;}
  *{box-sizing:border-box;margin:0;padding:0}
  body{background:radial-gradient(circle at 50% 0%,#16202e 0%,#0b0d13 60%);color:var(--text);
       font-family:-apple-system,"Segoe UI","Microsoft YaHei",sans-serif;padding:26px 16px;
       display:flex;justify-content:center;min-height:100vh}
  .wrap{width:100%;max-width:680px}
  h1{font-size:19px;font-weight:600;letter-spacing:.5px}
  .sub{color:var(--dim);font-size:12.5px;margin:6px 0 18px}
  .card{background:var(--panel);border:1px solid var(--line);border-radius:16px;padding:20px;margin-bottom:16px}
  h2{font-size:13px;font-weight:600;color:var(--dim);letter-spacing:1px;margin-bottom:14px}
  .song{font-size:17px;font-weight:600;margin-bottom:2px;height:24px;line-height:24px;
        overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
  .artist{color:var(--dim);font-size:13px;margin-bottom:16px;height:18px;line-height:18px;
        overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
  .bar{height:6px;background:#222836;border-radius:3px;overflow:hidden}
  .bar>i{display:block;height:100%;width:0;background:linear-gradient(90deg,#00b894,#00d2ff);transition:width .3s}
  .times{display:flex;justify-content:space-between;color:var(--dim);font-size:12px;margin:6px 0 18px}
  .row{display:flex;align-items:center;justify-content:center;gap:20px}
  button{background:#1e2432;color:var(--text);border:1px solid var(--line);border-radius:50%;
         width:52px;height:52px;font-size:18px;cursor:pointer;transition:.15s}
  button:hover{background:#28303f}
  button.main{width:66px;height:66px;background:var(--accent);border:none;font-size:23px;
              box-shadow:0 0 22px rgba(0,184,148,.4)}
  button.rec{border-radius:12px;width:auto;height:38px;padding:0 16px;font-size:14px;gap:8px}
  button.rec.on{background:var(--warn);border-color:var(--warn);color:#1a0c0a}
  .vol{display:flex;align-items:center;gap:12px;margin-top:20px;color:var(--dim);font-size:13px}
  .vol input{flex:1;accent-color:var(--accent)}
  input[type=search]{width:100%;background:#11151d;border:1px solid var(--line);color:var(--text);
       border-radius:10px;padding:10px 12px;font-size:13px;margin-bottom:10px;outline:none}
  ul{list-style:none;max-height:42vh;overflow:auto}
  li{padding:10px 12px;border-radius:10px;cursor:pointer;font-size:13.5px;color:var(--dim);
     display:flex;justify-content:space-between;gap:10px}
  li:hover{background:#1c222e;color:var(--text)}
  li.active{background:rgba(0,184,148,.16);color:#fff;border:1px solid rgba(0,184,148,.5)}
  li .t{color:inherit;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
  li .a{color:#6b7788;font-size:12px;flex:0 0 auto}
  .err{color:var(--warn);font-size:12.5px;min-height:16px;margin-top:10px}
  .foot{color:var(--dim);font-size:11.5px;margin-top:12px;line-height:1.7}
  .kv{display:grid;grid-template-columns:auto 1fr;gap:8px 14px;font-size:13px;color:var(--dim)}
  .kv b{color:var(--text);font-weight:600}
  .pill{display:inline-block;padding:2px 9px;border-radius:20px;font-size:11.5px}
  .pill.ok{background:rgba(0,184,148,.18);color:#4be0b8}
  .pill.no{background:rgba(255,123,114,.15);color:#ff9b93}
  .micbar{height:8px;background:#222836;border-radius:4px;overflow:hidden;margin:12px 0 6px}
  .micbar>i{display:block;height:100%;width:0;background:linear-gradient(90deg,#00d2ff,#00b894);transition:width .1s}
  .sayrow{display:flex;gap:8px;margin:16px 0 4px}
  .sayrow input{flex:1;background:#11151d;border:1px solid var(--line);color:var(--text);
       border-radius:10px;padding:9px 12px;font-size:13px;outline:none}
  .log{font-family:ui-monospace,Consolas,monospace;font-size:11.5px;color:var(--dim);
       height:150px;overflow:auto;line-height:1.8}
  #reclist{min-height:18px}
  a{color:#4be0b8}
</style>
</head>
<body>
<div class="wrap">
  <h1>ESP32 WiFi 音箱控制台</h1>
  <div class="sub" id="sub">连接中…</div>

  <div class="card">
    <div class="song" id="title">未播放</div>
    <div class="artist" id="artist">—</div>
    <div class="bar"><i id="bar"></i></div>
    <div class="times"><span id="pos">0:00</span><span id="dur">0:00</span></div>
    <div class="row">
      <button onclick="api('prev')">⏮</button>
      <button class="main" id="toggle" onclick="api('toggle')">▶</button>
      <button onclick="api('next')">⏭</button>
    </div>
    <div class="vol"><span>音量</span><input type="range" id="vol" min="0" max="100" value="2"
         oninput="onVol()"><span id="volv">2%</span></div>
    <div class="err" id="err"></div>
  </div>

  <div class="card">
    <h2>麦克风（INMP441）</h2>
    <button class="rec" id="rec" onclick="api('record')">● 开始录音</button>
    <label style="margin-left:10px;font-size:12.5px;color:var(--dim)">
      回复方式
      <select id="mode" onchange="setMode()"
              style="background:#11151d;color:var(--text);border:1px solid var(--line);
                     border-radius:8px;padding:3px 6px;font-size:12.5px">
        <option value="agent">交给 Codex</option>
        <option value="local">本地规则</option>
      </select>
    </label>
    <span id="rectip" style="margin-left:12px;color:var(--dim);font-size:12.5px">录音时喇叭会暂停（半双工）</span>
    <div class="sayrow">
      <input id="saytext" placeholder="打一句话，让音箱念出来（回车也行）"
             onkeydown="if(event.key==='Enter')doSay()">
      <button class="rec" onclick="doSay()">🔊 说</button>
    </div>
    <div class="micbar"><i id="micbar"></i></div>
    <div class="kv">
      <span>电平 / 峰值</span><b id="miclv">0.000 / 0</b>
      <span>已录时长</span><b id="micsec">0.0 s</b>
      <span>录音文件</span><b id="micfile">—</b>
    </div>
    <div id="reclist" class="foot"></div>
    <div class="kv" style="margin-top:10px;border-top:1px solid var(--line);padding-top:12px">
      <span>最新录音（inbox）</span><b id="inboxfile">—</b>
      <span>我听到的是</span><b id="transcript">—</b>
      <span>音箱刚说的话</span><b id="lastreply">—</b>
      <span>力传感器</span><b id="force">—</b>
    </div>
    <div class="foot">「交给 Codex」：录完 → 本地识别 → 识别结果写进 <code>wifi/inbox/pending.txt</code> →
      Codex 把回话写进 <code>wifi/reply.txt</code> → 音箱自动念出来。</div>
  </div>

  <div class="card">
    <h2>链路（WiFi → 板子）</h2>
    <div class="kv">
      <span>板子连接</span><b id="lk"></b>
      <span>板子模式 / 缓冲</span><b id="lk2">—</b>
      <span>欠载 / 失步</span><b id="lk3">—</b>
      <span>RSSI</span><b id="lk4">—</b>
      <span>电脑发 / 收</span><b id="lk5">—</b>
      <span>播放线程当前阶段</span><b id="stage">—</b>
    </div>
    <div class="log" id="log"></div>
  </div>

  <div class="card">
    <input type="search" id="q" placeholder="搜索歌名 / 歌手…" oninput="render()">
    <ul id="list"></ul>
    <div class="foot" id="foot"></div>
  </div>
</div>
<script>
let st = {playlist: [], index: -1, state: 'stopped', volume: 2};
let lastListSig = '';
let lastActiveIndex = -2;

function fmt(s){s=Math.max(0,Math.round(s||0));return Math.floor(s/60)+':'+String(s%60).padStart(2,'0');}

async function api(cmd, v, p){
  let q='';
  if(v!==undefined) q='?v='+v;
  if(p) q+=(q?'&':'?')+'p='+encodeURIComponent(p);
  try{ await fetch('/api/'+cmd+q, {method:'POST'}); }catch(e){}
  refresh();
}

function onVol(){
  const v=+document.getElementById('vol').value;
  document.getElementById('volv').textContent=v+'%';
  api('volume', v);
}

async function doSay(){
  const t=document.getElementById('saytext').value.trim();
  if(!t) return;
  try{ await fetch('/api/say?text='+encodeURIComponent(t), {method:'POST'}); }catch(e){}
  refresh();
}

function setMode(){
  const m = document.getElementById('mode').value;
  fetch('/api/mode?v='+encodeURIComponent(m), {method:'POST'}).catch(()=>{});
}

function render(){
  document.getElementById('title').textContent = st.title || '未播放';
  document.getElementById('artist').textContent = st.artist || '—';
  document.getElementById('toggle').textContent = st.state==='playing' ? '⏸' : '▶';
  document.getElementById('bar').style.width = (st.duration ? Math.min(100, 100*st.position/st.duration) : 0) + '%';
  document.getElementById('pos').textContent = fmt(st.position);
  document.getElementById('dur').textContent = fmt(st.duration);
  document.getElementById('err').textContent = st.error || '';
  document.getElementById('sub').textContent =
      '歌单 ' + (st.playlist ? st.playlist.length : 0) + ' 首' +
      (st.probing ? '（正在校验 ' + st.probing + ' 首…）' : '');
  const volEl = document.getElementById('vol');
  if (document.activeElement !== volEl) {
    volEl.value = st.volume;
    document.getElementById('volv').textContent = st.volume + '%';
  }
  document.getElementById('foot').textContent =
      '音频走 WiFi（TCP）：电脑解码 → 板子环形缓冲 → I2S 出声。歌单目录：D:\\\\CloudMusic 和本目录的 music。';

  const mic = st.mic || {};
  document.getElementById('micbar').style.width = Math.min(100, (mic.level||0)*300) + '%';
  document.getElementById('miclv').textContent = (mic.level||0).toFixed(3) + ' / ' + (mic.peak||0);
  document.getElementById('micsec').textContent = (mic.seconds||0).toFixed(1) + ' s';
  document.getElementById('micfile').textContent = mic.file || '—';
  const recBtn = document.getElementById('rec');
  recBtn.className = 'rec' + (st.recording ? ' on' : '');
  recBtn.textContent = st.recording ? '■ 停止录音' : '● 开始录音';
  document.getElementById('reclist').innerHTML = (st.recordings||[]).length
      ? '最近录音：' + st.recordings.map(f=>'<a href="/mic/'+encodeURIComponent(f)+'">'+f+'</a>').join(' · ')
      : '';
  const inbox = st.inbox || {};
  document.getElementById('inboxfile').innerHTML = inbox.file
      ? '<a href="/inbox/' + encodeURIComponent(inbox.file) + '">' + inbox.file + '</a>（' +
        (inbox.seconds || 0) + ' 秒）'
      : '—';
  document.getElementById('lastreply').textContent = st.reply || '—';
  const fsr = (st.link && st.link.force) || {};
  document.getElementById('force').textContent = (fsr.raw !== undefined)
      ? (fsr.raw + ' / ' + fsr.mv + ' mV' + (fsr.raw < 3000 ? '（按压中）' : '（松开）'))
      : '—';
  document.getElementById('transcript').textContent = st.transcript || '—';
  const modeEl = document.getElementById('mode');
  if (modeEl && document.activeElement !== modeEl) modeEl.value = st.reply_mode || 'agent';

  const lk = st.link || {};
  const s = lk.stats || {};
  document.getElementById('lk').innerHTML = lk.connected
      ? '<span class="pill ok">已连接 ' + (lk.addr||'') + '</span>'
      : '<span class="pill no">未连接（等板子连 0.0.0.0:' + (lk.port||'') + '）</span>';
  document.getElementById('lk2').textContent = (s.mode||'—') + (s.fill!==undefined ? ' / 缓冲 ' + s.fill + '%' : '');
  document.getElementById('lk3').textContent = (s.underruns!==undefined ? s.underruns : '—') + ' / ' + (s.resyncs!==undefined ? s.resyncs : '—');
  document.getElementById('lk4').textContent = (s.rssi!==undefined ? s.rssi + ' dBm' : '—');
  document.getElementById('lk5').textContent = (lk.tx_kb||0) + ' KB / ' + (lk.rx_kb||0) + ' KB（麦克风 ' + (lk.mic_kb||0) + ' KB）';
  document.getElementById('stage').textContent = st.stage || '—';
  document.getElementById('log').innerHTML = (lk.events||[]).map(e=>e[0]+'  '+e[1]).join('<br>');

  const q=(document.getElementById('q').value||'').toLowerCase();
  const list=document.getElementById('list');
  const items=st.playlist.filter(x=>!q || x.t.toLowerCase().includes(q) || (x.a||'').toLowerCase().includes(q));
  // 列表只在内容真的变了的时候重建（每次刷新都重建会闪烁、还会打断滚动）
  const sig = q + '|' + items.map(x=>x.i).join(',');
  if (sig !== lastListSig) {
    lastListSig = sig;
    list.innerHTML=items.map(x=>'<li data-i="'+x.i+'" data-p="'+(x.p||'').replace(/"/g,'&quot;')+'"><span class="t">'+x.t+'</span><span class="a">'+(x.a||'')+'</span></li>').join('');
    list.querySelectorAll('li').forEach(li=>li.onclick=()=>api('play', li.dataset.i, li.dataset.p));
  }
  // 只更新高亮，不动滚动
  list.querySelectorAll('li').forEach(li=>li.classList.toggle('active', +li.dataset.i === st.index));
  // 只有"切换了歌"才把高亮行滚进列表内部（绝不再滚整页）
  if (st.index !== lastActiveIndex) {
    lastActiveIndex = st.index;
    const act = list.querySelector('li.active');
    if (act) {
      const top = act.offsetTop, bottom = top + act.offsetHeight;
      if (top < list.scrollTop) list.scrollTop = top - 4;
      else if (bottom > list.scrollTop + list.clientHeight) list.scrollTop = bottom - list.clientHeight + 4;
    }
  }
}

async function refresh(){
  try{ st = await (await fetch('/api/state')).json(); render(); }catch(e){}
}

refresh();
setInterval(refresh, 500);
</script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json"):
        data = body.encode() if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path.startswith("/api/state"):
            self._send(200, json.dumps(PLAYER.state_json(), ensure_ascii=False))
        elif self.path in ("/", "/index.html", ""):
            self._send(200, PAGE, "text/html; charset=utf-8")
        elif self.path in ("/wiring", "/wiring.html"):
            try:
                with open(os.path.join(ROOT, "接线图.html"), "rb") as f:
                    self._send(200, f.read(), "text/html; charset=utf-8")
            except OSError:
                self._send(404, "{}")
        elif self.path.startswith("/mic/"):
            name = os.path.basename(urllib.parse.unquote(self.path[5:]))
            path = os.path.join(REC_DIR, name)
            if name.endswith(".wav") and os.path.isfile(path):
                with open(path, "rb") as f:
                    self._send(200, f.read(), "audio/wav")
            else:
                self._send(404, "{}")
        elif self.path.startswith("/inbox/"):
            name = os.path.basename(urllib.parse.unquote(self.path[7:]))
            path = os.path.join(INBOX, name)
            if name.endswith(".wav") and os.path.isfile(path):
                with open(path, "rb") as f:
                    self._send(200, f.read(), "audio/wav")
            else:
                self._send(404, "{}")
        else:
            self._send(404, "{}")

    def do_POST(self):
        path = self.path.split("?")[0]
        q = {}
        if "?" in self.path:
            for k, vals in urllib.parse.parse_qs(self.path.split("?", 1)[1]).items():
                q[k] = vals[0]
        if path == "/api/play":
            if q.get("p"):
                PLAYER.play_path(q["p"])
            else:
                PLAYER.play_index(int(q.get("v", 0)))
        elif path == "/api/toggle":
            PLAYER.toggle()
        elif path == "/api/next":
            PLAYER.skip(1)
        elif path == "/api/prev":
            PLAYER.skip(-1)
        elif path == "/api/volume":
            PLAYER.set_volume(int(q.get("v", 10)))
        elif path == "/api/record":
            PLAYER.toggle_record()
        elif path == "/api/say":
            text = (q.get("text") or "").strip()
            if text:
                threading.Thread(target=PLAYER.speak, args=(text,), daemon=True).start()
        elif path == "/api/auto":
            with PLAYER.lock:
                PLAYER.auto_reply = q.get("v", "1") == "1"
        elif path == "/api/mode":
            v = q.get("v", "agent")
            if v in ("agent", "local"):
                with PLAYER.lock:
                    PLAYER.reply_mode = v
                PLAYER.link.log("回复方式 -> %s" % ("交给 Codex" if v == "agent" else "本地规则"))
        elif path == "/api/understand":
            # 对 inbox 里已有的任意 wav 重新走一遍：识别 -> 回复 -> 说出来
            name = os.path.basename(q.get("f", ""))
            p = os.path.join(INBOX, name)
            if name.endswith(".wav") and os.path.isfile(p):
                threading.Thread(target=PLAYER._understand, args=(p,), daemon=True).start()
        elif path == "/api/refresh":
            PLAYER.scan()
        self._send(200, json.dumps(PLAYER.state_json(), ensure_ascii=False))


def main():
    global PLAYER
    PLAYER = Player()
    print("tracks:", len(PLAYER.tracks), "| unsupported:", PLAYER.unsupported)
    print("playable:", sum(1 for v in PLAYER.playable.values() if v))
    url = "http://127.0.0.1:%d/" % HTTP_PORT
    print("open:", url)
    try:
        webbrowser.open(url)
    except Exception:
        pass
    ThreadingHTTPServer(("127.0.0.1", HTTP_PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
