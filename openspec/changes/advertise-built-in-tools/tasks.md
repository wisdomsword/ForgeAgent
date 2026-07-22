## 1. 固定工具协议

- [x] 1.1 在 identity prompt 测试中增加默认内置工具目录和 FileWrite 精确 ToolCall 的失败断言
- [x] 1.2 更新包内固定协议，公开七个默认工具并消除 direct tool 与 Exec-only 指令冲突

## 2. 验证

- [x] 2.1 运行 identity、Task、Step、HTTP allowlist 相关回归与静态检查，并保留 M16 真实模型黑盒复跑入口
