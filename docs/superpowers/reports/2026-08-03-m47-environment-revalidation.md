# M47 环境依赖复验补证

- 日期：2026-08-03（Asia/Shanghai）
- 范围：M47 归档后复验原先记录的 11 个环境依赖项
- 原则：只补充新鲜验证证据，不修改 M47 历史里程碑、原始验证报告或实现代码

## 验证结果

- [x] Docker 容器/隔离专项：`uv run pytest -q tests/test_container_backend.py -m container_integration --junitxml=/tmp/forgeagent-container-junit.xml`，`10 passed, 4 deselected`。
- [x] 支持的 Python 解释器：3.11.15、3.12.12、3.14.3 均可用。
- [x] M34 verifier 跨版本 digest probe：`test_m34_verifier_digest_is_stable_across_supported_interpreters`，`1 passed`。
- [x] 全量回归（loopback、Docker daemon、三个解释器均可用）：`2792 passed in 189.35s`，无 skip。

## 环境说明

- Docker Desktop daemon 在复验前未运行；启动后成功拉取/检查 `python:3.11-slim` 并通过全部 10 个真实容器测试。
- 首次受限沙箱运行受到 loopback bind、外部网络和用户级 uv cache 权限限制，产生环境型失败；同一命令在受控环境中重跑后通过，未发现代码回归。
- 未执行 PyPI、tag、release automation 或远程 push。

## 结论

- [x] M47 遗留的 11 个环境依赖项已在具备运行条件的主机上补证闭合。
- [x] 不需要新增功能里程碑；M43 继续保持 `keep_python`，HTTP 继续保持 `loopback-only`。
- [x] 后续仍按 `milestones/milestone_047.md` 的真实触发条件启动独立变更。
