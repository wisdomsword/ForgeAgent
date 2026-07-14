## 1. 回归基线与测试隔离

- [ ] 1.1 将环境代理绕过、通用 confirmer 类型错误、同轮工具完成和 MCP 关闭卡住的复现固化为失败回归测试
- [x] 1.2 为 CLI/MCP 测试提供隔离 HOME 或配置根目录 fixture，证明真实 `~/.forgeagent/mcp.yaml` 不影响测试结果
- [x] 1.3 审核本地监听权限和进程计数相关测试，改为能力探测或稳定断言，并保留对真实资源泄漏的检测
- [x] 1.4 记录当前静态检查、隔离全量测试、Docker/网络可用性和已知环境限制，作为实施前基线

## 2. 网络边界安全

- [x] 2.1 增加大小写环境代理变量下 WebFetch 和 `/search` 必须直连的测试，并覆盖代理指向回环目标的绕过场景
- [x] 2.2 让受保护的 URL opener 显式禁用环境代理，同时复用现有目标解析、地址分类和逐跳重定向校验
- [x] 2.3 补齐私网、回环、链路本地、NAT64 和公网页面重定向到私网的回归覆盖
- [ ] 2.4 文档化 ForgeAgent 专用显式代理的未来契约与“本里程碑不实现代理转发”的边界

## 3. 工具确认与完成完整性

- [x] 3.1 为 MCP、WebFetch、FileWrite 参数分别增加 confirmer 格式化与批准/拒绝测试
- [x] 3.2 扩展现有 confirmer 使其类型安全地支持三类工具参数，不引入新的审批框架
- [x] 3.3 按 TTY 能力为 REPL 和单次 run 自动注入 confirmer，验证非 TTY 默认拒绝且 `--interactive` 仍只控制 Survey
- [x] 3.4 增加工具成功、工具失败、解析错误与 `completed: true` 组合的 Step 状态转换测试
- [x] 3.5 实施严格两阶段完成门控，只有后续无工具、无解析错误的独立响应可完成任务
- [x] 3.6 为 percent-encoded/大小写变化/重叠的 hostname secret、encoded delimiter、IPv6/zone-id、组件级 mask 交互、Unicode content character count、WebFetch guard/network 失败和 FileWrite 成功/写入失败结果增加泄漏回归测试
- [x] 3.7 实施固定安全 WebFetch 失败消息与 FileWrite project-relative 成功/固定失败消息，并验证 Step feedback 不再暴露原始 URL、hostname 或宿主绝对路径
- [x] 3.8 为 InvalidURL/BadStatusLine/LineTooLong/IncompleteRead/RemoteDisconnected、WebFetch artifact 写入、search 未知 charset、`allowed_root="/"`、非法路径及 FileRead/FileList 失败文本增加行为探针和回归测试
- [x] 3.9 实施 WebFetch/search 消费端异常收敛、canonical commonpath 文件边界和 FileRead/FileList 固定失败消息，并验证 CLI outcome 渲染不泄漏敏感路径

## 4. MCP 韧性与生命周期

- [x] 4.1 在 MCP 服务配置模型中增加默认 `false` 的 `required` 字段及兼容性解析测试
- [x] 4.2 实施可选服务连接失败降级，验证失败服务工具被排除且诊断包含服务名和原因
- [x] 4.3 实施必需服务连接失败的启动中止、资源清理和 CLI 非零退出测试
- [ ] 4.4 为正常关闭、无响应子进程、部分关闭失败、重复 close、daemon thread join 超时 warning 和延迟停止后的二次清理建立确定性测试并确定有证据的超时上限
- [ ] 4.5 使 `MCPManager.close()` 有界且幂等，为 loop thread 设置固定名称，在 manager 保存 shutdown future，由 loop coroutine 独占 holder wait/cancel 且只移除 done entries，future 超时时使用只读 fallback 并保留全部 pending 资源引用，允许重复 close 仅重试 cancel/stop/join，并保证关闭错误不覆盖任务结果或原始启动错误

## 5. 黄金验证核心

- [ ] 5.1 从 380 项候选中确定覆盖核心成功路径和本次风险边界的 20 个场景，并建立单一 manifest
- [ ] 5.2 为 20 个场景提供完全离线的 MockClient 响应、本地输入和自动判定期望
- [ ] 5.3 实现可重复 runner，输出逐场景机器可读结果、失败原因、人类可读汇总和通过率，并以失败状态控制退出码
- [ ] 5.4 标记其中 5 个真实模型兼容场景，提供显式 opt-in 运行入口和独立报告，确保基础 CI 不访问外部模型
- [ ] 5.5 将黄金核心接入项目验证命令，验证无网络、无 Docker、无凭证、隔离 HOME 环境下可完整执行

## 6. 契约与里程碑文档

- [ ] 6.1 更新模型客户端契约，准确描述当前 complete/streaming 和多模态支持边界
- [ ] 6.2 更新文本协议规范，纳入 WebFetch、FileRead/FileWrite 及严格两阶段完成语义
- [ ] 6.3 更新威胁模型、CLI 和发布说明，说明默认直连、环境代理禁用及企业代理迁移路径、symlink ancestor-swap 与 MCP incomplete-shutdown 残余威胁、TTY 确认和 MCP `required` 行为
- [ ] 6.4 更新黄金任务说明和 README，将 20 项标为可执行可信核心、其余 360 项标为候选，并说明 5 项真实模型运行不是 CI 门禁
- [ ] 6.5 按 `MILESTONE_GUIDE.md` 更新 ACTION_PLAN、相关历史状态说明、新加固里程碑文件和 `milestones/latest`，保留实证测试结果

## 7. 综合验证与审查

- [ ] 7.1 运行 Ruff 静态检查并修复本 change 引入的问题
- [ ] 7.2 在隔离 HOME 下运行完整 pytest，确保环境能力不足只产生有理由的 skip，不依赖人工 deselect
- [ ] 7.3 运行 SSRF/代理、CLI 确认、Step 完成和 MCP 生命周期专项测试，记录命令、结果与任何环境限制
- [ ] 7.4 运行 20 项离线黄金核心并核对逐项结果、报告、通过率和退出码；有凭证时仅补充非门禁的 5 项真实模型报告
- [ ] 7.5 对照 `spec.md`、本 change specs 和 CodeGraph 调用路径执行代码审查，确认没有扩大范围、遗漏调用方或产生文档漂移
