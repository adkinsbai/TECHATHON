# 小暖实体接入

用户已确认：保留电脑上的同一个小暖，ESP32-S3 作为麦克风、喇叭和压力输入，默认扬声器音量 10%。先完成可运行代码，实板接入后另做硬件验收。

## Architecture

The existing board TCP frame protocol remains on port 5000. A Python 3.12 `body_bridge` service owns that port and communicates with the existing loopback-only Companion service on port 8765. Do not run the old wifi_demo server at the same time. No second persona or memory database is created.

Pressure is calibrated at rest. Debounced press starts capture, release after at least 0.35 seconds sends a WAV to `/api/body/asr`, then calls `/api/chat` with `source: body`. A shorter touch invokes `/api/body/event`. Raw 10Hz samples never invoke the LLM. Capture has a 15-second cap; lost connections discard incomplete capture. Playback is half duplex, interruptible by a new press, bounded on failure, 24kHz stereo signed 16-bit little endian PCM, amplitude scaled by exactly `volume / 100`, initially 10. The final audio packet is zero-padded, and playback is allowed to drain before IDLE.

Companion extension endpoints:
- POST `/api/body/asr`: multipart WAV to the existing computer-local SenseVoice helper. Missing or failed local models return 503; no online fallback.
- POST `/api/body/tts`: `{text}` to the existing computer-local Kokoro helper; returns WAV. Reuses a local persona voice, otherwise `local:3`, without modifying the saved persona. Missing or failed local models return 503; no online fallback.
- GET `/api/body/stream`: SSE with `hello`, `status`, `turn_start`, `user`, `delta`, `done`, `error`, `turn_end`; data contains `turn_id`, `source` for turn events. Optional Last-Event-ID replay is bounded. Heartbeats keep idle connections alive.
- GET `/api/body/status`: effective device state; stale heartbeat (>8 seconds) means disconnected.
- POST `/api/body/status`: `{connected, phase, raw, mv, pressed, stats, error, tcp_port}`; returns `{settings: {volume: 10}, commands: []}`.
- PATCH `/api/body/settings`: `{volume: integer 0..100}`; saved under a new state key.
- POST `/api/body/command`: `{command: record_start|record_stop|calibrate}`; bounded command queue delivered with the next heartbeat.
- POST `/api/body/event`: `{event_id, kind: touch, duration, strength}`; deduplicated, recorded as a physical event, and produces a streamed short Companion response.
- Existing `/api/chat` gains optional `source: web|body` (default web). Replies are serialized. All turn events are broadcast; the initiating page keeps its existing response stream, body turns update both web views via the new event stream.

The bridge listens to completed reply events and uses the dedicated local-only `/api/body/tts` route to play through the board. All bridge-to-Companion HTTP traffic bypasses system proxies. A connected, fresh body takes automatic playback ownership; browser voice previews still work. New device events update screen text and emotion without duplicate messages. Body state and controls are added as a small warm themed panel on both views. Physical events can be included as grounded context; no inference of hugs, location or user emotions from pressure.

## Delivery and acceptance

Code lives in a separate local Git checkout. The extension installer backs up only changed source files, checks patch anchors, is repeatable, and never copies or replaces `.env`, persona, chat data or models. Start scripts detect the configured Companion path, start only missing local services, log startup failures, and never expose Companion on the LAN. USB configuration remains separate from runtime TCP and must not flash an unidentified board.

Software acceptance: pressure hysteresis/debounce/calibration/capture cap, 10% PCM scaling, fragmented SSE, reconnect and bounded send failure, dedupe and stale state, same-database chat flow, UI synchronization and no duplicate audio. Use isolated fixture data for automated tests. Finish with code review and browser screenshots. Physical microphone, FSR calibration, speaker loudness and Wi-Fi stability require real-board acceptance.
