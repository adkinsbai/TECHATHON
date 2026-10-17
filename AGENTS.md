# Working on Xiaonuan

Read `README.md`, `CLAUDE.md`, `MEMORY.md`, and `docs/XIAONUAN-BODY-VERIFICATION.md` before making changes. The project skill is `.claude/skills/xiaonuan-body-development/SKILL.md`.

- Work in this repository. `companion/` is the portable source snapshot; the current user's running Companion can live elsewhere. `.local-body.json` (ignored) identifies the configured live root. Never assume a clone's empty data directory is the user's original companion.
- Preserve original chat, memories, persona, `.env`, model files and unrelated board files. Never publish or copy those into a PR. Use blank `.env.example` templates. Wi-Fi configuration and device backups remain ignored local files.
- Body ASR/TTS must use `/api/body/asr` and `/api/body/tts`. ASR is computer-local SenseVoice; a missing model produces a clear error. TTS is Microsoft Xiaoyi via edge-tts (`voice.tts_wav`, same voice as the web page, persona default `edge:zh-CN-XiaoyiNeural`); it needs internet, retries, then returns 503 and stays silent, never switching to another voice. Kokoro has been removed. Conversation still uses the original Companion's configured language model.
- Physical speaker default is 10% PCM amplitude; 0 means silence. Do not add a minimum-volume boost. Keep the board's 24kHz, signed 16-bit stereo playback protocol and half-duplex behavior.
- Pressure is local contact only. Do not infer emotion, hugs or room position. Require rest calibration, debounce, hysteresis, a 15-second capture limit, bounded queues, failure timeouts and no replay across connections.
- Identify hardware through an actual chip/runtime probe before writes. Use `tools/body_device.py`: preserve backups, verify approved source provenance and SHA256 readback, then normal reset. A USB product name alone is insufficient.
- Install extension changes with `install_companion.py`; it validates anchors and backs up source only. Use Windows extended paths for deep directories. Never replace whole live directories or databases.
- Only stop a service after checking its module, arguments and configured root. A probe timeout is ambiguous and must not trigger a restart. Definitive missing routes or changed backend source can justify restarting an identified Companion.
- Test on alternate loopback/TCP ports with isolated data. Do not create synthetic chat history in the user's database. Do not run legacy `wifi_demo.py` alongside `body_bridge` on TCP 5000.
- Before a PR, run the appropriate tests, review the staged file list for private files, and state software evidence separately from real microphone, speaker and long-run hardware acceptance.
