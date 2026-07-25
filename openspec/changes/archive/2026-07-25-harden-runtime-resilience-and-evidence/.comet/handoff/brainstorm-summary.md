# Brainstorm Summary

- Change: harden-runtime-resilience-and-evidence
- Date: 2026-07-25

## 确认的技术方案

- 采用单一 change 收敛 P2/P3，但只实现可验证的韧性与已有能力可靠性，不为清单完成堆叠新产品面。
- Evaluator 使用宿主冻结的 `RunCheck` 检查 ID；模型不能定义 argv、cwd、env、timeout 或输出上限。检查在临时项目副本中执行，不修改真实项目。
- 检查使用无 shell 子进程、最小环境、固定超时、进程组终止、有界脱敏输出和确定性清理；默认无检查定义时不注册工具。
- 取消只承诺安全边界停止；可持有子进程句柄的 `RunCheck` 支持及时终止，provider/MCP 等同步宿主调用继续依靠冻结 timeout，不伪造 Python 线程强杀。
- MCP hung-call 永久 skip 改为短 deadline 本地 test double 回归。
- `/search` 在首选引擎失败或零结果时最多 fallback 一次到另一个内置引擎，每次请求仍独立经过现有网络 guard。
- 使用当前可用凭证和 Docker 环境执行真实证据；环境不满足时记录阻塞，不扩大产品行为。
- native tool-call 流式聚合按现有回归结项；持久历史、语义摘要、音视频与响应侧多模态继续延期并记录触发条件。

## 关键取舍与风险

- 不开放普通 `Exec`，避免 Evaluator 获得任意代码、写入与进程能力。
- 临时副本增加 I/O，但比构建通用 snapshot/overlay 系统更小；排除 `.git`、`.forgeagent`、虚拟环境、缓存和构建产物。
- 固定 fallback 最多增加一次搜索请求，不做动态 engine/router。
- 真实模型结果只作为当次证据，不声称永久质量提升。

## 测试策略

- 全部行为改动使用 TDD：先验证未知 ID、参数注入、隔离副本、timeout/cancel、输出脱敏与清理的 RED。
- MCP 使用本地永不完成 async test double，验证短 deadline、close 和 generation 隔离。
- 搜索使用两个固定引擎的请求顺序与错误矩阵，不访问公网。
- 完成后运行专项、全量 pytest、Ruff、离线 golden、build、OpenSpec strict；真实模型与 Docker 证据单独记录。

## Spec Patch

无。OpenSpec delta specs 已覆盖确认后的行为与边界。
