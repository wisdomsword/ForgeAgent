# advertise-built-in-tools 验证报告

## 结论

PASS。固定协议已向无自定义 identity 的模型公开全部默认内置工具；M16 真实模型
黑盒确认空 HTTP allowlist 拒绝目标 FileWrite，精确
file/m16-allowlist.txt allowlist 预批准并执行同一 FileWrite。无 Critical、
Warning 或未接受偏差。

## 完整性

| 检查 | 结果 | 证据 |
| --- | --- | --- |
| OpenSpec tasks | PASS | 4/4 已完成 |
| Delta requirement | PASS | runtime-identity 1/1 已实现 |
| Delta scenarios | PASS | 3/3 有实现与测试证据 |
| OpenSpec 严格校验 | PASS | openspec validate advertise-built-in-tools --strict |

## 正确性

- src/forgeagent/res/prompts/protocol.md 列出 Exec、Edit、Survey、WebFetch、
  FileRead、FileWrite 和 FileList，并规定 direct tool 匹配时优先使用对应工具。
- tests/test_identity.py 断言默认 prompt 包含全部工具名、FileWrite 精确 marker 和
  direct-tool 优先规则。
- scripts/m16-filewrite-allowlist-blackbox.sh 以 operation-linked
  confirmation/tool 事件和文件状态为权威证据；额外成功工具或额外 artifact 保持
  INCONCLUSIVE，额外失败且无 artifact 的操作不覆盖目标 FileWrite 证据。
- tests/test_m16_filewrite_allowlist_blackbox.py 覆盖失败工具无 artifact、失败工具
  有 artifact、额外成功工具、错误 allowlist decision、token 泄漏、audit degraded、
  超时和进程清理。

## 自动验证

- TDD RED：目标 FileWrite 正确后追加失败 Exec，旧脚本返回 2；
  allowed 阶段失败工具留下 unexpected.txt 时，旧脚本误返回 0。
- M16 脚本专项：12 passed。
- 最终全量：1249 passed, 11 skipped。
- Bash：bash -n 通过。
- Ruff：check 通过，2 个测试文件已格式化。
- git diff --check：通过。

## 真实模型黑盒

模型：glm-5.2。

Evidence：
/tmp/forgeagent-m16-filewrite.uRHXVG

| 阶段 | Task | Decision | Tool result | 文件 |
| --- | --- | --- | --- | --- |
| empty allowlist | 673a0c1e9bde4f48a3235f3d42abe2f1 | denied | FileWrite failed | 无目标文件 |
| exact allowlist | 24a5ea012f56491bbbcdae89583a8e85 | preapproved | FileWrite success | 仅 m16-allowlist.txt，内容匹配 |

两个阶段的 decision 与 FileWrite tool event 均共享 operation_id；审计文件权限均为
0600，audit_degraded=false。模型在两个阶段后续均尝试过一次失败 Exec，但未产生
额外 artifact，因此不影响 FileWrite allowlist 合同。

## 一致性与安全

- 实现遵循 OpenSpec design：静态稳定 prompt、无新依赖、无 registry/parser/API/
  allowlist 变化。
- 无硬编码凭据、无新增网络或文件权限面。
- Claude 的本地 ANTHROPIC_BASE_URL 指向第三方 sg.pomoai.xyz；该网关注入了另一个
  Agent 系统上下文并拒绝 ForgeAgent 协议。该 endpoint 不满足调用方 system 语义，
  因此不作为 M16 合同失败；标准 Chat Completions 路由上的 glm-5.2 已完成真实验收。
- review_mode=off，按 hotfix 配置跳过自动代码审查；全量测试、安全检查与
  OpenSpec 完整验证未跳过。

## OpenSpec 对照

| 维度 | 状态 |
| --- | --- |
| Completeness | 4/4 tasks，1/1 requirement |
| Correctness | 3/3 scenarios，真实两阶段黑盒通过 |
| Coherence | 实现与 proposal/design/delta spec 一致 |

All checks passed. Ready for branch handling and archive confirmation.
