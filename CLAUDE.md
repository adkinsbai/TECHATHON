# Claude 接手入口

先读 `README.md` → `MEMORY.md` → `AGENTS.md` → `.claude/skills/xiaonuan-body-development/SKILL.md`。详细证据见 `docs/XIAONUAN-BODY-VERIFICATION.md`，架构与原始计划在 `docs/superpowers/`。

## 当前项目是什么

同一个小暖拥有电脑上的聊天/3D界面和 ESP32-S3 实体。电脑端仍保存原人设、聊天与记忆；实体提供麦克风、扬声器、FSR。不是两个独立角色。实体语音固定走电脑本地 SenseVoice/Kokoro，语言模型沿用已有配置。默认音量 10%。

## 先确认运行的是哪一份

- `companion/`：本 PR 提供的完整应用源码快照，已去除个人数据、密钥、模型和交互日志。`SOURCE-MANIFEST.json` 记录导出范围和哈希。
- 本机可能仍在运行用户原来的 Companion。先读忽略的 `.local-body.json` 确认路径，再核对监听端口和进程；不要直接把新克隆的空数据应用当成原来的小暖。
- 正式默认页面 `http://127.0.0.1:8765/`，3D 页面 `/world`；实体 TCP 5000。`18765` 曾用于假模型/假板测试，不能据此声称实物功能通过。
- 当前电脑端启动入口 `start-body.cmd` / `start-body.ps1`。已有配置优先复用；不要重复开一个桥接进程。

## 改哪里

| 工作 | 源码入口 |
| --- | --- |
| 传感器、录音状态、网络和播放 | `body_bridge/` |
| 本地语音专用接口、事件与同库对话 | `companion_extension/body_runtime.py` |
| 两个页面的实体面板和同步钩子 | `companion_extension/` |
| 安装定位、源码备份、服务启动 | `install_companion.py`, `start-body.ps1` |
| 板子 I2S、压力采样和 TCP | `firmware/board/` |
| 小暖完整聊天、人格、记忆和3D世界 | `companion/app/`, `companion/static/` |

安装器只部署约定的八个扩展相关源码文件；它不会把整个 `companion/` 自动覆盖到原应用。若修改完整应用核心，先在隔离数据上验证，再对已确认的原路径准备有备份的具体源码补丁。不要整体覆盖用户数据。

## 接手后的第一轮

1. 看 Git 状态、当前分支和本地配置，确认已有进程与端口。
2. 读取项目 memory 的证据边界和待验收项；不要重复下载或提交大模型。
3. 跑 `python -m unittest discover -s tests -q`。Windows 启动器测试需要 PowerShell；浏览器音频接管测试需要 Node.js。
4. 需要验证全链路时使用 `tests/body_e2e.py` 的备用端口和假板。需要验证本地语音时运行 `tools/body_voice_check.py`，它不写聊天、不播放扬声器。
5. 按用户下一条任务改动，记录真实硬件结果与软件结果。继续使用 10% 默认音量；真实听感和麦克风质量不能用 HTTP 200 代替。

Python 3.12 是当前基线。多步 Python 操作写入脚本文件执行，便于复核。不要将凭据写进命令行、源码、日志或 PR 描述。
