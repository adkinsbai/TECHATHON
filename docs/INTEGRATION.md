# 模型实验室接入说明

当前主流程：文字 / 图片 → 风格迁移 → 二维确认 → Rodin 静态 GLB → Tripo 骨架识别与蒙皮 → Blender 校准。界面仅保留“形象生成”和“骨骼调试”。桌面运行层、互动、换装与行为事件暂不包含在内。

## 前端与资产

React 管理输入、参考图确认和任务状态；Three.js 提供 GLB 导入、线框、真实骨骼、手动动画播放、姿态复位与导出。支持单文件嵌入资源的 GLB（200 MB 以内），含 Draco 和 Meshopt 解码器。

草稿仍使用原 localStorage 键，保留旧描述、模型名称与旧材质值；读取旧字段不代表旧功能仍显示。新风格保存在 referenceStyle。旧参考图没有风格字段时按“保持原风格”处理，签名保持兼容。修改文字、参考图、姿态或目标风格都会使旧完成图失去自动确认资格；也可明确选择以某张完成图为准。

当前模型写入 IndexedDB。导入时统一到约 2.6 单位高、地面中心，Y 向上。源文件哪个方向是正面仍需检查。模型导出包含实际已有的骨架、蒙皮、形变和动画，不凭空创建互动。

导出调试包：character.glb、asset-report.json、preview.png、rig-debug.md。报告区分当前模型数据与编辑草稿，骨骼数量不代表视觉验收。Blender 工程在任务记录中单独下载。

## 图像准备和 Rodin

- POST /api/references/prepare：multipart prompt、images、TAPose、style、inputSignature。至少一种输入模态；最多 5 图，每图 5 MB。
- style 仅支持 preserve / plush / clay / toon。目标风格由服务端固定模板转为图像指令，实际发送给图像服务；无图时文生图，有图时图文编辑。
- POST /api/references/import：导入已完成的单张参考图，不调用图像服务。
- GET /api/references、/:id、/:id/image：本地状态和图片。缓存于 .local/references/。
- POST /api/generate：只接收 referenceId、referenceConfirmed=true 和 TAPose。服务端从缓存取确认图，固定 Rodin Gen-2.5-Medium / Raw / GLB / 20,000 目标面 / PBR。
- GET /api/jobs、/:id、/:id/model：Rodin 状态与本机模型，缓存于 .local/rodin/。

图像 API 使用配置的 HTTPS /v1 端点，不把登录网页 token 当作 API 地址；认证请求不跟随重定向。Rodin 的文字参数不能可靠完成语义换装，因此先在二维图中落实风格与修改，再用最终图重建 3D。

## Tripo 自动绑骨

配置 TRIPO_API_KEY，可选 TRIPO_PROXY_URL（你已有的 HTTP CONNECT 代理，只作用于 Tripo 认证请求与输出下载，保留 TLS 验证）。API Key、上传 token、上游任务 ID 和签名下载地址只留在后端。

1. POST /api/auto-rigs：上传当前静态 model GLB，最多 150 MB。服务端先验证模型，然后使用 Tripo v3 的 POST /files 上传，取得 file_token，再调用 POST /animations/rig-check。不会自动进入绑骨。
2. GET /api/auto-rigs 和 GET /api/auto-rigs/:id：本机任务列表和状态；状态查询至少间隔 5 秒，遇限流遵循 Retry-After。
3. GET /api/tripo/account 读取 API 可用 / 冻结点数。绑骨前再次检查余额；余额为 0 时不创建绑骨任务，保留已检查模型，页面提示并禁用绑骨按钮。
4. 预检查返回 riggable=true 后，POST /api/auto-rigs/:id/bind（multipart rigType）单独创建绑骨任务。双足 / others 显式使用 v3.0-20260909；其他生物骨架使用 v2.5-20260210。只有双足发送 spec=mixamo；输出 GLB。
5. 全部完成后，服务端下载并检查 GLB 的实际 skin、joint 和 weight 属性，将模型保存在 .local/tripo/<id>.glb。GET /api/auto-rigs/:id/model 提供本机文件。
6. POST /api/auto-rigs/:id/blender：从缓存结果创建 Blender 检查工程，保留原骨架与权重。重复请求复用已创建或运行中的本地工程任务。

本地任务记录 .local/tripo/jobs.json 同时保存上传和上游任务标识。上传 / 提交中断时标为结果未知，不自动重新提交；已有上游任务 ID 的检查 / 绑骨可在重启后继续查询。服务商返回成功但缺少实际蒙皮时，不提供成功模型。点数显示采用服务商返回值，不从示例响应推测价格。

预检查与自动绑骨均按账户实际计费规则执行。明确被拒绝的 HTTP 4xx 提交保留已检查模型；不会自动重试，恢复额度后仍需手动确认。网络结果未知则不重新提交。没有动画的绑骨输出仍是有效资产，页面如实显示动画数量为 0；不生成虚构动画。需要在 Blender 做姿态验证，再制作正式动作或另接重定向。

## Blender

需要 Blender 4.5 LTS。使用后台隐藏窗口、禁用自动脚本执行参数和独立任务目录；不通过 shell 拼接模型路径。子进程不继承图像、Rodin 或 Tripo API Key。单次任务超时 10 分钟。

- POST /api/rigging/import：将已有蒙皮的 GLB 转为检查工程，不重绑。Tripo 输出也走相同方法。
- Blender 导入原模型、统计骨骼与实际权重、打包纹理、保存 character.blend。GLB 输出为原字节复制，因此保留原动画、形变和蒙皮数据。原始骨架有未绑定顶点时仍保留工程供修正，检查不标为通过。
- GET /api/rigs 和 GET /api/rigs/:id：Blender 状态；/:id/model、/blend、/report 下载文件。缓存于 .local/rigs/<id>/。
- 备用 POST /api/rigs：人工定位 mori-biped-v1 的 19 骨模板，再计算骨热或距离蒙皮。此流程只针对静态双足角色，不是自动解剖识别，默认折叠且不运行定位辅助层。

备用骨热先焊接重合顶点，保留面角 UV 和材质；距离蒙皮按最近四条骨段生成平滑初始权重，不识别衣物 / 肢体语义。两者均需人工修正。不要对 Tripo 输出再次执行这套模板。

## 验证

pnpm test 使用模拟服务响应，不消耗真实服务额度。pnpm build 检查类型和生产构建。pnpm test:blender 使用自建测试网格验证骨热、距离蒙皮及已有双骨骨架 / 形变 / 动画保留，不访问外部生成服务。

2026-10-17 版本已验证：39 项自动测试、生产构建、三种本机 Blender 集成场景。真实 Tripo 测试已完成外部 Rodin 兔子上传与预检查，识别为双足。真实 Tripo 骨架输出与整条 Tripo → Blender 联调尚未完成，具体外部条件见本机任务记录，不上传账户数据。已验证的 Blender 转换使用自建蒙皮资产，不冒充 Tripo 生成结果。

## 服务边界

服务只监听 127.0.0.1，校验 Host 与跨域来源，拒绝浏览器访问 .env、.local、.git。模型下载校验 HTTPS 和公共地址，签名地址不发给浏览器。换机器或重新部署需准备各自密钥、Blender 和网络；不要将本服务直接公开部署。

接口依据：[Rodin](https://docs.hyper3d.ai/en/api-specification/rodin-gen2-5)、[Tripo 文件上传](https://developers.tripo3d.ai/en/docs/files)、[Tripo 预检查](https://developers.tripo3d.ai/en/docs/animations-rig-check)、[Tripo 绑骨](https://developers.tripo3d.ai/en/docs/animations-rig)、[Tripo 状态查询](https://developers.tripo3d.ai/en/docs/task-query)。
