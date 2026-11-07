---
generated_from_state_version: 10
---

# 验证

## 当前结果

- 结果: **已归档**
- 验证情况: **已完成检查，验证结果已确认**
- 目标周期: 2
- 迭代: 1
- 验证器尝试次数: 1
- 完成时间: 2026-10-28T11:18:43.160Z
- 摘要: 独立核查候选 a92165b：兼容路径实现与 brief/spec 逐条一致（识别规则 format_version==1 且无 trigger 但有 description、trigger 派生算法、正文→Steps、合成节、native >32KB 重加强制、compat 256KB 上限、raw digest 绑完整磁盘内容、symlink/掩码/信任确认由既有层保留）；`pytest tests/test_skills.py` 52 passed；A1-A6 各有具体测试对应。M52 全部验收通过。

## 验收

| 编号 | 结果 | 来源 | 验收项 | 原因 |
| --- | --- | --- | --- | --- |
| A1 | passed | brief.md | A1：标准 Skills SDK 技能（`name + description + 自由正文`）经 `SkillRegistry` 加载；trigger 由 description 派生（单行、≤240 字符、无换行），正文成为 Steps，Failure Branches/Completion Criteria 为合成文本。 | 标准技能经兼容路径加载：trigger 由 description 派生（≤240 字符、单行、无换行），正文成为 Steps，Failure Branches/Completion Criteria 为合成文本；test_registry_loads_standard_sdk_skill_in_compat_mode + test_registry_standard_skill_trigger_derived_bounded_and_single_line 验证 |
| A2 | passed | brief.md | A2：native 严格格式技能仍按原路径加载；native 非法情形（未知 key、多行 trigger、trigger+description 混合）仍拒绝。 | native 严格路径未改动；未知 front matter key、多行 trigger、trigger+description 混合均仍拒绝；test_registry_trigger_and_description_hybrid_rejected + test_registry_ignores_invalid_document_with_bounded_diagnostic 验证 |
| A3 | passed | brief.md | A3：native 技能磁盘大小 >32KB 仍拒绝；兼容技能正文截断到 ≤32KB（内存有界）。 | native 磁盘 >32KB 仍拒绝（test_registry_enforces_raw_skill_file_size_boundary）；兼容技能正文截断到 ≤32KB 内存有界（test_registry_standard_skill_body_truncated_to_memory_bound） |
| A4 | passed | brief.md | A4：兼容技能磁盘 >256KB、空正文、缺 description、空白 description、名称不匹配均拒绝。 | 兼容技能磁盘 >256KB、空正文、缺 description、空白 description、名称不匹配均拒绝（test_registry_rejects_invalid_standard_skills，5 参数化） |
| A5 | passed | brief.md | A5：兼容技能 raw digest 绑定完整磁盘内容：32KB 截断点之后的变更（不改变截断后正文）仍触发信任重新确认。 | raw digest 绑定完整磁盘内容：32KB 截断点之后的变更（不改变截断后正文）仍触发信任重新确认（test_registry_standard_skill_raw_digest_binds_full_on_disk_content） |
| A6 | passed | brief.md | A6：兼容技能经完整 `SkillRegistry.load` 管线加载（catalog、信任确认、read 各节、digest 确定性），与 user 侧 native 技能共存。 | 完整 SkillRegistry.load 管线（catalog、信任确认、read 各节、digest 确定性）+ 与 user 侧 native 技能共存；test_registry_loads_standard_sdk_skill_in_compat_mode + test_registry_standard_skill_raw_digest_binds_full_on_disk_content + test_registry_standard_skill_digest_stable_when_unchanged 验证 |

## 检查

_没有记录 Runtime 检查。_

### Builder 报告的证据

以下为 Builder 报告，不等同于 Runtime 检查凭据或独立验收结果。

- ruff check src/forgeagent/skills.py tests/test_skills.py: passed — All checks passed
- ruff format --check src/forgeagent/skills.py tests/test_skills.py: passed — 2 files already formatted
- pytest tests/test_skills.py: passed — 52 passed in 0.60s
- mypy src/forgeagent/skills.py (types-PyYAML 存根): passed — skills.py 无错误；101 个错误均为其它文件既有（loop/collaboration/http_*）
- pytest (full suite): failed — 3071 passed, 10 skipped, 2 failed — 2 个失败均为既有 m23/m25（history-rewrite 哈希失效），已在干净 HEAD 实证复现，非 M52 引入；见 known_limits 与 brief 验证预期
- 已知限制: 全量套件存在 2 个既有失败（tests/test_m23_mode_evaluation.py、tests/test_m25_mode_evaluation.py）：引用里程碑历史重写前已失效的提交哈希（c20c0948/8e82fdd4/9e1e5c58），git ls-tree 退出 128；已在干净 HEAD 实证复现，与 M52 无关。已在 brief.md『验证预期』披露，Verifier 不应计入 M52 验收。

## 阻塞项

_无。_

## 风险与跳过的工作

- 全量套件存在 2 个既有失败（tests/test_m23_mode_evaluation.py、tests/test_m25_mode_evaluation.py）：引用里程碑历史重写前已失效的提交哈希（c20c0948/8e82fdd4/9e1e5c58），git ls-tree 退出 128；已在干净 HEAD 实证复现，与 M52 无关；brief.md『验证预期』已披露，不计入 M52 验收。

## 之前的迭代

| 目标周期 | 迭代 | 尝试 | 结果 | 未解决项 | 摘要 | 完成时间 |
| ---: | ---: | ---: | --- | --- | --- | --- |
| 1 | 0 | 0 | recovery | — | Native Shape artifacts changed | 2026-10-28T09:42:09.462Z |
| 2 | 1 | 1 | pass | — | 独立核查候选 a92165b：兼容路径实现与 brief/spec 逐条一致（识别规则 format_version==1 且无 trigger 但有 description、trigger 派生算法、正文→Steps、合成节、native >32KB 重加强制、compat 256KB 上限、raw digest 绑完整磁盘内容、symlink/掩码/信任确认由既有层保留）；`pytest tests/test_skills.py` 52 passed；A1-A6 各有具体测试对应。M52 全部验收通过。 | 2026-10-28T11:18:43.160Z |



## 结论

独立核查候选 a92165b：兼容路径实现与 brief/spec 逐条一致（识别规则 format_version==1 且无 trigger 但有 description、trigger 派生算法、正文→Steps、合成节、native >32KB 重加强制、compat 256KB 上限、raw digest 绑完整磁盘内容、symlink/掩码/信任确认由既有层保留）；`pytest tests/test_skills.py` 52 passed；A1-A6 各有具体测试对应。M52 全部验收通过。
