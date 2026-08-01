# M47 验证报告：客户端生命周期与输入契约

- 状态：验证命令已通过，Comet 已推进至 archive
- 日期：2026-08-02（Asia/Shanghai）
- 变更：`harden-client-lifecycle-and-input-contracts`
- 基线提交：`599909d2849eb611f5310f78e5dadfb3fa4e4365`

## 验证门禁

- `uv run pytest`：`2781 passed, 11 skipped`（Python 3.14.3）。
- `uv run ruff check .`：`All checks passed!`。
- `uv run ruff format --check .`：`147 files already formatted`。
- `uv build`：源码分发包和 wheel 均构建成功；仅作本地验证，不执行发布。
- `openspec validate --all --strict`：`37 passed, 0 failed`。
- Python 3.11.15 下模型、CLI、HTTP、协作、lifecycle 专项：`511 passed, 1 skipped`。
- Python 3.12.12 下同一专项：`511 passed, 1 skipped`。
- Python 3.14.3 下同一专项：`511 passed, 1 skipped`。
- 三个受支持解释器均可见时，跨版本 lifecycle digest probe：`1 passed`；子进程只依赖标准库，不依赖 pytest 安装。

## 两轮最终评审

### 第一轮：行为与所有权

- Provider SDK client 延迟创建，complete/stream 共用实例，并由拥有它的 provider 幂等关闭。
- 注入 transport 继续由调用方拥有；`Task.close()` 不关闭注入的 model client。
- CLI、smoke、evaluate、HTTP 构造失败和 role 路径均覆盖正常返回、提前返回与异常关闭，顺序保持 Task 在前、client 在后。
- 模型生成参数、能力声明和 registry entry 拒绝非正数及非有限值；provider fallback 使用显式 `None` 语义。
- lifecycle verifier 继续按 AST 定位目标，但对规范化源码片段做摘要，保留变更检测且不依赖 Python AST dump 版本细节。

### 第二轮：泄漏、范围与归属

- 未新增运行时依赖、Rust 重写、PyPI、tag、push 或发布自动化。
- provider 清理日志只输出固定 provider 标签；原始 SDK close 异常不会进入公开投影。
- 现有 evaluation 公开错误文案和请求投影均由全量测试覆盖。
- `git diff --check` 干净；收尾阶段只有一处 M41 行数门禁的最小语义保持修复，以及 verifier 子进程自包含修复，均属于已批准生命周期/verifier 范围。

## 已知 skip 与风险

- 全量测试的 11 个 skip 是既有环境依赖（主要是 container/runtime 不可用）；M47 没有新增 skip。
- 三个解释器的专项各有一个既有 repository-lifecycle 环境 skip；在解释器均可用时，跨版本 digest 断言实际执行并通过。
- `dist/` 构建产物只是本地验证文件，不代表已执行任何发布动作。

## Comet 证据

- OpenSpec strict 验证已通过。
- 验证报告路径已登记到 `.comet.yaml`，且 `branch_status: handled`。
- 最终由 verify 阶段守卫推进状态机到 archive。
