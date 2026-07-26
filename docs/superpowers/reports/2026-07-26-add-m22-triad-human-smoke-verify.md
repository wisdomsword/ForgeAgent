# add-m22-triad-human-smoke 验证报告

## 结论

PASS。实现、测试、OpenSpec delta spec、OpenSpec design 与技术设计文档一致，未发现待修复的 CRITICAL、WARNING 或 SUGGESTION。

## 记分卡

| 维度 | 结果 | 证据 |
| --- | --- | --- |
| 完整性 | PASS | OpenSpec 6/6 tasks 完成；3/3 requirements 已实现 |
| 正确性 | PASS | 7/7 spec scenarios 有实现与离线回归覆盖 |
| 一致性 | PASS | 高层设计、技术设计、delta spec 与最终实现一致 |
| 构建 | PASS | `uv build` 生成 sdist 与 wheel |
| 测试 | PASS | 全量 `2219 passed, 10 skipped`；安全专项 `88 passed` |
| 质量 | PASS | Ruff、格式检查、`git diff --check`、OpenSpec strict 全部通过 |
| 复审 | PASS | 独立复审确认无 Critical、Important 或 Minor findings |

## Requirement 与 Scenario 映射

### 一键脚本运行真实模型 Triad 并保留人工计划确认

- `scripts/m22-triad-human-smoke.py` 使用固定 `--mode triad`、`--tier restricted`、`--no-identity`、`--no-memory` 和 `--max-rejections 2` 参数。
- ForgeAgent 子进程继承原生终端 stdin/stdout/stderr，不注入 `y` 或其他合成输入。
- 非 TTY、非法模型覆盖和虚拟环境缺失均在创建现场目录及调用模型前退出。
- README 明确费用、人工确认、模型覆盖和现场保留。

对应场景：人工批准、人工拒绝、非交互终端拒绝均由脚本控制流和离线测试覆盖。真实模型路径保持显式 opt-in，因此自动验证未替用户批准计划或消耗模型费用。

### 自动验证协作终态与可观察产物

- 状态加载只接受一份非 symlink 普通 JSON，并限制为 256 KiB。
- 状态投影校验 Triad completed、完整 Planner acceptance items、attempts、rejections 和逐项通过的 evaluation。
- `calc.py`、`test_calc.py` 必须是普通文件；pytest 与 CLI JSON 在现有 `check_runner` 的一次性项目副本和受限 worker 中执行。
- 生成代码不能继承 credential、访问宿主根外路径、联网或创建子进程；输出与失败诊断有界且不回显不可信正文。

对应场景：成功摘要、ForgeAgent/状态/文件/pytest/CLI 失败和现场保留均有确定性测试。

### 无需真实模型的离线回归

- 测试通过 fake subprocess runner 和 fake check runner 覆盖命令、状态及失败控制流。
- 安全回归使用真实 `check_runner` 验证环境、越界文件、网络和进程阻断。
- 自动测试不调用真实 ForgeAgent 模型路径、不访问用户 HOME、不消耗凭证。

## 安全复审

首次最终评审发现宿主 Python 直接执行模型生成代码的风险。修复提交改为复用 `forgeagent.check_runner`，并补充状态大小、完整 plan item 和启动异常边界。独立复审确认全部阻塞项已解决，且未引入新的问题。

## 分支处理

验证阶段暂时保留 `codex/feature/20260726/add-m22-triad-human-smoke` 分支和工作树，以便完成 Comet 归档。归档提交完成后再合并到 `main`、复验并 push。
