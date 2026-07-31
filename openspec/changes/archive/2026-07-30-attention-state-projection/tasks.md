## 1. 注意力协议

- [x] 1.1 增加有界 attention-state 类型/辅助函数和旧 `needs_info` 映射，并添加单测。
- [x] 1.2 增加状态转换审计事件，以及安全掩码/截断测试。

## 2. Loop 接入

- [x] 2.1 扩展 Loop 的 stop-reason/status 不变量，支持 `needs_input`、`blocked`，持久化有界元数据，并覆盖 checkpoint/report/resume 行为。
- [x] 2.2 映射 Survey/模型的 attention 结果，不改变普通完成、取消或 `external_action_pending` 语义。

## 3. HTTP 投影

- [x] 3.1 为普通 Task、Loop、Duo、Triad 记录的 TaskService snapshot 增加附加式 `attention` 投影。
- [x] 3.2 增加 HTTP 生命周期测试，覆盖 running、needs-input、blocked、ready、旧版兼容和安全披露。

## 4. 文档与验证

- [x] 4.1 更新 HTTP/Loop/threat-model 文档及 attention-state 语义的验证证据。
- [x] 4.2 运行专项测试、完整 pytest、Ruff、build、OpenSpec strict 和最终两轮一致性评审；保持 PyPI 发布暂停。
