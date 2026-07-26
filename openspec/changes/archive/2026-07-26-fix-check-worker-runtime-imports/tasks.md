## 1. TDD 修复

- [x] 1.1 增加真实 `python -m pytest` RunCheck 回归并确认因 `_pytest._code` 导入失败而 RED
- [x] 1.2 为 audit hook 增加 check-worker-only Python 运行时目录枚举白名单，并保持普通 restricted 默认不变
- [x] 1.3 运行 check runner 与 M22 artifact 定向测试，确认真实保留现场通过

## 2. 文档与验证

- [x] 2.1 更新 threat model 与 ACTION_PLAN，记录最小可见性和真实人工验证状态
- [x] 2.2 运行完整 pytest、Ruff、build、OpenSpec strict、diff check 与代码审查
