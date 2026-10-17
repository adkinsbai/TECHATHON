"""main.py - 板子开机自启（WiFi 版）

看到 wifi_on.txt 就进 WiFi 音频模式；没有它就让出 CPU 给 REPL，
这样出问题时还能用 Thonny / mpremote 连上去看。
"""

import os

try:
    if "wifi_on.txt" in os.listdir():
        import board_main
        board_main.run()
except KeyboardInterrupt:
    print("stopped by user")
except Exception as exc:
    print("WIFI-MAIN-ERR", repr(exc))
