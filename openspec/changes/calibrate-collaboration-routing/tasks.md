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

- [x] 4.1 运行路由、集成、派生分析与文档合同定向测试
- [x] 4.2 运行全量 pytest、OpenSpec strict、Golden 20/20、Ruff check/format、打包和 diff 检查；loopback 与 packaging 依赖安装的环境例外如实记录
- [x] 4.3 完成两轮最终自审与独立代码评审；修复 Task 4 复审确认的 2 项 Important 和 1 项 Minor，并重复受影响验证
- [x] 4.4 完成 build-stage preparation/handoff：准备归档输入，确认 `milestones/latest` 当前指向 `milestone_027.md`，并记录分支收尾选择；delta spec 同步、change 归档、最终里程碑状态和实际 branch finish 留给后续 Comet archive/branch gates

## 5. 最终独立评审修复

- [x] 5.1 添加 RED/GREEN 测试并修复 M25 派生产物在备份创建失败时可能删除既有文件的问题
- [x] 5.2 添加 RED/GREEN 集成测试，确保 CLI 与 REPL 的默认/显式 Single 路由均发出稳定 `collaboration.route` 审计事件
- [x] 5.3 重新执行受影响验证、完整基线和两轮最终自审，并同步验证报告、公开基线与里程碑证据

## 6. 最终路由审计一致性修复

- [x] 6.1 以 RED/GREEN 修复 CLI/REPL Single 路由复用实际 audit sink，并补齐 `/single <goal>` 帮助与补全合同
- [x] 6.2 在 Loop checkpoint 中持久化默认/显式来源，create/resume 审计复用冻结来源并兼容旧 checkpoint
- [x] 6.3 覆盖 CLI/HTTP 无模式为 default、显式 single/duo/triad 为 explicit，运行受影响测试、Ruff 与 diff 检查并完成两轮自审
