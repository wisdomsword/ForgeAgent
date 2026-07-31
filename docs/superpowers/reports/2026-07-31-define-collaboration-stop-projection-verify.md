---
change: define-collaboration-stop-projection
date: 2026-07-31
status: verified
release_actions: paused
---

# Verification Report

## Scope

本 change 为 Collaboration 建立确定性的 Task/Loop 停止原因投影，透传资源耗尽、需要输入和阻塞语义，并把内部执行目标与公开 handoff 目标分开。没有执行 PyPI、tag、push 或发布自动化。

## Evidence

- `UV_CACHE_DIR=/tmp/forgeagent-m39-review-uv-cache uv run pytest -q tests/test_collaboration_stop_projection.py tests/test_collaboration_runner.py tests/test_collaboration_models.py tests/test_collaboration_handoff.py tests/test_http_task_service.py tests/test_http_server.py`：225 passed。
- `uv run ruff check ...`：通过。
- `uv run ruff format --check ...`：通过。
- `openspec validate define-collaboration-stop-projection --strict --no-interactive`：通过。
- `uv build`：通过；仅构建 wheel/sdist，未上传。
- 全量 `pytest`：通过；结果记录在 M39 总体验证中。

## Contract Review

第一轮检查映射矩阵、旧状态兼容和 handoff trust boundary；第二轮检查未知原因 fail-closed、attention 与 reason 一致性、资源停止不伪报等待输入，以及合法路径不会被内部执行 goal 脱敏。发现并修正了测试对 HTTP 公开 attention 的重复假设，保留已有 HTTP attention 投影，不扩大本 change 的职责。

## Residual Risk

Loop 自身仍保留其既有 handoff 字符串结构；该问题由后续独立 change 处理。Duo 验收计划也不在本 change 范围内。
