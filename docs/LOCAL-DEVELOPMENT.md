# 同一台 Windows 电脑开发、测试和更新板子

使用主分支的源码和 Python 3.12，无需反复打包或解压团队测试版。
角色素材实验在独立分支维护，不需要合并到硬件开发分支。

## 首次准备

在仓库根目录运行：

```powershell
.\setup-dev.ps1
# Python 不在默认安装目录时：
.\setup-dev.ps1 -Python '你的 Python 3.12 路径\python.exe'
```

依赖安装在本工作目录忽略的 `.venv/`。源码应用仍使用
`%APPDATA%\Xiaonuan` 中已有的密钥、聊天、人设和记忆。
如原来设置过 `XIAONUAN_HOME`，继续使用它指向的目录。
无需把个人数据复制进仓库，也无需运行安装器把扩展复制到另一份应用。

把现有测试包的识别模型目录复制到 `%APPDATA%\Xiaonuan\models/`，
或设置 `XIAONUAN_MODELS_DIR` 指向现有模型父目录。
完整模型目录包含 `model.int8.onnx` 和 `tokens.txt`。

## 每次开发

双击 `start-dev.cmd`，或运行 `./start-dev.ps1`，打开
`http://127.0.0.1:8765/setup`。先关闭旧的测试版应用。
修改 Python 后重启源码应用加载改动：

```powershell
.\start-dev.ps1 -Restart
```

`-Restart` 仅请求本工作目录的源码进程正常退出；身份无法确认、
探测超时或退出失败时停止操作。页面静态文件修改后刷新浏览器。
USB 负责更新程序，运行中的声音和传感器数据仍通过 Wi-Fi TCP 5000。

## USB 检查与更新

串口号以本机实际枚举为准，不沿用另一台电脑的 COM11。
探针会暂时中断板上程序，读取芯片身份、源码哈希和 GPIO8/GPIO9，
随后正常复位，不替换板上文件。运行期间不要同时打开其他串口工具。

```powershell
.\.venv\Scripts\python.exe tools/body_probe.py --port COM7
# 第一次迁移时，可恢复板子已有 Wi-Fi 配置，不在控制台输出密码；拒绝覆盖本机已有配置：
.\.venv\Scripts\python.exe tools/body_probe.py --port COM7 --save-config
```

`firmware/wifi.json` 为忽略的本机文件。确认其 `host` 是这台电脑的
局域网地址；使用 Windows 移动热点时为 `192.168.137.1`，热点为 2.4GHz。
只在可信网络上放行本地子网到 TCP 5000。

修改 `firmware/board/` 后执行：

```powershell
.\flash-dev.ps1 -Port COM7
```

这个命令通过现有 `tools/body_device.py` 更新板上 Python 源码，
不重刷 MicroPython。先确认实际 ESP32-S3 身份、备份相关文件到
`runtime/device-backup-*`、核对来源，再部署、逐文件 SHA256 读回并正常复位。
来源未知时会停止并保留备份，不覆盖无关文件。

## 双压力传感器排查

- 右手信号线接 GPIO8，按住说话；左手信号线接 GPIO9，只感知触碰。
- 通电和校准时两只手均松开。左手需获得稳定且不低于 2500 的空载读数才能校准。
- 设置页分别检查“有数据 / 校准 / 按住”：没有数据先查板上程序；
  未校准检查接线和空载值；已校准但按压读数不下降检查电路和实际接触。
- 左手单独按下再松开才提交触碰。两只手在 1 秒内先后按下，均松开后提交抱抱。
- 软件通过不代表实际麦克风、喇叭或传感器手感验收完成。

## 隔离验证

```powershell
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -q
.\.venv\Scripts\python.exe tests/body_e2e.py --source companion --api-port 18766 --tcp-port 19501
```

联调使用备用端口、假板和隔离数据，不往原聊天库写入模拟对话。
