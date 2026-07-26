## 1. RED：冻结候选文件门禁合同

- [x] 1.1 为 `SubmitCandidate` 增加缺失文件、符号链接/目录拒绝、状态不推进和默认兼容的失败测试
- [x] 1.2 为 CLI 私有候选文件 JSON 增加缺省、合法、有界非法与无敏感值回显测试
- [x] 1.3 为 M22 脚本增加子进程注入 `calc.py`/`test_calc.py` 且不改变人工确认的离线测试

## 2. GREEN：实现最小宿主门禁

- [x] 2.1 实现有界顶层文件名规范化与基于目录描述符的普通文件检查
- [x] 2.2 将可选要求从 `run_collaboration_once` 传入 Runner、generator registry 与 `SubmitCandidateTool`
- [x] 2.3 在 CLI 解析私有环境配置，并由 M22 脚本仅对子进程注入固定要求

## 3. 文档与验证

- [x] 3.1 更新 README、ACTION_PLAN 与相关规格，说明门禁职责和真实人工复测方法
- [x] 3.2 运行定向测试、完整 pytest、Ruff、build、OpenSpec strict 与 diff check
- [x] 3.3 完成标准代码审查、修复 findings，并记录真实模型验证仍需人工批准执行
