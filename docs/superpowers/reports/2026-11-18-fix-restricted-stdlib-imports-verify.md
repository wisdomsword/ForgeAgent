# restricted worker 标准库导入修复与真实模型复验

本次将普通 restricted worker 的解释器目录枚举配置与既有 check worker 对齐。生产代码只增加 `readable_directory_roots=(sys.base_prefix, sys.prefix)`；Duo/Triad 真实复验及独立产物检查均通过。

## 根因与修复

上一轮[真实验收](2026-11-18-live-model-acceptance.md)中，宿主能导入 unittest，但 restricted worker 找不到 `unittest.result`。包首次导入需要枚举子目录，而普通 worker 只允许枚举项目目录；解释器前缀文件读取与目录发现权限不一致。

修复只在普通 worker 入口指定受信任解释器目录，不改共享 hook、文件写入规则、网络/进程限制或回执保护，也不预加载标准库。威胁模型同步记录只读枚举范围。不增加依赖、全盘权限、厂商端点或 API key。

## 回归与安全边界

在修改生产代码前，新增 12 个实际 subprocess 回归，观察到原始失败：

```text
11 failed, 1 passed, 19 deselected in 3.48s
```

其中 unittest 与 XML 子模块导入、项目 unittest 执行、目录枚举失败；部分反向测试也先被同一个导入错误阻断。修复后 12 个回归全部通过，并继续验证后续越界操作被正确拒绝。覆盖：

- 冷启动 unittest、XML、email 包导入与项目内 unittest 执行。
- `listdir`、`scandir` 允许读取解释器库目录。
- 项目外普通宿主目录及其项目内 symlink 别名仍不可枚举。
- 导入成功后，在项目外解释器前缀写文件、创建目录仍被拒绝。

restricted backend、回执/descriptor/output 边界与 check runner 联跑：`96 passed in 22.53s`。最低支持版本 Python 3.11.15 上的新回归：`12 passed, 19 deselected in 3.78s`。

## Duo/Triad 真实模型复验

用户明确授权沿用 MAAS 服务及环境中的凭据。请求发送到用户指定的 `/v1/chat/completions`，没有修改生产路由或用户配置。仅发送固定合成任务、角色运行提示和测试反馈；密钥仅作请求鉴权。

与上一轮保持相同目标：实现平方和函数与 unittest 文件，覆盖 0、1、10、负数。Generator：`deepseek-v4.1-flash-1017`，Planner：`glm-5.3-flash`，Evaluator：`glm-5.3-flashx`。新目录位于忽略的 `artifacts/restricted-stdlib-fix-2026-11-18/`，没有覆盖旧失败记录。

| 模式 | 状态 / 停止原因 | 请求数 | 耗时 | 通过的计划项 | Generator / Evaluator 尝试 | 拒绝次数 |
| --- | --- | ---: | ---: | ---: | --- | ---: |
| Duo | completed / completed | 6 | 24.91 秒 | 1/1 | 1 / 1 | 0 |
| Triad | completed / completed | 8 | 85.91 秒 | 6/6 | 1 / 1 | 0 |

交叉验证依据不只依赖模型声明：

- 校验真实结果 JSON 与持久化 `CollaborationState`，确认 completed phase、提交计数、完整计划 ID 和通过的 Evaluation ID 对齐，无失败计划项。
- 两组实际候选均在新 restricted worker 中独立检查 0、1、10、额外的 37（17575），以及负数 ValueError，均打印 `INDEPENDENT_CHECK_PASSED`。
- 再独立加载并运行每组生成的 unittest，要求至少四个测试且全部成功，均打印 `INDEPENDENT_UNITTEST_PASSED`。
- 固定只批准 `sum_squares.py` 与 `test_sum_squares.py` 写入，拒绝其他路径、全盘授权及网络操作。Triad 采用既有 headless preauthorize，仅针对这项合成验收任务；不构成人工交互审批体验验收。

provider 自动重试关闭，每次验收最多 40 次请求；实际共 14 次请求，无拒绝重做。费用可能产生，未读取账单。

## 最终集成验证

pytest: `3171 passed, 1 skipped`；OpenSpec strict: `42/42`.

macOS arm64 / Python 3.14.7 完整测试实际输出：

```text
3171 passed, 1 skipped in 277.11s (0:04:37)
```

JUnit 记录 3172 项测试，零失败、零错误、一个跳过。十项 Docker integration 在本次完整运行中全部执行通过；Docker Desktop 使用当前 context endpoint，仅传入测试子进程。唯一跳过是 PATH 中无 `python3.11` 时的可选跨解释器 digest 检查，独立 Python 3.11 验证不用于篡改该 skip。

OpenSpec CLI 1.13.1 归档前 strict 为 43/43（42 主规格加一个 active change）；同步修改一项既有 requirement 并[归档](../../../openspec/changes/archive/2026-11-18-fix-restricted-stdlib-imports/)后为 42/42。五个任务全部完成，README 与 ACTION_PLAN 指向本报告。

已完成 Ruff lint 与格式检查（160 文件）、离线 Golden 20/20、wheel/sdist 构建。新 wheel 的 Python 3.11.15 隔离安装后六项冒烟全部通过：clean-wheel、CLI、真实 loopback HTTP、Single、Duo、Triad。这里的安装后协作冒烟使用确定性客户端，与上面的真实模型结果分别计证。

更新 README 当前验证链接后重新构建最终 wheel，并重新执行上述六项隔离安装冒烟。wheel 中 57 个包文件与最终源码逐字节一致。最终 wheel SHA-256：`a906d7af7cfd45892ed6d48112477f664bcff4347632331832bd5d7949b39469`。

规格归档及报告、入口更新后的文档回归：`33 passed in 0.58s`；diff 空白检查通过。

## 证据与范围

本地原始证据位于忽略的 `artifacts/restricted-stdlib-fix-2026-11-18/`：

- `duo-scoped-writes/`、`triad-scoped-writes/`：真实响应、控制台、attempts、结果、原始状态、两个候选文件和独立 unittest 结果。
- `live-summary.json`：状态交叉验证、独立检查及候选文件 SHA-256。
- `golden/results.json`、`dist/`、`clean-wheel-python311.json`、完整 pytest 日志和 JUnit。

先前失败日志和图像尺寸/上游稳定性问题继续保留在上一轮报告中。本次没有重新调用图像模型或重跑全部真实 Golden；未验证跨平台、长时间稳定性或实际账单。没有发布、tag 或远端 push，也没有修改参考项目。
