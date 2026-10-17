# 小暖：AI 数字生命体伴侣与 ESP32-S3 实体

同一个小暖可以在电脑聊天页、3D 世界和硬件实体之间互动。电脑保存人格、聊天与记忆并生成回复；ESP32-S3 提供压力传感器、麦克风和扬声器。USB 用于配置和供电，日常交互通过局域网 Wi-Fi TCP 连接。

本仓库包含完整的电脑端应用源码、实体中间层、网页接入、安装启动工具和 ESP32-S3 固件。个人聊天、实际人设、密钥、Wi-Fi 密码和语音模型不随源码分发。

## 给 Claude 的接手入口

按顺序阅读：

1. [CLAUDE.md](CLAUDE.md)：运行哪份应用、修改入口、接手步骤。
2. [MEMORY.md](MEMORY.md)：工程决策、已踩过的坑、实测边界与剩余工作。
3. [AGENTS.md](AGENTS.md)：代码代理必须遵守的项目约束。
4. [SKILLS.md](SKILLS.md) 和 [项目 skill](.claude/skills/xiaonuan-body-development/SKILL.md)：开发、验证与交接流程。
5. [验证记录](docs/XIAONUAN-BODY-VERIFICATION.md) 与 [安装使用说明](docs/XIAONUAN-BODY.md)。

这里的 memory 是工程交接记录，不是用户私人的聊天记忆；skill 也是本项目的工作指南，不包含电脑上的个人 skill 库。

## 交互与架构

```text
聊天页 / 3D 世界 ────── 同一个 Companion：人格、聊天库、记忆、回复锁
                                 │ 本机 HTTP / SSE
                           body_bridge 中间层
                                 │ Wi-Fi TCP 5000
                           ESP32-S3 实体
                         FSR / INMP441 / ES8311
```

- 短按压力传感器触发一次接触事件；按住说话，松手后识别并回复。压力只表示局部接触，不能据此判断情绪或空间位置。
- 实体识别用电脑本地 **SenseVoice**，合成用微软 **晓伊（活泼）**（edge-tts，免费免 key、需联网），与网页同一个音色。专用接口为 `/api/body/asr`、`/api/body/tts`；识别模型缺失明确报错，合成失败重试后这句不出声，不换别的声音。对话模型仍使用 Companion 自己的语言模型配置。
- 扬声器默认 **10% PCM 振幅**，0% 静音；24kHz、16-bit、双声道播放。当前硬件半双工，播放时不录音，再次按压可打断。
- 实体在线时接管自动语音，网页保留同一份文字和表情。录音上限 15 秒；断线丢弃未完成录音和旧语音。

## 运行已有的小暖

当前电脑已有原应用时，继续使用原来的 Companion 根目录，保留它的 `.env`、`data/`、人设和模型。不要用新克隆的空数据目录替换原应用。

环境：Windows、Python **3.12**。安装依赖、接入原应用：

```powershell
python -m pip install -r body-requirements.txt -r companion/requirements.txt
python install_companion.py --target '原来的 Companion 文件夹' --remember
.\start-body.ps1
```

以后可双击 `start-body.cmd`。安装器只部署八个相关源码文件，先检查定位点再备份写入；不读写聊天、模型或密钥。原目录和 Python 路径保存在忽略的 `.local-body.json`。

正式页面：[聊天](http://127.0.0.1:8765/) / [3D 世界](http://127.0.0.1:8765/world)。启动器会检查监听服务的身份，复用可用进程；探测超时不会直接结束原服务。完整行为与回退说明见[安装说明](docs/XIAONUAN-BODY.md)。

## 在新电脑运行源码包

`companion/` 是从实际运行应用导出的源码快照，包含聊天、人格、记忆、本地语音和 3D 页面实现。导出白名单及逐文件 SHA256 见 [SOURCE-MANIFEST.json](companion/SOURCE-MANIFEST.json)。它不含原用户数据，新电脑首次启动会生成自己的空数据目录。

```powershell
python -m pip install -r body-requirements.txt -r companion/requirements.txt
Copy-Item companion/.env.example companion/.env
# 编辑 companion/.env：填写自己的对话模型密钥和识别模型目录
python install_companion.py --target companion --remember
.\start-body.ps1
```

识别模型需自行准备。`MODELS_DIR` 指向包含 `sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2025-09-09/` 的目录（约 230MB）；可先查看 `companion/download_models.py`，需要下载时在 `companion/` 目录手动运行它。下载器会访问 Hugging Face，模型体积与许可证请自行核对，仓库没有附带模型。语音合成用微软晓伊，不需要下载模型，但文字会发给微软合成。

网页和实体共用人设里的音色（默认晓伊）。空模板没有可用的语言模型密钥，未配置前不能完成真实对话。

## 连接硬件

1. 确认真实芯片/运行时身份，再按 [接线表](docs/wiring.md) 和 [协议](docs/protocol.md) 核对硬件；不要只凭 USB 名称刷写。
2. 电脑与板子连同一个 **2.4GHz Wi-Fi**。`firmware/wifi.json` 的 `host` 是电脑的局域网 IPv4，`port` 为 5000。配置模板在 `firmware/wifi.json.example`；密码只存本机忽略文件。
3. 只向可信专用网络放行 TCP 5000，Companion 页面仍只监听本机。关闭占用同端口的旧 `wifi_demo.py`。
4. 使用 `tools/body_device.py` 备份、核对来源、部署、SHA256 读回校验后正常复位。具体命令和换网步骤见[安装说明](docs/XIAONUAN-BODY.md)。它不会替换整块 MicroPython 固件，也不会覆盖无关设备文件。
5. 开机/校准时让 FSR 保持空载，面板显示新鲜连接和校准完成后再按压。

## 验证

单元与回归测试需要 Python 依赖，Windows 启动测试需要 PowerShell，网页音频测试需要 Node.js：

```powershell
python -B -m unittest discover -s tests -q
python tests/body_e2e.py --source companion --api-port 18766 --tcp-port 19501
```

第二条使用隔离数据、模拟板和假语音/回复，不占正式端口、不写用户聊天。完整软件记录、本地模型环回和真实设备结果见[验证记录](docs/XIAONUAN-BODY-VERIFICATION.md)。`tools/body_voice_check.py` 可对正在运行的本地语音接口做环回检查，不播放喇叭、不写聊天。

实测已确认芯片、部署读回、Wi-Fi/TCP、压力校准，以及两轮实际 ASR → chat → TTS 接口成功。真实麦克风可懂度、扬声器听感与尾音、打断手感和长时间稳定性仍需真人验收。

## 目录与维护

| 路径 | 内容 |
| --- | --- |
| `companion/app/`, `companion/static/` | 完整电脑端源码、聊天/3D界面与资源 |
| `companion_extension/` | 部署到 Companion 的实体接口、面板和浏览器同步代码 |
| `body_bridge/` | TCP、压力检测、录音、同库对话、实体播放 |
| `install_companion.py`, `start-body.*` | 安全安装、记住本地路径、检查并启动服务 |
| `firmware/board/`, `tools/body_device.py` | 板上源码与备份/部署工具 |
| `tests/`, `tools/body_fixture.py` | 回归测试和隔离联调 |
| `docs/superpowers/` | 设计约定与实施计划 |
| `wifi/` | 原仓库保留的独立音箱演示；接入小暖时不同时运行 |

扩展功能的主维护源是 `companion_extension/`；修改后通过安装器更新并核对 `companion/` 中对应文件，导出清单记录最初快照而非持续变化的版本锁。涉及完整应用核心的修改，应单独准备可回退源码补丁，安装器不会整目录同步。

原硬件演示的说明保留在 [HARDWARE-LEGACY.md](docs/HARDWARE-LEGACY.md)。第三方音频、模型与 3D 资源的许可需在再分发时分别核对；本 PR 的源码整理不新增对这些组件的授权。
