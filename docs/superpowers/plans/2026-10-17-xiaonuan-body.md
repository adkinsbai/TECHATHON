# Xiaonuan Body Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Connect the existing ESP32-S3 audio/pressure node to the same running Xiaonuan persona and memory, with 10% default speaker volume.

**Architecture:** A separate `body_bridge` process owns TCP 5000 and calls Companion at loopback port 8765. A small installed Companion extension broadcasts body state and dialogue to the existing screens. Existing data and credentials remain in place.

**Tech Stack:** Python 3.12, existing wifi_link, httpx, miniaudio, FastAPI, browser SSE, unittest.

## Global Constraints

- Default physical speaker volume is 10%; no minimum-volume boost.
- Body ASR/TTS uses existing computer-local SenseVoice/Kokoro only; no online speech fallback.
- Use the existing Companion persona and database. Never replace `.env`, `data/`, or models.
- Preserve board frame protocol and port 5000; Companion remains loopback-only.
- Pressure means measured contact; do not infer emotion, hug or room position.
- Half-duplex press/release interaction; 15-second capture cap, bounded network failures, no replay of old speech after reconnect.
- Both web views receive body-origin turns; connected hardware owns automatic audio output.
- Do not flash unidentified USB hardware or edit synced project sources.

### Task 1: Hardware bridge

Files: `body_bridge/{__init__,__main__,pressure,audio,client,runtime}.py`, `tests/test_body_bridge.py`, `body-requirements.txt`.

Interfaces: consume the HTTP/SSE contracts in the design; produce TCP frames via existing `wifi.wifi_link.Link`, `MODE_REC`, `MODE_PLAY`, `MODE_IDLE`. Heartbeat returns settings and commands. Global `done` reply events enqueue TTS; no separate model backend.

- [x] Write tests for calibrated pressure, bounce and hysteresis, short touch versus recorded utterance, 10% PCM scaling, fragmented SSE, stale/disconnected playback and bounded failures.
- [x] Run tests and confirm missing behavior fails before implementation.
- [x] Implement focused modules and `python -m body_bridge --companion-url http://127.0.0.1:8765 --port 5000 --volume 10`.
- [x] Run unittest and self-review. Commit only owned files.

### Task 2: Companion extension and two-view synchronization

Files: `companion_extension/body_runtime.py`, `companion_extension/body-client.{js,css}`, `tests/test_companion_extension.py`.

Interfaces: implement the exact routes/SSE events in the design, `BodyHub`, `attach_body_routes(app, hub, reply_stream, voice=voice)`, `hub.relay(reply_stream_impl, user_text, note, heard, source)` async iterator. `BodyHub` accepts the existing store and supplies a serialized turn lock and grounded context helper.

- [x] Write tests for dedupe, stale state, volume validation/default, command consumption, event ordering and serial turns.
- [x] Confirm failures, implement hub/router and browser client, then pass tests.
- [x] Add thin hooks to existing chat/world scripts through the installer: external body messages/emotion/speaking events, audio ownership, suppress accidental game keyboard input while panel controls are focused.

### Task 3: Safe installation, startup and firmware edge cases

Files: `install_companion.py`, `start-body.cmd`, `start-body.ps1`, `firmware/board/board_main.py`, `wifi/wifi_demo.py`, `docs/XIAONUAN-BODY.md`, tests and integration harness.

- [x] Test repeatable install and rollback on missing anchors using a copied fixture, never real data.
- [x] Implement source-only backups and install; preserve live files changed by others by validating current anchors immediately before writes.
- [x] Clear the firmware ring on mode switches; pad/drain host playback. Change legacy player default volume and remove TTS minimum-volume boost.
- [x] Exercise the complete press/ASR/chat/TTS flow against an isolated Companion fixture and synthetic board on alternate ports, including disconnect during speech.
- [x] Check desktop/mobile views and screenshots, request independent code review, fix material findings.
- [x] Install into the existing Companion, restart only the identified local service, start bridge, verify fresh routes/state and preserve history count. Record real-board acceptance separately.
