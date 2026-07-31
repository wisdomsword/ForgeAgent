# Attention State Projection 验证报告

- Change: `attention-state-projection`
- 范围：Task/Step attention 映射、Loop checkpoint/report 停止语义、HTTP 附加式公开投影
- 发布约束：PyPI 发布继续暂停；未上传包、未创建 tag、未 push
- 结论：专项验证通过；全量门禁见下方新鲜证据

## 关键契约

- `running / needs_input / blocked / ready` 与既有 `completed / failed / cancelled` 分离。
- 旧 `needs_info`、`Termination.NEEDS_INFO` 和 `ToolOutcome.needs_info` 保持可读，并附加 `needs_input` 投影。
- Loop 的 `needs_input`/`blocked` 使用 `status=stopped`，attention 随 checkpoint 原子保存；`external_action_pending` 保持优先且不自动重放。
- HTTP 只增加有界 `attention` 字段，保留既有 `status`、`reason`、`detail` 和模式字段。
- attention 文本做 secret/path masking、控制字符清理和 500 字符上限；审计只记录状态/原因等安全字段。

## 测试证据

```text
uv run pytest tests/test_attention.py tests/test_step.py tests/test_task.py \
  tests/test_loop_checkpoint.py tests/test_loop_runner.py \
  tests/test_http_task_service.py tests/test_http_server.py -q
344 passed

uv run pytest -q
2447 passed, 10 skipped

uv run ruff check .
All checks passed!

uv run ruff format --check .
123 files already formatted

uv build
Successfully built forgeagent-0.1.0.tar.gz and forgeagent-0.1.0-py3-none-any.whl

openspec validate --all --strict --no-interactive
Totals: 25 passed, 0 failed
```

新增测试覆盖：旧 Survey 映射、模型声明 blocked、Loop 旧 checkpoint 迁移、attention stop 持久化、HTTP running/needs-input/blocked/ready 投影和敏感文本边界。

## 两轮自评

第一轮逐项对照 proposal、design、三份 delta spec 和 tasks：所有实现接口均有对应代码与专项测试，未新增 endpoint、scheduler、自动恢复或新依赖。

第二轮检查模糊、错误、过度保守、前后不一致、遗漏和泄露：修正了 attention 控制字符清洗的字符间空格问题、补齐旧 checkpoint 默认迁移、保留 `external_action_pending` 优先级，并将 HTTP 字段作为 additive projection；未发现待修问题。
