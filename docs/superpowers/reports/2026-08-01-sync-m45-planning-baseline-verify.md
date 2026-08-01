# sync-m45-planning-baseline 验证报告

- 日期：2026-08-01
- Comet workflow：tweak
- 范围：同步 M45 规划基线、将 canonical 基线契约改为跟随 `milestones/latest`、加固生命周期门禁
- 运行时源码：无修改

## 结论

通过。两份借鉴评审文档的当前基线已与 `milestones/latest` 指向的 M45 一致；M44 仍作为 loopback HTTP 动作审批的历史交付证据。规范和测试不再把 M44 或 M45 永久写死为未来基线，发布目标移除与开发分支 push 的区别保持不变。

## TDD 证据

### RED

命令：

```text
uv run pytest tests/test_borrowing_roadmap.py tests/test_repository_lifecycle.py -q
```

旧文档仍声明 M44 时得到 `2 failed, 15 passed`：借鉴评审 frontmatter 不含 `M45`，生命周期门禁读到 `baseline_number=44`、`latest_number=45`。

### GREEN

同步文档后，同一命令得到 `17 passed`。加入治理文档专项后得到：

```text
22 passed in 0.03s
```

独立审查进一步指出综合评审缺少里程碑证据路径，原测试也未解析两份文档的编号/路径。收紧门禁后先得到
`1 failed`（综合评审基线无法解析），补齐证据链接、M45 四项 change 记录和 `M32-M45` 验证范围后，
治理文档专项再次得到 `22 passed`。

## 完整门禁

- 全量测试：`2734 passed, 10 skipped in 171.77s`
- Ruff：`All checks passed!`
- 格式：`146 files already formatted`
- 本地构建：sdist 与 wheel 均成功；未上传产物，未执行 PyPI、正式 tag 或发布自动化
- OpenSpec strict（归档前）：`36 passed, 0 failed`，包含本 change
- `git diff --check`：通过

## 边界核对

- 当前基线由 `milestones/latest` 决定，目标里程碑文件必须存在，评审 frontmatter 与正文编号必须一致。
- 两份评审文档都必须携带同一里程碑证据路径，目标里程碑必须声明“已完成并归档”。
- M44 继续证明 HTTP action-bound approval；M45 不被表述为该能力的首次交付者。
- HTTP listener 仍为 loopback-only；公网入口和 Gateway 仍是条件候选。
- 包索引发布、正式 tag、以分发为目的的远程 push 和发布自动化仍不在路线图。
- 普通开发分支 push 仅用于已授权的版本控制交接，不恢复发布目标。

## 独立审查

只读审查发现并已修复：综合评审缺少 `milestone_045.md` 证据链接；M45 里程碑仍记录三个而非四个
change；验证范围仍停留在 M32-M43；基线测试只做字符串包含、无法阻止 stale process metadata；范围描述
与同步借鉴文档的事实冲突。审查未发现发布边界放宽、secret/绝对路径泄漏或无关运行时源码修改。
