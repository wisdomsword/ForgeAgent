# 真实模型验收：2026-11-18

修复前首次验收结论：三个文本模型的 Single 任务与流式检查通过；两个图像模型能够出图，但尺寸参数不符合请求，Sunburst 首次请求失败后复试成功。Duo/Triad 未通过，发现 restricted worker 的标准库子模块导入缺陷，不能据此宣布整个 Agent 已通过真实模型验收。

**后续修复复验**：标准库导入问题已修复，Duo/Triad 在新目录均 completed，Evaluator 提交与独立函数、unittest 检查均通过。详见[修复验证报告](2026-11-18-fix-restricted-stdlib-imports-verify.md)。下文保留首次验收的原始结果及范围，图像参数偏差未在该修复中处理。

## 范围与环境

- 被验源码：提交 `a2bc878`，macOS arm64，Python 3.14.7。本轮未修改产品代码、模型注册表或用户配置。
- 用户指定服务：`https://maas.wetokenshub.cn`。文本走 `/v1/chat/completions`，成功的图像请求走 `/v1/images/generations`。
- 鉴权取自进程环境 `MAAS_SD_API_KEY`；长度和指纹与用户提供的信息匹配。密钥没有写入配置、命令参数或验收产物。`/v1/models` 返回 20 个模型，包含全部五个指定 ID。
- 本轮发送真实请求，会产生费用；未读取账单，不能从 token 数或内部 cost 字段推断实际金额。
- 固定的合成 CSV/JSON、边界修复题、词频题和平方和代码在独立目录运行；未加载个人 Identity、Memory、Skills 或外部 MCP。
- 原始 JSON、模型响应、脚本和图像保存在忽略的 `artifacts/live-acceptance-2026-11-18/`，不随本报告发布。

## 文本模型：15/15 Golden，3/3 流式检查通过

复用仓库现有真实 Golden 五项：G01 CSV 汇总、G03 嵌套 JSON 展平、G08 修复边界错误并保持原测试不变、G11 合并去重排序、G43 词频 Top-N。验收检查实际文件内容、顺序、数值或测试见证，不仅检查模型声明。

| 模型 | Golden | 五项合计耗时 | Golden complete 请求数 | 流式检查 |
| --- | --- | ---: | ---: | --- |
| `glm-5.3-flash` | 5/5 | 235.59 秒 | 18 | 通过，3.70 秒，1 个正文 delta |
| `deepseek-v4.1-flash-1017` | 5/5 | 69.94 秒 | 23 | 通过，1.83 秒，3 个正文 delta |
| `glm-5.3-flashx` | 5/5 | 89.37 秒 | 18 | 通过，4.98 秒，1 个正文 delta |

流式检查通过实际 `OpenAICompatibleClient.stream()` 请求精确输出 `ACCEPTED`，检查正文、唯一 DONE、结束原因及无 ClientError。Golden 通过真实 `Task`、协议解析、工具与 restricted worker 执行。使用显式临时 capability（64K 上下文、4096 输出上限，未声称这些是服务商模型极限），不向生产注册表硬编码路由；provider 重试设为一次尝试，单个模型最多 40 次 Golden 请求。三个模型实际各计 19、24、19 次 provider 尝试，含各一次流式请求，均无传输错误。

证据：各模型目录内 `results.json`、`report.md`、`responses.jsonl`、`stream.json`、`attempts.json`。这是一轮小样本功能验收，不是可靠性统计或底层模型版本认证。

## 图像模型：生成可用，精确尺寸未通过

每个模型请求 `n=1`、`size=1024x1024`、`response_format=b64_json`，提示为白底、左侧红圆、右侧蓝方。两张实际 PNG 均已打开检查，基础形状、颜色和位置符合提示，无文字。

| 模型 | 生成结果 | 成功请求耗时 | 返回尺寸 | 判定 |
| --- | --- | ---: | --- | --- |
| `gpt-image-2.5-flare-c` | 首次 `/v1` HTTP 200，1 张 PNG，1,037,803 字节 | 78.258 秒 | 1254×1254 | 能出图；精确尺寸不符合请求 |
| `gpt-image-2.5-sunburst-c` | 首次 `/v1` HTTP 500；最终 `/v1` 复试 HTTP 200，1 张 PNG，990,814 字节 | 110.339 秒 | 1254×1254 | 能出图；有首次上游失败及尺寸偏差 |

Sunburst 首次失败的原始响应：

```json
{"error":{"message":"upstream error: do request failed (request id: 202611180549119930016968268d9d6fB2KUGb3)","type":"new_api_error","param":"","code":"do_request_failed"}}
```

按用户提及的另一条路径诊断时，`/api/v3/images/generations` 对 Sunburst 返回 HTTP 400：

```json
{"error":{"code":"InvalidParameter","message":"model \"gpt-image-2.5-sunburst-c\" is not served by this plugin"}}
```

因此本轮不能将 `/api/v3` 宣称为这两个图像模型的可用协议；Flare 未向该路径提交生成请求。保留 Sunburst 的 `result-v1-initial.json`、`result-v3-probe.json` 和最终 `result.json`，没有覆盖失败证据。每个最终图像的 SHA-256 已记录在结果 JSON 中。

这里验证的是网关图像生成 API；ForgeAgent 现有图像输入能力与新增原生图像生成工具均不在本轮结论中。两个模型的整体图像判定是“部分通过”，不是完整参数兼容通过。

## 协作验收：未通过，定位到标准库导入边界

固定任务：生成 `sum_squares.py` 与 `test_sum_squares.py`，用标准库 unittest 验证 0、1、10、-1，并在完成后提交候选。Generator 使用 DeepSeek，Planner 使用 GLM Flash，Evaluator 配置 GLM FlashX。Triad 采用现有 headless `preauthorize` 策略，仅批准这项固定测试的计划；不构成交互式人类审批 UX 验收。

首轮未接入 FileWrite 确认通道，写入被正确拒绝。该轮 Duo 停为 `invalid_role_submission`，Triad 停为 `role_failed`，不能当作成功。临时脚本随后错误调用 `RestrictedBackend.close()`，报告写出中断：

```text
AttributeError: 'RestrictedBackend' object has no attribute 'close'
```

已修正临时脚本，从持久化状态恢复首轮报告，没有为恢复报告重复模型请求。第二轮在全新目录中仅批准两个指定文件的 FileWrite，拒绝其他路径、全盘授权与网络确认，保留首轮证据。

| 第二轮 | 模型请求数 | 耗时 | 持久化状态 | 独立函数检查 |
| --- | ---: | ---: | --- | --- |
| Duo | 10 | 85.11 秒 | `failed / invalid_role_submission` | 通过 |
| Triad | 11 | 131.30 秒 | `stopped / max_rounds` | 通过 |

独立检查在 restricted worker 中通过 `runpy.run_path()` 加载候选，验证 0、1、10、额外未提供的 37（结果 17575），以及负数抛 ValueError。两个候选函数均正确；协作未完成，Evaluator 均未运行，不能把独立函数正确写成协作完成。

两个 Generator 在执行 unittest 时遇到相同缺陷。无模型最小复现：

```python
RestrictedBackend(allowed_root=temporary_project).execute(
    "import unittest\nprint(unittest.TestCase)", Runtime()
)
```

实际 worker 输出末尾：

```text
    from .result import TestResult
ModuleNotFoundError: No module named 'unittest.result'
```

宿主同一解释器 `python -I` 能正常导入 unittest，`unittest/result.py` 确实存在。独立诊断进程安装同一 audit hook 后复现失败；仅给 `readable_directory_roots` 添加解释器目录，同样导入即成功并打印 `TestCase`。证据见 `unittest-probe.json` 与 `import-policy-comparison.json`。

根因：`src/forgeagent/_sandbox_worker.py` 的文件 open 允许解释器目录，但 `os.listdir`/`os.scandir` 仅允许项目目录及显式 readable roots。Python 首次发现标准库包的子模块需要枚举目录，被拒绝后表现为 ModuleNotFoundError。外层全盘授权会扩大过多权限，不是本问题的合适解决办法。

首次验收的修复建议：对受信任解释器库目录允许只读枚举，使其与现有库文件读取规则一致；保留项目外写入、普通宿主目录枚举、网络、进程和回执保护。增加冷启动 `unittest`/嵌套标准库导入回归与反向边界检查，然后重跑本次 Duo/Triad。首次验收时该问题是发布前阻塞项，未在该次验收中修改源码；后续修复及复验结果见上方链接。

## 其他观察与剩余边界

- `~/.zshrc` 实测权限为 `644`，不同于用户提供的 `600`。未修改权限或重新 source；本轮直接使用已继承的 key。建议将其收紧到 `600`，避免同机其他用户读取凭据。
- 向网关反馈两项图像问题：`size=1024x1024` 被返回为 1254×1254，以及 Sunburst 首次 `do_request_failed`。不要在客户端静默改尺寸后宣称服务遵循原参数。
- 没有修改 shell 全局环境、用户配置或生产路由，没有新增依赖、发布、tag 或远端 push。
- 未验证图像编辑、图片输入理解、长上下文、负载/并发稳定性、实际账单、其他操作系统以及人工交互审批体验。
