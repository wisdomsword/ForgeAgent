## 1. TDD 安全修复

- [x] 1.1 增加真实 restricted 子进程模块劫持回归，并确认当前启动命令执行伪造 worker 而 RED
- [x] 1.2 使用 Python isolated mode 最小化加固 worker bootstrap，并确认伪造 worker/runtime 不再执行

## 2. 文档与验证

- [x] 2.1 更新 threat model，运行专项、完整 pytest、golden、Ruff、build、OpenSpec strict 与 diff check
