# M23 Single/Duo/Triad 质量—成本评估验证报告

- Change: `m23-collaboration-mode-evaluation`
- 验证模式: full
- 基线: `da41726888d9243583a5ce8e240604da6c5880eb`
- 正式证据提交: `27cdd2f`
- 协议: `forgeagent.m23.mode-evaluation/v2`

## 结论

| 维度 | 状态 | 证据 |
| --- | --- | --- |
| 完整性 | PASS | OpenSpec tasks 13/13；requirements 7/7；scenarios 16/16；正式 raw 27/27 |
| 正确性 | PASS | 协议、排程、独立检查、N/A、usage、聚合和中立报告均有离线合同及正式证据 |
| 一致性 | PASS | proposal、OpenSpec design、技术设计、delta spec、实现和公开文档一致 |

未发现 CRITICAL、WARNING 或 SUGGESTION。实现与规格一致，可以归档。

## Requirement 映射

| Requirement | 实现 | 测试 | 正式证据 |
| --- | --- | --- | --- |
| Versioned and fixed evaluation protocol | `scripts/m23_mode_evaluation.py:339`、`:345`；`docs/evaluation/m23/protocol.json` | `tests/test_m23_mode_evaluation.py:34` 及严格协议参数化测试 | protocol hash 单一；27 个 RunSpec 完整 |
| Repeated and order-balanced mode execution | `scripts/m23_mode_evaluation.py:345` | `tests/test_m23_mode_evaluation.py:34` | 每模式 9 份，每个 task/mode 3 份 |
| Independent task completion checks | `scripts/m23_mode_evaluation.py:491`、`:792` | `tests/test_m23_mode_evaluation.py:339`、`:368`、`:404` | 27 个 `fixture-integrity` 全部通过；一个真实外部 pytest 失败被保留 |
| Applicable acceptance-loop metrics | raw 构建和 mode 投影位于 `scripts/m23_mode_evaluation.py` | `tests/test_m23_mode_evaluation.py:240`、`:647` | Single 为 N/A；Duo/Triad 首次验收 8/9、9/9 |
| Complete quality and cost telemetry | audit 投影及 `scripts/m23_mode_evaluation.py:985` | `tests/test_m23_mode_evaluation.py:159` 及 usage 缺失合同 | 279 次逻辑调用，usage 缺失 0/279，四类 token 和延迟均已记录 |
| Safe raw records and reproducible aggregation | `scripts/m23_mode_evaluation.py:859`、`:985`、`:1133`、`:1254` | 原子写入、混合证据、路径逃逸测试；`:804`、`:819` | 独立复算与正式 summary/report 一致；无敏感字段或绝对路径 |
| Neutral descriptive report | `scripts/m23_mode_evaluation.py:1044` | `tests/test_m23_mode_evaluation.py:717`、`:1007` | 报告无 winner/ranking/recommendation/superiority，并明确不自动宣称 Triad 优于 Single |

16 个规格场景均由上述合同测试覆盖；真实证据覆盖完整调度、内部完成与外部失败分离、Single N/A、
usage 完整性、raw 安全边界、幂等复算和中立报告。设计文档
`docs/superpowers/specs/2026-07-27-m23-collaboration-mode-evaluation-design.md` 存在，frontmatter
链接当前 change，并声明 OpenSpec 为 canonical spec。

## 真实证据审计

- 环境绑定 commit `14576d9a23d202daacb28dbfbeefda631078b21c`，`tracked_dirty=false`。
- protocol SHA-256 为 `bb6a9aaded0dee6a3599d9b004e17eeb9543c76cb3c79c284e960786e36383e4`；
  environment SHA-256 为 `dc1b5ff1f207971862677f3692a3ad0821ff6b6dd53b885d7f5be2c0b59b6f76`。
- Single/Duo/Triad solved 为 5/9、8/9、9/9；该结果仅为小样本描述性证据。
- 逻辑模型调用为 76、91、112；input token 为 227727、129869、193441；output token 为
  36713、41860、66560；cached/reasoning token 均为 0。
- 平均端到端延迟为 48.93、63.54、79.30 秒；usage 缺失为 0/279。
- raw 中无 `prompt`、`reply`、credential、检查正文或绝对路径；summary/report 无自动排名字段。
- v1 批次已移入 `2026-07-27-haiku-4-5-invalid-8dbebff` 并附 `INVALID.md`，不参与 v2 聚合。

## Review 修复闭环

最终代码评审发现 v1 restricted check worker 内嵌套进程、immutable fixture 未独立验收和输出根
逃逸三个 IMPORTANT 问题。每项均先加入失败回归，再以 v2 协议最小修复；v1 完成率被撤回并保留
失效审计。修复后 CSV/events 候选检查在受限 worker 同进程执行，所有任务追加 fixture 字节检查，
run/aggregate 共用规范化输出根校验。未修改产品协作运行时、CLI、模型注册或 credential 路径。

## 质量门禁

- M23 专项: `53 passed`
- 全量 pytest: `2305 passed, 10 skipped`
- Golden offline: `20/20`
- Ruff format/check: PASS
- wheel/sdist build: PASS
- OpenSpec strict: `19/19`
- `git diff --check`: PASS

Comet 无法为 Python/uv 项目自动推断 build 命令；本报告记录的 `uv build` 已真实退出 0，build
guard 使用一次性 `COMET_SKIP_BUILD=1` 消费这份手动构建证据，未修改持久环境或项目配置。

## 保留限制

样本只包含三个固定任务、每种组合三次重复、一个模型 ID、一个 provider 路由和本机环境；服务端
权重版本无法由本地独立固定。结果不自动宣称 Triad 优于 Single，也不据此作产品决策。
