"""Run a snippet on the board through the raw REPL and print its output.

    python board_exec.py COM7 "import os; print(sorted(os.listdir()))"
"""

import sys
import time

import serial

PORT = sys.argv[1] if len(sys.argv) > 1 else "COM7"
CODE = sys.argv[2] if len(sys.argv) > 2 else "print('hello')"

s = serial.Serial()
s.port = PORT
s.baudrate = 115200
s.timeout = 0.3
s.dtr = False
s.rts = False
s.open()
time.sleep(0.3)
s.read(65536)

for _ in range(2):
    s.write(b"\x03")
    time.sleep(0.25)
    s.read(8192)
s.write(b"\x01")
time.sleep(0.3)
s.read(4096)

s.write(CODE.encode() + b"\x04")
buf = b""
t0 = time.time()
while time.time() - t0 < 12:
    d = s.read(4096)
    if d:
        buf += d
    if b"\x04>" in buf:
        break
s.close()

text = buf.decode("utf-8", "replace")
print(text.replace("\x04>", "").replace("\x04", "").strip())
