# port-task-filesystem-authority 验证报告

日期：2026-08-04  
基线：`97af2c2cd8e0359957e43b02d9063078ea888d49`  
实现提交：`8332262`、`9c84ddd`  
工作流：Comet tweak，full verify

## 结论

PASS。9/9 tasks 完成，7/7 requirements 和 33/33 scenarios 均有实现与测试证据；没有剩余 CRITICAL、IMPORTANT 或 WARNING 问题。

| 维度 | 状态 | 证据 |
| --- | --- | --- |
| Completeness | PASS | tasks 9/9；requirements 7/7 |
| Correctness | PASS | scenarios 33/33；受影响面 889 passed；全量 2821 passed、11 skipped |
| Coherence | PASS | 实现遵循 change design；M47 HTTP approval/receipt/headless 语义保留 |

## Requirement 映射

| Requirement | 实现与测试 |
| --- | --- |
| Project identity root and task filesystem authority are independent | `task.py`、`step.py`、`tools.py`、`collaboration.py`；Task、File/WebFetch、collaboration 回归 |
| Trusted tier has consistent host filesystem access | `task.py` tier/root 推导；trusted Exec/File 测试 |
| Restricted tasks can receive one task-scoped full-disk filesystem grant | `RequestFilesystemAccessTool`；批准、拒绝、缓存、backend swap、Task 生命周期测试 |
| Container filesystem mounts do not expand at runtime | container 固定拒绝；非 restricted 边界测试 |
| Runtime authority facts are host-derived and explicit | `Task._runtime_authority_prompt`；默认/自定义 prompt、built-in/custom backend 测试 |
| Restricted tools use one type-safe confirmation interface | CLI/REPL 确认摘要；MCP/WebFetch/FileWrite/Request 类型测试 |
| Full-disk confirmation is single-use, task-scoped and minimally disclosed | Task 决定审计、CLI task id、外部路径 basename、后续副作用独立确认测试 |

## 安全复审闭环

首次独立审查发现三项必须修复的问题：扩权后相对 `..`/symlink 可借 broadened root 逃逸，CLI single Task 未透传 audit sink/task id，外部 FileWrite confirmation audit 记录完整父目录。三项均先取得失败测试，再修复：

- 相对路径现在同时以 immutable project root 解析和做 realpath containment；绝对路径才使用当前 filesystem root。
- `run_once`、main run 和 REPL 三条 single 路径传递 audit sink，每次 Task 生成独立非空 task id。
- FileWrite confirmation audit 仅记录 project-relative 路径或外部 basename；原始参数仍交给 confirmer，不改变用户确认内容。

修复后的独立复审未发现 P1/P2 或新的 correctness/security 回归。低风险残余是 FileWrite/FileList 没有各自重复同一共享 resolver 的扩权逃逸测试；共享 `_validate_context_path` 已由 WebFetch symlink 与 FileRead `..` 两种行为直接覆盖，因此未增加重复测试。

## 验证命令

- `UV_CACHE_DIR=/tmp/forgeagent-m48-main-uv-cache rtk uv run pytest -q ...affected...` -> `889 passed`
- `UV_CACHE_DIR=/tmp/forgeagent-m48-main-uv-cache rtk uv run pytest -q` -> `2821 passed, 11 skipped in 156.03s`
- `UV_CACHE_DIR=/tmp/forgeagent-m48-main-uv-cache rtk uv run ruff check .` -> `All checks passed!`
- `UV_CACHE_DIR=/tmp/forgeagent-m48-main-uv-cache rtk uv run ruff format --check .` -> `147 files already formatted`
- `rtk openspec validate port-task-filesystem-authority --strict` -> valid
- `rtk git diff --check` -> clean

全量测试在受控沙箱外运行，因为既有 HTTP/blackbox 测试需要绑定本机 loopback，打包测试需要执行隔离的 `uv build`。没有进行 Git push。

## OpenSpec / Design 一致性

delta spec 对 verify 阶段发现的三项安全边界已补充 scenario，change design 的 Decisions 与 Risks 同步更新，不存在 spec/design 漂移。该 change 使用 tweak preset，按流程不生成独立 Superpowers Design Doc；本项不构成缺失。
