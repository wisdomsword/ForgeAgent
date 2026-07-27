## 1. 固定评估合同

- [x] 1.1 新增版本化 `protocol.json`，固定 3 个任务、3 次重复、轮换模式顺序、模型、生成参数、环境和产物检查
- [x] 1.2 新增离线合同测试，覆盖协议完整性、27 次排程、N/A 语义、usage 缺失和中立报告约束

## 2. 独立评估 Harness

- [x] 2.1 实现协议校验、环境指纹、隔离工作区和固定任务夹具初始化
- [x] 2.2 复用公开 Task/CollaborationRunner 运行 Single/Duo/Triad，不修改协作运行时或 credential 路径
- [x] 2.3 实现安全 audit 采集、外部产物检查、指标口径和单次原始 JSON 原子写入
- [x] 2.4 实现从原始记录复算 `summary.json` 和中立 `report.md` 的聚合器
- [x] 2.5 修复受限检查嵌套进程、immutable fixture 验收和 run/aggregate 输出根边界

## 3. M23 真实评估证据

- [x] 3.1 使用 v2 协议执行模型/环境 preflight，并运行完整 3×3×3 固定调度
- [x] 3.2 保存 27 份有效原始机器记录、协议/环境清单、聚合 JSON 和人工报告
- [x] 3.3 核对聚合分母、失败/缺失语义、敏感信息排除和“不自动宣称 Triad 优于 Single”约束

## 4. 文档与验证

- [x] 4.1 更新 README、ACTION_PLAN 和 M23 里程碑，区分描述性证据与产品结论
- [x] 4.2 运行 ruff、目标/全量 pytest、OpenSpec strict，并进入 Comet verify
- [x] 4.3 完成两轮自我评审，立即修复并复验所有发现
