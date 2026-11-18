# 真实模型验收

公共入口是 [`scripts/live_model_acceptance.py`](../scripts/live_model_acceptance.py)，
依赖仓库内的 Golden fixtures 与协作实现，须从 Git checkout 使用。它不属于安装 wheel 后
的 CLI 子命令，也不提供图像生成产品功能。环境安装见[依赖说明](dependencies.md)。

## 配置与默认预览

[`examples/gateway/acceptance.yaml`](../examples/gateway/acceptance.yaml) 列出三个文本模型、
两个图像模型以及 Duo/Triad 的角色选择。调整模型 ID 以匹配自己的服务。
`context_window`、`max_output_tokens` 是本次验收预算，不是厂商最大能力声明。

```bash
uv sync --locked
uv run python scripts/live_model_acceptance.py --suite all
```

默认只校验 YAML 并打印计划，不要求 Key、不发请求、不创建输出目录。可以显式加
`--dry-run`。配置拒绝未知字段和直接写入的 `api_key`。

付费执行需要事先在自己的 shell 中配置 `MAAS_SD_API_KEY` 和 `MAAS_BASE_URL`。
后者必须是 HTTPS 站点根，不带 `/v1`、查询参数、账号或密码；不要把值提交到仓库。
入口会为文本添加 `/v1`；图像路径由 `image_path` 选择 `/v1/images/generations`
或 `/api/v3/images/generations`，不自动回退或重试。

```bash
# 以下命令会调用外部服务并可能产生费用
uv run python scripts/live_model_acceptance.py --suite text --allow-paid-requests
uv run python scripts/live_model_acceptance.py --suite collaboration --allow-paid-requests
uv run python scripts/live_model_acceptance.py --suite images --allow-paid-requests
```

`--suite all` 运行全部检查。`--config` 可指定自己的 YAML。`max_requests` 是整个进程的
请求次数上限，包含失败请求；SDK 重试关闭。它不是货币金额上限，费用仍取决于服务定价。
单次请求超时由 `timeout_seconds` 限制，不表示整个套件的总时限。

## 判定与证据

- 文本：每个模型检查一次流式响应，并执行现有五项真实 Golden：G01/G03/G08/G11/G43。
- 协作：Duo 和 Triad 创建固定的求平方和函数与至少四项 unittest；仅确认两个候选文件的
  FileWrite，Triad 仅预授权这个固定验收目标的计划。报告完成后仍以新 restricted worker
  独立验证 0、1、10、37、负数行为及生成的测试，失败不会判为通过。
- 图像：每个模型发送一次请求，要求 base64 PNG，检查 PNG 签名、IHDR 和尺寸。
  返回 URL 不会被下载，重定向不会被跟随，响应上限 32 MiB。不支持其他图像格式。
  这不是完整图像解码或视觉质量评估；生成图片仍需人工审阅。尺寸与请求不符即失败。

输出写入 `artifacts/model-acceptance/<时间-随机标识>/`，包含总报告、脱敏文本响应、
Golden 报告、协作 workspace 与 PNG。可用 `--output-dir artifacts/<新目录>` 自定义；
输出必须位于仓库 artifacts 下且目录尚不存在，避免覆盖旧证据。

退出码：0 表示预览成功或全部自动检查通过，1 表示运行检查失败，2 表示配置预检失败。
异常只公开异常类型；具体模型输出可检查本地证据。已知敏感环境值会被日志脱敏，
但无法保证删除所有个人信息；不要直接公开运行产物。整个 artifacts 目录默认被 Git 忽略。

历史验收中两个图像模型对 1024×1024 请求返回了 1254×1254，属于尺寸契约失败。
新增入口不会将这类响应算作通过，也不代表本次重新调用过这些模型。

## 在产品 CLI 使用网关

[`models.yaml`](../examples/gateway/models.yaml) 和
[`config.yaml`](../examples/gateway/config.yaml) 可分别合并到自己的
`~/.forgeagent/models.yaml`、`~/.forgeagent/config.yaml`。保留已有配置；不要直接覆盖。
这里的 `MAAS_OPENAI_BASE_URL` 需要包含 `/v1`，与验收入口的根地址变量分开。
图像生成模型没有加入文本路由注册表。
