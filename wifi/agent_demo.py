"""agent_demo.py - 「能听能说」的闭环：麦克风 → 电脑 → 回复 → 喇叭

链路：INMP441 → 板子 I2S RX → WiFi(TCP) → 这个脚本 →（AI / 文件 / 命令行）
      → 文字 → 语音合成 → WiFi(TCP) → 板子 I2S TX → 喇叭

回复从哪来（三选一）：
    --say "文本"          直接念这句（最快，用来验"能说"）
    --watch say.txt       盯着文件：你把想让它说的话写进 say.txt，它就来念
    --api                 用 OpenAI 自动跑「语音转文字 → 让模型回一句 → 语音合成」
                          （需要先设环境变量 OPENAI_API_KEY）

录音：不给上面任何参数时，就是"录一句"模式 —— 板子进录音模式，
      检测到你说完（静音约 0.9 秒）自动收尾，存成 wifi/recordings/xxx.wav。

用法示例：
    python agent_demo.py --say "你好，我在听"
    python agent_demo.py --watch say.txt
    python agent_demo.py --record            # 只录一句，存 WAV
    python agent_demo.py --api               # 录一句 → 自动回答并念出来

注意：喇叭和麦克风共用一条 I2S，是半双工 —— 说话时不录、录音时不放。
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import wave

import audioop

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from wifi_link import (AUD_BYTES, MODE_IDLE, MODE_PLAY, MODE_REC, RATE, Link,
                       MicSink)

REC_DIR = os.path.join(HERE, "recordings")
TCP_PORT = 5000
LEAD_SECONDS = 0.5


# ------------------------------------------------------------------ 录音
class Utterance:
    """一点点 VAD：有声音就攒，静音够久就算说完了。"""

    def __init__(self, min_sec=0.5, max_sec=8.0, silence_sec=0.9, thresh=0.012):
        self.min_sec = min_sec
        self.max_sec = max_sec
        self.silence_sec = silence_sec
        self.thresh = thresh
        self.buf = bytearray()
        self.voiced = 0.0
        self.silence = 0.0
        self.started = False
        self.done = False
        self.lock = threading.Lock()
        self.level = 0.0

    def feed(self, pcm):
        if not pcm:
            return
        rms = audioop.rms(pcm, 2) / 32768.0
        secs = len(pcm) / 2.0 / RATE
        with self.lock:
            self.level = rms
            if not self.started:
                if rms >= self.thresh:
                    self.started = True
                    self.buf = bytearray(pcm)
                    self.voiced = secs
                return
            self.buf += pcm
            if rms >= self.thresh:
                self.voiced += secs
                self.silence = 0.0
            else:
                self.silence += secs
            if self.voiced >= self.min_sec and self.silence >= self.silence_sec:
                self.done = True
            elif self.voiced + self.silence >= self.max_sec:
                self.done = True

    def save(self):
        with self.lock:
            data = bytes(self.buf)
            spoken = self.voiced
        if spoken < self.min_sec:
            return None
        name = time.strftime("utter_%Y%m%d-%H%M%S.wav")
        path = os.path.join(REC_DIR, name)
        os.makedirs(REC_DIR, exist_ok=True)
        with wave.open(path, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(RATE)
            w.writeframes(data)
        return path


def record_once(link, seconds=15.0, quiet=False):
    """让板子进录音模式，录一句。返回 WAV 路径（没听到人说话就返回 None）。"""
    utt = Utterance()
    sink = MicSink(REC_DIR)
    sink.start()

    def on_mic(payload):
        sink.feed(payload)          # 顺手也存一份连续录音
        utt.feed(payload)           # 板子已经转成 16bit 单声道了

    link.on_mic = on_mic
    link.set_mode(MODE_REC)
    t0 = time.time()
    last_show = 0.0
    try:
        while time.time() - t0 < seconds:
            if utt.done:
                break
            if not quiet and time.time() - last_show > 0.5:
                last_show = time.time()
                sys.stdout.write("\r电平 %s  已说话 %.1fs   " %
                                 ("#" * int(utt.level * 60), utt.voiced))
                sys.stdout.flush()
            time.sleep(0.02)
    finally:
        link.set_mode(MODE_IDLE)
        sink.stop()
        if not quiet:
            print()
    return utt.save()


_pcm_cache = {"rest": b""}


def pcm_16(link, payload):
    """把板子回传的 32bit 立体声槽数据转成 16bit 单声道（左声道）。"""
    usable = len(payload) - (len(payload) % 8)
    if usable <= 0:
        return b""
    import struct
    vals = struct.unpack("<%di" % (usable // 4), payload[:usable])
    return struct.pack("<%dh" % (usable // 8), *[v >> 16 for v in vals[0::2]])


# ------------------------------------------------------------------ 说话
def tts_windows(text, out_wav, voice=None):
    """用 Windows 自带语音合成做个 WAV（离线，不需要 key）。"""
    txt = out_wav + ".txt"
    with open(txt, "w", encoding="utf-8") as f:
        f.write(text)
    lines = ["Add-Type -AssemblyName System.Speech",
             "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer"]
    if voice:
        lines.append("$s.SelectVoice('%s')" % voice)
    lines += ["$s.Rate = 0",
              "$s.SetOutputToWaveFile('%s')" % out_wav,
              "$s.Speak([IO.File]::ReadAllText('%s', [Text.Encoding]::UTF8))" % txt,
              "$s.Dispose()"]
    ps = out_wav + ".ps1"
    with open(ps, "w", encoding="utf-8-sig") as f:
        f.write("\n".join(lines))
    subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", ps],
                   check=True, capture_output=True)
    try:
        os.remove(txt)
        os.remove(ps)
    except OSError:
        pass
    return out_wav


def speak_wav(link, wav_path, volume=0.6):
    """把任意 WAV 转成 24kHz 立体声 16bit，推给板子播出来。"""
    with wave.open(wav_path, "rb") as w:
        ch = w.getnchannels()
        width = w.getsampwidth()
        rate = w.getframerate()
        data = w.readframes(w.getnframes())
    if width != 2:
        data = audioop.lin2lin(data, width, 2)
        width = 2
    if ch == 2:
        data = audioop.tomono(data, 2, 0.5, 0.5)
    if rate != RATE:
        data, _ = audioop.ratecv(data, 2, 1, rate, RATE, None)
    if volume < 0.999:
        data = audioop.mul(data, 2, volume)
    stereo = audioop.tostereo(data, 2, 1.0, 1.0)

    link.set_mode(MODE_PLAY)
    time.sleep(0.15)
    start = time.monotonic()
    sent = 0
    for off in range(0, len(stereo), AUD_BYTES):
        piece = stereo[off:off + AUD_BYTES]
        ok = False
        while not ok:
            ok = link.send_audio(piece)
            if not ok:
                time.sleep(0.2)
        sent += len(piece)
        target = sent / 4.0 / RATE - LEAD_SECONDS
        elapsed = time.monotonic() - start
        if target > elapsed:
            time.sleep(target - elapsed)
    time.sleep(0.4)
    link.set_mode(MODE_IDLE)


def say(link, text, voice=None, volume=0.6):
    tmp = os.path.join(tempfile.gettempdir(), "esp32_say.wav")
    tts_windows(text, tmp, voice)
    speak_wav(link, tmp, volume)


# ------------------------------------------------------------------ AI（可选）
def api_brain(wav_path, api_key, model="gpt-4o-mini", tts_model="gpt-4o-mini-tts",
              voice="alloy", system=None):
    """转写 → 让模型回一句 → 合成语音，返回 (文字, wav路径)。需要联网 + key。"""
    import urllib.error

    def post(url, data, ctype):
        req = urllib.request.Request(url, data=data, method="POST")
        req.add_header("Authorization", "Bearer " + api_key)
        req.add_header("Content-Type", ctype)
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.read()

    # 1) 语音转文字
    boundary = "----esp32demo"
    with open(wav_path, "rb") as f:
        audio = f.read()
    body = []
    body.append(("--%s\r\n" % boundary).encode())
    body.append(b'Content-Disposition: form-data; name="file"; filename="a.wav"\r\n')
    body.append(b"Content-Type: audio/wav\r\n\r\n")
    body.append(audio)
    body.append(("\r\n--%s\r\n" % boundary).encode())
    body.append(b'Content-Disposition: form-data; name="model"\r\n\r\n')
    body.append(b"whisper-1\r\n")
    body.append(("--%s--\r\n" % boundary).encode())
    raw = post("https://api.openai.com/v1/audio/transcriptions", b"".join(body),
               "multipart/form-data; boundary=%s" % boundary)
    text = json.loads(raw.decode()).get("text", "").strip()
    if not text:
        return "", None

    # 2) 让模型回一句
    payload = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": system or
             "你是一个放在桌面上的语音音箱，回答要短、口语化，一两句话，不要用列表和 markdown。"},
            {"role": "user", "content": text},
        ],
    }).encode()
    raw = post("https://api.openai.com/v1/chat/completions", payload, "application/json")
    reply = json.loads(raw.decode())["choices"][0]["message"]["content"].strip()

    # 3) 合成语音
    payload = json.dumps({"model": tts_model, "voice": voice, "input": reply,
                          "response_format": "wav"}).encode()
    audio = post("https://api.openai.com/v1/audio/speech", payload, "application/json")
    out = os.path.join(tempfile.gettempdir(), "esp32_reply.wav")
    with open(out, "wb") as f:
        f.write(audio)
    return reply, out


# ------------------------------------------------------------------ 主流程
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--say", default=None, help="直接念这段文字")
    ap.add_argument("--watch", default=None, help="盯着这个文件，内容变了就念")
    ap.add_argument("--record", action="store_true", help="只录一句，存 WAV")
    ap.add_argument("--api", action="store_true", help="录一句 → OpenAI 回答 → 念出来")
    ap.add_argument("--voice", default=None, help="Windows 语音的名字（可选）")
    ap.add_argument("--volume", type=float, default=0.6, help="说话音量 0~1")
    ap.add_argument("--seconds", type=float, default=15.0, help="一次最多录多久")
    args = ap.parse_args()

    link = Link(TCP_PORT, verbose=True)
    print("等板子连上 0.0.0.0:%d ……" % TCP_PORT)
    t0 = time.time()
    while not link.connected:
        if time.time() - t0 > 60:
            print("60 秒了还没连上：确认板子上电、wifi.json 里的 host 是这台电脑的 IP")
            return 1
        time.sleep(0.3)
    print("板子已连上：%s" % link.client_addr)

    if args.say:
        print("说话：%s" % args.say)
        say(link, args.say, args.voice, args.volume)
        return 0

    if args.watch:
        path = args.watch
        print("盯着 %s：把想让它说的话写进去就会念出来（换行结束）" % path)
        last = ""
        while True:
            if os.path.exists(path):
                with open(path, encoding="utf-8") as f:
                    text = f.read().strip()
                if text and text != last:
                    last = text
                    print("说话：%s" % text)
                    say(link, text, args.voice, args.volume)
            time.sleep(0.5)

    if args.api:
        key = os.environ.get("OPENAI_API_KEY")
        if not key:
            print("没设 OPENAI_API_KEY，改用 --watch 模式（说 say.txt 里的内容）")
            return 1
        while True:
            print("请说话……")
            wav = record_once(link, args.seconds)
            if not wav:
                print("没听到人说话")
                continue
            print("已录：%s，发给模型……" % os.path.basename(wav))
            reply, out = api_brain(wav, key)
            if not reply:
                print("没听清")
                continue
            print("模型回答：%s" % reply)
            speak_wav(link, out, args.volume)

    print("请说话（说完会自动收尾，最多 %.0f 秒）……" % args.seconds)
    wav = record_once(link, args.seconds)
    if wav:
        print("已存：%s" % wav)
        print("把它拖进对话里给我听，或者用 --watch say.txt 让我回话。")
    else:
        print("没听到人说话（可能是麦克风没接好，或者 L/R 没接地）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
