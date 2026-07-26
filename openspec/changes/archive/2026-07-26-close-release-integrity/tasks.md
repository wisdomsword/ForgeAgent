## 1. 发布边界 TDD

- [x] 1.1 在 `tests/test_packaging.py` 增加 sdist 根文件 allowlist 与开发目录/用户文件负向内容合同，并确认当前默认 sdist 进入 RED
- [x] 1.2 在 `pyproject.toml` 配置最小 sdist allowlist，使真实 build 内容合同进入 GREEN

## 2. 当前验证文档合同

- [x] 2.1 修改 `tests/test_collaboration_docs.py`，验证 README 当前验证章节唯一且格式正确，同时保留历史 M22 文件数字合同
- [x] 2.2 更新 README 当前验证章节为本次最终新鲜 pytest 与 OpenSpec strict 结果，不篡改历史报告和里程碑

## 3. 完成门禁

- [x] 3.1 运行包装专项、文档专项、完整 pytest、golden、Ruff、build、sdist 内容检查、OpenSpec strict 与 diff check，并完成两轮一致性自审
