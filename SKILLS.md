# 项目 Skill

Claude 可读取 [.claude/skills/xiaonuan-body-development/SKILL.md](.claude/skills/xiaonuan-body-development/SKILL.md)，也可通过项目入口 `CLAUDE.md` 找到它。其他代码代理遵循 `AGENTS.md` 并手动读取同一份指南。

适用：继续开发小暖电脑端/实体、修改本地语音或传感器、排查安装与断线、准备验证和 GitHub 交接。

这份 skill 提供工作步骤；工程事实和历史问题在 `MEMORY.md`，命令在 `README.md` 与 `docs/XIAONUAN-BODY.md`。不需要安装作者电脑的全局 skill、读取私人会话记忆或复制任何个人配置。

编写依据是本次实际遇到的故障：深层 Windows 路径、raw REPL 软复位不执行启动程序、健康探测超时、在线音色影响实体。后续改动必须以隔离测试和真实设备证据区分软件通过与实物验收。
