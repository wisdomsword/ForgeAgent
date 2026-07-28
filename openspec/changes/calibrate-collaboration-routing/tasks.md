## 1. 路由合同

- [x] 1.1 添加 RED resolver 与审计测试，覆盖显式模式、默认 Single、冻结检查 Triad 和兼容输入
- [x] 1.2 添加 RED CLI、REPL、Loop 与 HTTP 集成测试，证明无宿主证据的编程目标默认 Single
- [x] 1.3 简化协作路由，删除过期编程分类，并使较弱模式覆盖确认不可达

## 2. 冻结 M25 派生分析

- [x] 2.1 添加 RED 测试，覆盖不可变输入、误完成双分母、精确终止原因、分组成本指标和路由裁决
- [x] 2.2 实现标准库 M27 派生脚本，并生成加法式 JSON 与 Markdown 产物
- [x] 2.3 独立复算派生产物，并确认全部 M25 冻结输入保持字节不变

## 3. 文档与证据

- [x] 3.1 修正 README Memory 行为，不改变 M18 runtime 语义
- [x] 3.2 将 Linux verified 文字收窄到 Pipeline 50 / Job 249 证据，并删除过期 configured 矛盾
- [x] 3.3 用 M27 策略、裁决和最终当前基线更新 README、ACTION_PLAN、威胁模型和平台文档

## 4. 验证与收尾

- [ ] 4.1 运行路由、集成、派生分析与文档合同定向测试
- [ ] 4.2 运行全量 pytest、OpenSpec strict、Golden 20/20、Ruff check/format、打包和 diff 检查
- [ ] 4.3 完成两轮最终自审与独立代码评审，修复全部确认问题并重复受影响验证
- [ ] 4.4 创建并归档 M27，更新 milestones/latest，并完成已授权的分支收尾流程
