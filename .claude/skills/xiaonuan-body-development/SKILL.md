---
name: xiaonuan-body-development
description: Use when developing Xiaonuan Companion or its ESP32-S3 body, changing local speech or sensor interaction, diagnosing installation or reconnects, or preparing a verified handoff.
---

# Developing Xiaonuan's physical body

Read repository `CLAUDE.md`, `AGENTS.md`, `MEMORY.md`, and `docs/XIAONUAN-BODY-VERIFICATION.md`. Commands and architecture live in `README.md` and `docs/XIAONUAN-BODY.md`.

1. Identify the checkout and configured live Companion root. A portable clone has empty user state. Preserve the original `.env`, persona, chat, memories and models; never publish them.
2. Change the owning module and test with isolated data and alternate ports. Body speech must call `/api/body/asr` (local SenseVoice; a missing model fails clearly) and `/api/body/tts` (Microsoft Xiaoyi via edge-tts, same voice as the web page; failures stay silent, never another voice). Keep 10% default PCM volume and half-duplex capture.
3. Install through the anchor-validating installer, with source backups and Windows extended paths. For health timeouts, wait or report failure without restarting an existing service. Restart only an identified process with affirmative evidence.
4. Before device writes, probe actual chip/runtime identity, back up, verify approved source provenance, deploy and SHA256-read back. Use normal reset after raw REPL; verify startup and fresh TCP/sensor data.
5. Run appropriate regressions and the isolated TCP flow. Report real microphone/speaker acceptance separately from HTTP success or simulation. Review every staged path and commit for private data before pushing; update project memory with evidence and remaining work.

Never infer emotion or room position from pressure, replay stale speech after reconnect, or replace an entire live application/data directory.
