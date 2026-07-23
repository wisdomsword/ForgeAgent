## 1. MCP stderr 隔离与诊断

- [ ] 1.1 先写失败测试覆盖 per-server/generation `errlog` 注入、字节上限、成功 chatter 丢弃、secret masking、固定原因分类和旧 generation 不覆盖新诊断
- [ ] 1.2 实现有界 stderr sink、`stdio_client(..., errlog=...)` 接线和兼容现有 `server_status()` 的 masked diagnostic projection

## 2. 交互式启动呈现

- [ ] 2.1 先写失败测试覆盖真实 TTY、`NO_COLOR`、无颜色、窄终端、确认暂停、成功/异常/`Ctrl-C` 清理和无残留刷新线程
- [ ] 2.2 在 CLI 内实现最小 StartupRenderer、纯 ASCII 七色 Logo、初始化生命周期和模型/sandbox/project 摘要
- [ ] 2.3 实现 MCP `available/enabled` 摘要，确保 disabled 排除、optional 失败一行降级、required 失败不渲染部分 Ready

## 3. 非 TTY 与错误输出

- [ ] 3.1 先写失败的 CLI/子进程回归，固定 pipe quit 零 stdout/stderr、管道任务结果导向、`run`/`serve` 无 Logo 和 optional MCP 状态
- [ ] 3.2 统一 stdin/stdout TTY 判定，移除非交互 banner/prompt/启动状态，并把 required MCP 启动错误接到 sanitized stderr + 非零退出路径

## 4. `/mcp` 用户诊断

- [ ] 4.1 先写失败测试覆盖可用工具数、Reason / Impact / Action、Docker 非默认 sandbox 说明、unknown 降级、disabled 状态和 public label/secret masking
- [ ] 4.2 扩展 `/mcp status` 的结构化展示，保留 enable/disable、工具列表、timeout pending 和现有路由语义

## 5. 文档、评审与验证

- [ ] 5.1 更新 README 与相关 CLI/MCP 文档，记录交互/非交互输出契约、`/mcp` 诊断和无新依赖/权限边界
- [ ] 5.2 运行受影响测试、完整 pytest、ruff check/format、golden 20/20、OpenSpec strict、package build 和 diff check
- [ ] 5.3 完成两轮 whole-change 自审和独立代码评审，立即修复发现并重跑相关与完整验证
- [ ] 5.4 产出本 change 验证报告，执行 Comet verify/archive，并确认所有既存 dirty 路径未进入本 change 提交
