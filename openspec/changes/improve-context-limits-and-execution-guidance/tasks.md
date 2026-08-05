## 1. 共享限额解析

- [x] 1.1 增加先失败的 context 测试，覆盖 adaptive、configured、effective、低值和模型切换计算
- [x] 1.2 实现一个不可变的反馈限额解析结果，并由 SlidingWindowContextPolicy 消费

## 2. 交互可观察性

- [x] 2.1 增加先失败的启动、`/model`、`/reload`、低值告警与非交互静默测试
- [x] 2.2 在规定的交互边界显示紧凑的实际反馈限额和当前模型低值告警

## 3. 执行指引

- [x] 3.1 增加先失败的固定协议与 mock replay 测试，覆盖 Survey 澄清、完整目标工具选择、Exec 递归聚合和文件交付
- [x] 3.2 更新固定协议，不改变工具 schema、sandbox 检查或直接 prose 完成语义

## 4. 用户配置

- [ ] 4.1 在不读取或输出敏感值的前提下，验证已授权的 120/40 两行仍各精确存在一次
- [ ] 4.2 只删除这两行，并验证其余字节与文件权限不变

## 5. 验证

- [ ] 5.1 运行 context、CLI、identity、prompt、Task 与 HTTP 专项测试
- [ ] 5.2 运行 lint、类型检查、完整测试、OpenSpec 严格校验和真实模型受控重复文件扫描 REPL smoke
- [ ] 5.3 审查 diff 中是否存在公式漂移、secret 泄漏、非交互输出回归、prompt 越界或无关改动
