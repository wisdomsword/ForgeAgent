## Context

真实失败现场显示 `calc.py` 和 `test_calc.py` 均正确，但 Evaluator 的每次 `FileRead` 都在 147 字符处截断。用户配置中的 40-token 单工具和 120-token 单轮 feedback 上限与该现象精确对应。

## Fix

CLI 的内部 context loader 接受一个仅供受信任仓库包装脚本使用的进程环境 JSON 覆盖。M22 脚本在启动 ForgeAgent 子进程时设置只含以下内容的 JSON：

```json
{"context":{"round_feedback_max_tokens":4000,"tool_result_max_tokens":2000}}
```

模型注册表继续从原用户配置加载 provider group、base URL 和 credential。覆盖值不写回用户文件，也不包含或复制 credential。普通 CLI 未设置该内部环境变量时保持现有行为。

## Safety

- JSON root 和 context 字段继续走现有 `load_context_config()` Pydantic 校验。
- 无效内部覆盖沿用 CLI 的稳定 config-error 路径。
- ForgeAgent 子进程仍继承 stdin/stdout/stderr；仅额外传入继承环境的副本和一个非敏感 JSON 值。
