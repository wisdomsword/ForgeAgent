# M25 编程模式质量—成本评估验证报告

## 结论

PASS。实现、270 份真实终态证据、独立复算与公开文档符合 OpenSpec change、技术设计和实施计划；没有未解决的 CRITICAL、WARNING 或 SUGGESTION。

## 记分卡

| 维度 | 状态 | 证据 |
|---|---|---|
| 完整性 | PASS | OpenSpec tasks 16/16；delta spec 7/7 requirements、21/21 scenarios 有实现或测试证据 |
| 正确性 | PASS | 270/270 唯一 terminal raw；116 solved、154 failed；独立复算通过；M23 历史证据无差异 |
| 一致性 | PASS | 实现采用既定的向后兼容 harness 扩展、独立 M25 schema/根、双 route hash、严格完整聚合和中立报告 |

## 新鲜验证证据

- 离线构建：wheel 与 sdist 成功生成。
- 沙箱可执行全套回归：`2352 passed, 22 skipped`；排除 11 个需要 loopback socket 的 M16 黑盒测试与另行离线验证的 packaging 测试。
- M23/M25/packaging 聚焦回归：`126 passed`。
- Ruff：全库 check 通过，111 个文件 format check 通过。
- Golden：20/20 通过。
- OpenSpec 1.4.1 strict：`21 passed, 0 failed`。
- 真实证据安全、M23 byte lock 与公开文档测试：`2 passed, 63 deselected`。
- 独立复算：`INDEPENDENT_RECOMPUTE_OK runs=270`。
- `git diff --exit-code d7fa30526f829959102b5fb69b4778899d6b1f88 -- docs/evaluation/m23` 与 `git diff --check` 通过。

## 需求与场景映射

- 版本化协议、双模型固定字段、历史隔离：`docs/evaluation/m25/protocol.json`、`scripts/m23_mode_evaluation.py` 及协议/M23 byte-lock 测试。
- 270-run 排程、顺序平衡和安全续跑：M25 schedule、identity、resume 测试。
- runtime、checks、fixture integrity 与 artifacts 完成口径：raw 构造回归及独立复算的一致性校验。
- Duo/Triad 验收循环与 Single N/A：模式聚合和中立报告测试。
- tokens、调用、attempt、延迟和 usage 缺失：audit 投影、分层聚合和独立复算。
- 安全 raw、完整集合聚合和输出根边界：raw schema、完整性、路径逃逸与递归敏感信息扫描。
- 无自动排名报告：报告合同与公开 M25 文档。

## 已知环境边界

- 原始沙箱全量 pytest 中 11 个 M16 黑盒测试因沙箱禁止 loopback socket 失败，packaging 在线隔离构建因 DNS 失败；已分别由过滤后的全套回归、离线 packaging 测试和离线 wheel/sdist build 补证。
- `npx` 固定版本 OpenSpec 验证因沙箱 DNS 失败；使用本机已安装且版本为 1.4.1 的 `openspec validate --all --strict` 完成等价验证。
- 结果仅代表报告记录日期、本机环境、两条 provider route 与不可固定的服务端模型权重，不形成模式排名。

## 分支处理

验证阶段先保留 `codex/feature/20260727/m25-programming-mode-evaluation` 分支；最终收尾按用户明确要求将全部提交合并到 `main`，在合并后的 `main` 重新验证，并删除本地功能分支。未执行 push。

## 最终评估

所有检查通过，可以归档。
