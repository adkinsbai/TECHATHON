# TECHATHON · 交互式玩偶与 3D 角色资产

仓库包含两个可独立运行的模块：

| 模块 | 入口 | 说明 |
| --- | --- | --- |
| MORI 模型与骨骼实验室 | pnpm dev → http://127.0.0.1:5173/ | 文字 / 图片 → 风格迁移 → Rodin 3D → Tripo 自动绑骨 → Blender 检查 |
| ESP32-S3 WiFi 语音节点 | python wifi/wifi_demo.py → http://127.0.0.1:8081/ | 麦克风、FSR、音频传输与语音演示，见下文 |

## MORI 模型与骨骼实验室

需要 Node.js 22.18+；在仓库根目录执行 pnpm install 和 pnpm dev。复制 .env.example 为 .env，配置各服务 Key；Blender 4.5 LTS 单独安装。

当前聚焦形象生成和骨骼调试，已移除工作台的聊天、互动模拟和换装界面。支持 GLB 导入导出、真实骨骼检查、动画试播和 Blender 工程转换。硬件模块继续保留原有功能，两者尚未接成统一桌宠运行层。

[完整启动与使用说明](docs/CHARACTER-WORKBENCH.md) · [接入说明](docs/INTEGRATION.md) · [绑骨路线](docs/RIGGING-ROADMAP.md)

检查：pnpm test、pnpm build；准备 Blender 后可运行 pnpm test:blender。密钥、模型输出、本机网络配置和工具安装不随代码提交。

---

## ESP32-S3 语音音箱节点（WiFi）

一块 ESP32-S3-N16R8 + ES8311 音频模块 + INMP441 麦克风 + FSR 力传感器，
通过 **WiFi（TCP）** 和电脑通信：电脑负责解码、识别、回复和语音合成，板子只负责
"把 PCM 写进 I2S" 和 "把麦克风读出来"。

### 系统结构

```
               ┌──────────────────────── 电脑 (Windows / Python) ───────────────────────┐
 浏览器 :8081  │  wifi_demo.py：网页控制台 + TCP 服务端 + 解码/音量/推流                │
   │           │  asr.py：Vosk 本地识别（中文小模型）                                  │
   ▼           │  brain.py：离线规则回复（可替换成大模型）                              │
 控制台 ──────►│  TTS：Windows SAPI（Huihui 中文女声）                                  │
               └───────────────▲──────────────────────────────┬───────────────────────┘
                               │ AUD(96KB/s) / MODE            │ MIC(48KB/s) / STAT / SENS
                               │                               ▼
                        ┌──────┴──────────────────────────────────────┐
                        │            ESP32-S3（MicroPython）           │
                        │  board_main.py：TCP 客户端 + 环形缓冲 + I2S │
                        │  es8311.py：Codec 配置                      │
                        └──────┬───────────────────────┬──────────────┘
                               │ I2S TX                │ I2S RX / ADC
                        ES8311 + NS4150B          INMP441 / FSR
                               │
                             喇叭
```

### 目录

```
audio-node-v1/
├─ README.md                  ← 本文件
├─ docs/
│  ├─ protocol.md             通信协议（帧格式、消息类型、字段）★重点
│  ├─ wiring.md               三个器件的接线表
│  └─ wiring.html             三合一接线图（浏览器打开）
├─ firmware/
│  ├─ micropython-esp32s3-1.25.0.bin   板上固件（MicroPython）
│  ├─ board/
│  │  ├─ main.py              开机自启入口
│  │  ├─ board_main.py        板子端主程序（TCP + I2S + ADC）
│  │  └─ es8311.py            ES8311 驱动（只写不读）
│  ├─ install_wifi.py         把上面的文件写进板子
│  ├─ set_wifi.py             生成 wifi.json（SSID / 密码 / 电脑 IP）
│  └─ wifi.json.example       配置模板
├─ wifi/                      电脑端
│  ├─ wifi_demo.py            网页控制台 + 推流 + 录音/识别/回复
│  ├─ wifi_link.py            帧协议、TCP 服务端、麦克风落盘
│  ├─ asr.py                  Vosk 本地识别
│  ├─ brain.py                离线规则回复（可替换）
│  ├─ agent_demo.py           命令行版"录音→回复→说话"
│  ├─ board_sim.py            假板子（没有硬件时验证电脑端）
│  └─ requirements.txt
└─ tools/
   └─ board_exec.py           在板子上跑一段 Python 的调试工具
```

### 快速开始

#### 0. 电脑环境

```powershell
cd wifi
python -m pip install -r requirements.txt
```

语音识别模型需要单独下载（约 42MB，未随包分发）：

```powershell
## 下载 vosk-model-small-cn-0.22.zip 后解压到 wifi\models\
## 最终目录形如： wifi\models\vosk-model-small-cn\{am,conf,graph,ivector}
```

没有模型时，录音仍能保存，只是不能自动识别。

#### 1. 烧录固件（仅首次）

用 `firmware/micropython-esp32s3-1.25.0.bin` 通过 esptool / Flash Download Tool
烧到 **0x0**（板子是 ESP32-S3-N16R8）。

#### 2. 配置 WiFi 并写入板子文件

```powershell
cd firmware
python set_wifi.py --ssid "你的热点"          # 会提示输密码，并自动填电脑的 WLAN IP
python install_wifi.py                        # 找串口并把 main.py / board_main.py 等写进去
```

> 板子只支持 **2.4GHz**；电脑和板子必须在同一个局域网里。
> 电脑要通过防火墙放行 **TCP 5000**（第一次运行时 Windows 可能会弹窗）。

#### 3. 运行电脑端

```powershell
cd wifi
python wifi_demo.py
```

浏览器打开 <http://127.0.0.1:8081/>：

- **播放/暂停/上下曲/音量/歌单**：音频通过 WiFi 推到板子播放
- **开始录音**：录一段话，自动识别 → 交给我/规则回复 → 音箱念出来
- **力传感器**：实时显示 raw / mV
- **/wiring**：三合一接线图

音乐目录默认是 `D:\CloudMusic` 和本包根目录下的 `music\`，可以在 `wifi_demo.py`
顶部的 `MUSIC_ROOTS` 里改。

### 通信协议（摘要）

完整说明见 **[docs/protocol.md](docs/protocol.md)**。

一条帧：

```
AA 55 AA 55 | type(1) | len(2,LE) | payload | checksum(2,LE)
checksum = (sum(payload) + type*31 + len) & 0xFFFF
```

| type | 方向 | 名称 | 内容 |
| --- | --- | --- | --- |
| 0x01 | 电脑→板子 | AUD | 24kHz 立体声 16bit PCM，每帧 4096 字节（42.7ms） |
| 0x02 | 电脑→板子 | MODE | 0 空闲 / 1 播放 / 2 录音 |
| 0x03 | 电脑→板子 | PING | — |
| 0x81 | 板子→电脑 | MIC | 24kHz 单声道 16bit PCM，≤2048 字节 |
| 0x82 | 板子→电脑 | STAT | 8 字节：模式/缓冲%/欠载/失步/RSSI/丢帧 |
| 0x83 | 板子→电脑 | PONG | — |
| 0x84 | 板子→电脑 | LOG | UTF-8 文本 |
| 0x86 | 板子→电脑 | SENS | 4 字节：ADC raw(2) + 毫伏(2)，10Hz |

### 已知限制

- **半双工**：麦克风和喇叭共用一路 I2S，录音时不放音、放音时不录音。
- 力传感器当前若跳线在 D 侧，只能得到 0/4095 两档；放 A 侧才有连续力度值。
- Vosk 小模型对短命令会听错（例如"换一首"→"患有个"），靠上下文纠错。
- 只支持 2.4GHz WiFi；建议用手机热点，避免会场网络的设备隔离。

### 第三方组件

- MicroPython（MIT）— `firmware/micropython-esp32s3-1.25.0.bin`
- Vosk（Apache-2.0）— 通过 pip 安装，中文模型需自行下载
- miniaudio / pyserial — pip 安装
