# 从对话生成可以进入的世界

## 先看示例（不需要任何密钥）

仓库自带一个完整生成好的示例：`companion/demos/scenes/zoo/`。它来自三句对话
（“噜噜，我今天去动物园玩了……”），包含场景规划、9 类绘本卡通 3D 模型和参考图预览。

1. 启动小暖（团队测试版双击 `Xiaonuan.exe`，或源码 `python -m xiaonuan_app` / `start-dev.cmd`）。
2. 打开梦幻世界 `http://127.0.0.1:8765/world`，开始页下方有 **“由对话生成的世界”**：
   每个世界都列出它来自的那段对话，点 **“进入这个世界 →”** 就能进去。
   示例直达：`http://127.0.0.1:8765/world?scene=demo-zoo`。
3. 进去后是有结构的动物园：入口门楼 → 环形步道 → 中心广场和休息亭；每种动物一个围栏展区
   （指示牌、动物小屋、按物种布置的地面），动物会呼吸、蹦跳走动，老虎在对峙冲撞。

示例是只读的：可以进入、查看对话和规划，不能在它上面重新生成或修订（不会花钱，也不会改动仓库）。
想用同样的对话自己生成一遍，在世界工作室新建场景即可。

## 自己生成一个世界

入口：`http://127.0.0.1:8765/world-studio`（开始页“用你自己的对话生成新世界 →”）。

需要在 `%APPDATA%\Xiaonuan\.env` 配置（字段见 `companion/.env.example`）：

| 用途 | 字段 | 说明 |
| --- | --- | --- |
| 场景规划 | `DEEPSEEK_API_KEY`（或 `SCENE_PLANNER_*`） | 把对话整理成标准场景规划 |
| 统一风格参考图 | `OPENAI_API_KEY`、`OPENAI_BASE_URL`、`OPENAI_IMAGE_MODEL` | 中转站要选它支持的生图模型，例如 `gpt-image-2.5-flare` |
| 建模 | `RODIN_API_KEY` | 每个模型约 0.5 积分 |
| 动物建模 + 绑骨（可选） | `TRIPO_API_KEY`（`tsk_` 开头的开放平台密钥） | 建模服务选“自动”时，动物用 Tripo 并自动绑骨、套待机/走路动作 |

完整流程：对话 → 场景规划（资产、实例、关系，统一绘本卡通美术方向）→ 每类资产 GPT 生成参考图
→ Rodin / Tripo 生成 GLB → 世界里按米制尺寸装配 → 卡通化（三档色阶、描边、接地阴影）
→ 语义布局（`app/scene_site.py`）→ 卡通动作或骨骼动作。
生成的场景保存在 `%APPDATA%\Xiaonuan\world-studio\<编号>\`，会同时出现在开始页的“由对话生成的世界”里。

把自己生成的场景变成仓库示例（去掉服务商任务令牌，参考图缩成预览）：

```powershell
python tools/export_scene_demo.py <场景编号> <示例名字>
```

输出到 `companion/demos/scenes/<示例名字>/`，编号为 `demo-<示例名字>`，打包团队测试版时会一起带上。

继续用 `start-dev.cmd` 启动源码应用。

## 原有世界怎么工作

`app/weaver.py` 用对话记忆、回忆和梦生成配方，`static/worldgen.js` 根据
配方用 Three.js 几何体、实例化植物、地标和粒子搭建世界。
`static/world.js` 实现第一人称行走：WASD、鼠标/拖动视角、加速度平滑、
重力、跳跃、地形高度、圆形/盒状碰撞和水域限制；伙伴带路使用网格寻路。
玩家移动不依赖生成模型自身有骨骼。

## 新流程

1. 粘贴用户与玩偶的对话，或明确点击“使用最近聊天”。示例不写入聊天库。
2. 专门的场景规划角色输出 `ScenePlan`，可独立配置模型和账户。
3. 每类资产有 `description`、单体 `image_prompt`、尺寸、碰撞范围和原话来源。
   `instances` 表达复用、位置、朝向及父节点；`relations` 表达停栖、打斗和邻近。
   JSON 经 Pydantic 校验引用、数量上限、父节点环路与坐标边界。
4. 可为每类资产上传参考图。GPT 统一风格和主体，随后使用 Rodin 或 Tripo 生成 GLB。
   不同资产并行：最多 2 个生图、3 个建模任务；前一批建模时后一批继续生图。
5. Three.js 读取实际 GLB，统一米制尺寸、水平居中和落地，再按场景图装配。
   多棵树共用一个模型，两只老虎也共用一个模型。沿用原有行走和碰撞系统。
6. “补充这个世界”调用规划模型修订；勾选的资产才重做。旧文件保留在版本目录，
   已完成的其他模型继续复用。入口预留出生点距离，建筑避开主要步道。

树的建模图只能包含树，不要把“鹦鹉在树上”的关系写入树的图像描述。
混合图可能让建模器选中错误主体。本轮演示实际发现并修正了这个问题：
旧树图混入一只鸟，Rodin 只重建了鸟；按树高复用后变成大量巨型鸟。
现在纯树资产与单只 0.6 米鹦鹉分别生成/装配，建筑作为设计补充明确标记 `inferred`。

## 动物园演示

输入三句原话在 `app/scene_plan.py` 的 `ZOO_CONVERSATION`。
实际规划与修订后的标准结构保存为 `companion/demos/zoo-blueprint.json`。
包含 9 类资产、35 个实例：24 棵树、5 种动物（老虎复用两次）、
1 个入口、1 座休息亭、3 间栖息棚，鹦鹉仅 1 只并归属于指定树。

演示已实际调用已配置的 GPT 图像服务和 Rodin；Tripo 也有适配与协议测试，
本次演示选用 Rodin。当前老虎用整体模型的位置/朝向时间线表现对峙和冲撞；
它是静态网格场景动画，尚未生成骨骼打斗动作。
地形、天空、草和道路继续使用原来的程序生成系统。

## 当前效果与下次工作

当前是管线与交互 demo。用户已确认独立浏览器可以操控，但认为精细模型与原有
低模环境混在一起显得突兀、粗糙、空旷。下一步应统一整体美术，完善连续道路、
展区边界、植被层次、地面材质、光照和空间密度；不能只靠继续添加独立模型解决。
本轮按用户要求保存到 GitHub，整体环境优化留待下次。

Codex 内嵌预览可使用右下角屏幕按钮；若 WASD 输入到了 Codex 聊天框，
点击“在独立浏览器游玩”，切换到 Edge / Chrome 窗口并点击进入。

## 本机配置与文件

设置保存在现有 `%APPDATA%\Xiaonuan\.env`，字段见 `companion/.env.example`。
也可设置同名环境变量。若已有模型工作台的 `.env`，可在本工作目录创建忽略文件：

```json
{"asset_env_file":"已有工作台的绝对路径/.env"}
```

文件名为 `.scene-local.json`，只保存本机路径，不复制密钥进源码。
修改后重启 `start-dev.ps1 -Restart`。
规划默认沿用 DeepSeek；`SCENE_PLANNER_*` 可改用专门模型。
生成资产与任务状态保存在 `%APPDATA%\Xiaonuan\world-studio/<场景编号>/`，
跟随 `XIAONUAN_HOME`；不放入 Git，不改原聊天和记忆。
签名下载地址和上游订阅密钥不返回浏览器。

任务记录持久化，查询暂时失败可继续原任务；提交结果未知不会自动重发付费请求。
文件下载限定公网 HTTPS、大小上限，并校验完整、自包含的 GLB 2.0。
替换生成资产后按内容哈希更新 URL，避免旧模型缓存。

## 验证

```powershell
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -q
```

`tests/test_scene_studio.py` 覆盖场景图、原话保持、并行上限和阶段重叠、
成品复用、任务恢复、未知提交不重试、参考图编辑、Tripo 协议、GLB 完整性、
单只鹦鹉/两只老虎/建筑清单、出生点及步道避让。
浏览器中额外检查真实模型导入、数量、比例、实际截图、WASD 走过入口与老虎运动。

API 文档依据：[GPT 图像生成](https://developers.openai.com/api/reference/resources/images/methods/generate)、
[Rodin](https://docs.hyper3d.ai/en/get-started/quick-start)、
[Tripo 图像建模](https://developers.tripo3d.ai/en/docs/generation-image-to-model/standard)。
