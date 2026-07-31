# M45 M29-M38 生命周期工件对账报告

日期：2026-08-01  
变更：`reconcile-m29-m38-artifacts`  
基线：M44 集成提交 `8513bef069ef75ec7b9959a3112e0863722239a0`  
工作分支：`feature/20260801/m45-baseline-reconciliation`

## 结论

M29-M38 的开发、验证和归档工件此前没有完整进入当前基线，导致续接导航、审计追溯和 OpenSpec 主规格状态不完整。本变更只恢复已经在来源工作区存在、且对应 Comet 状态为 `phase: archive`、`verify_result: pass`、`archived: true` 的历史证据；不恢复任何旧实现、不覆盖 M44/M45 当前规范、不创建发布 change，也不恢复 PyPI 目标。

恢复后，历史工件作为不可执行的证据层存在；当前执行基线仍由 `ACTION_PLAN.md`、`milestones/latest` 和当前 HEAD 决定。历史里程碑均追加 `M45 对账注记`，明确原始测试计数只对应历史快照。

## 白名单与裁决

### 采纳

- `milestones/milestone_{029,030,031,032,035,036,037,038}.md`：恢复 8 个缺失的里程碑续接与验收记录。
- 10 个已验证 archive：`2026-07-30-align-borrowing-roadmap-baseline`、`2026-07-30-attention-state-projection`、`2026-07-30-mcp-progressive-disclosure`、`2026-07-30-prompt-memory-rewrite-governance`、`2026-07-30-runtime-skill-exit-contract`、`2026-07-30-structured-collaboration-handoff`、`2026-07-31-align-http-trigger-next-steps`、`2026-07-31-document-http-action-approval-trigger`、`2026-07-31-retire-pypi-publication-goal`、`2026-07-31-sync-borrowing-review-m34-baseline`。
- 5 个历史 Superpowers plan、10 个 verify report、5 个 design spec，以及 `docs/agent-governance-gates.md` 和 `tests/test_governance_docs.py`。
- 4 个缺失能力的 active delta source：`agent-governance-gates`、`attention-state-protocol`、`runtime-skill-exit-contract`、`structured-collaboration-handoff`；另保留 M34 `skills-runtime` 增量，待本变更归档时同步主规格。

### 明确拒绝

- 不恢复 `skills-lock.json`：来源为用户未跟踪文件，不属于 M29-M38 已验证生命周期证据。
- 不恢复 `.agent/`、`.agents/`、`.claude/`、`.codex/` 中的工作区内容或 `何为Harness.html`：它们是会话/草稿资产，不是归档工件。
- 不恢复 `milestones/milestone_033.md`、`milestones/milestone_034.md`：当前工作区已存在，避免重复来源；不覆盖 M44 `borrowing-review-baseline`、`http-action-approvals` 和 M45 修复后的 `mcp-progressive-disclosure`。
- 不创建或恢复 `openspec/changes/publish-v0-1-0`；包索引发布、正式 tag 和发布自动化仍不在路线图。

## 来源摘要

以下 SHA256 来自来源工作区 `/Users/admin/Code/llm-agent/ForgeAgent`，用于确认恢复前的输入；archive 行是按相对文件名排序后的 tree manifest 摘要。

```text
c652b53a86b72425a9f24c99d6a6af4f7c226e7ec2276bbcb4db87916cf46a18  milestones/milestone_029.md
f363d548af57218360758e20db9611517d1e1c407e6defd7758a48b54e878c1d  milestones/milestone_030.md
3afe322ebb4c155e233b414d159c2bb5f95d88ad4e8abf9af71556ca90a220c4  milestones/milestone_031.md
66a102773900a99fa0163cbfecfcd73d4d625ff377cc41176b0f76009040eac0  milestones/milestone_032.md
bbe828c7672f6553cd6a52b1531622e0e2cea7a2e0679a97f3918fe32937075d  milestones/milestone_035.md
34a4458a5f4f4c866f0b0929d8dd8ca336b26d53acb5923afa53ea4ae10973c4  milestones/milestone_036.md
890f7b6c4acab5558038a6ac0aecd5f8054791a75604828e81b427c2a36edf50  milestones/milestone_037.md
0d9159d268ac4058dc08d32d8a5e4d82a4943148e27f452ae7ddc94f044f876c  milestones/milestone_038.md
9b7b148f7b4e41d5e9397e207c49355c02206d6eb3a6622ef1fe25fafb415d5e  docs/superpowers/plans/2026-07-30-attention-state-projection.md
28a77cfd9b33b3fbc61490a898ae46ab7bc13cead8d7324aeae525e1ca29c4e6  docs/superpowers/plans/2026-07-30-mcp-progressive-disclosure.md
18a79928d721a24cc2d2fd2c050a668243b0ad80aa89d11a7c85b7a12123d31b  docs/superpowers/plans/2026-07-30-prompt-memory-rewrite-governance.md
8242579e91f5c7845a85ccd6f81190f5edbf3c85352a0b1a432be33bcb90d35d  docs/superpowers/plans/2026-07-30-runtime-skill-exit-contract.md
50673701838437efa662f6e7eee9fca37eafbad31123e3833eb0d4c48ad9c9d4  docs/superpowers/plans/2026-07-30-structured-collaboration-handoff.md
67bc7a17479253b5d71567bc2c0479b2aba244b2f61c16ef54458becd2311d20  docs/superpowers/reports/2026-07-30-align-borrowing-roadmap-baseline-verify.md
ff1d8e1dedf3648bd15e84ff8fc1a959cf549dcf7131ee7e165b8907717f15f1  docs/superpowers/reports/2026-07-30-attention-state-projection-verify.md
59ba2f8467ebd2b4a75569863aa83b0c071ea0dbd99ca0fbd6f87a39392e04d4  docs/superpowers/reports/2026-07-30-mcp-progressive-disclosure-verify.md
dfc41dd756b53d9583d1b02c9e2580856a267acce8d2818e927a0288d7d28c5b  docs/superpowers/reports/2026-07-30-prompt-memory-rewrite-governance-verify.md
726b045d136268867fafdf2b9139b4480a89e3eaf1077dd13607972e74abab4d  docs/superpowers/reports/2026-07-30-runtime-skill-exit-contract-verify.md
777d11311db17889cab4dc5a887a248ec905446011d4bd9077b8cb4e86c137ad  docs/superpowers/reports/2026-07-30-structured-collaboration-handoff-verify.md
55421c12750eb683ea76e877e045633ad9ffc2a4601ed75db8f42a491792e4f5  docs/superpowers/reports/2026-07-31-align-http-trigger-next-steps-verify.md
0236ffb01e8bb7cda57ae20fcf585b1351c40c7d4a56cbb9b76ebd51848027fd  docs/superpowers/reports/2026-07-31-document-http-action-approval-trigger-verify.md
3ca6ea09faef11c023704157d2943b80d30d5682f20cb4505be2376a87c06160  docs/superpowers/reports/2026-07-31-retire-pypi-publication-goal-verify.md
0829cc0a7818d509ff31143f4a915c6af7aa214c9f70b59d1a713bbb69031e3c  docs/superpowers/reports/2026-07-31-sync-borrowing-review-m34-baseline-verify.md
5a018170d4122717b71189f45b497dc1c393005479fb7558d247462881e5c6ac  docs/superpowers/specs/2026-07-30-attention-state-projection-design.md
621257648194215cc5cfd912213ffbe6b08d12d7919e691df88bb3a4dd9ba477  docs/superpowers/specs/2026-07-30-mcp-progressive-disclosure-design.md
c0406b69f80e7aa9a639c7c6b32146c5c6e481d55e1e023425308cf81fe2b148  docs/superpowers/specs/2026-07-30-prompt-memory-rewrite-governance-design.md
707acd3fc77218e64d84927ebef97a39440f68dfef95539787990a175952a19a  docs/superpowers/specs/2026-07-30-runtime-skill-exit-contract-design.md
47f54438f7242f159ea057569de66e23a6fd10311877066031f91a050b79b4ee  docs/superpowers/specs/2026-07-30-structured-collaboration-handoff-design.md
96ccec51799aad06f8573a0f9810083d4a59355cd3c62006baa01a3ae454f106  docs/agent-governance-gates.md
6632db3cfb882583ee06167b039d8ddd1132544e35ac32f38ef3282e7032bbde  tests/test_governance_docs.py
37ecc9b17b6684f04f4da9c9a685b2e2d583c71f3d353292a6935f899cdc792a  openspec/changes/archive/2026-07-30-align-borrowing-roadmap-baseline (tree manifest)
9c119b5d5df8a6eca8a48b65d085ac5e2d45471b4e1da0ee338a371c4d9e7204  openspec/changes/archive/2026-07-30-attention-state-projection (tree manifest)
653af2ceb2fc42b72b124935137d76f24e46e44bb0e1337117780f31f003a3ea  openspec/changes/archive/2026-07-30-mcp-progressive-disclosure (tree manifest)
37039f0f4c1dd45b9bf09e0885b08082f103646c3f079c999bcdf1dd528d2e49  openspec/changes/archive/2026-07-30-prompt-memory-rewrite-governance (tree manifest)
ff97af8434b70f97052aea5300c36a7375888978ef43b5dcfdfe6f285aa8976b  openspec/changes/archive/2026-07-30-runtime-skill-exit-contract (tree manifest)
a608b0f26d55ddb5c2f33919d536778bd6c6cd2eb974588233062ab1f8f0a9a9  openspec/changes/archive/2026-07-30-structured-collaboration-handoff (tree manifest)
aa79e856fc24689c67bea60f5b20e6683587c9f3f2105e3499950e8b7bc3f7fc  openspec/changes/archive/2026-07-31-align-http-trigger-next-steps (tree manifest)
4c953539222d84f039f584ae2f1b80f5e8fee4c284c47b2201085708fd077a6b  openspec/changes/archive/2026-07-31-document-http-action-approval-trigger (tree manifest)
bb26172cedd54c9c8821f21b0a1d7af9cfb4bb82ac2d9126a14fb8668b13694f  openspec/changes/archive/2026-07-31-retire-pypi-publication-goal (tree manifest)
467a5cdeaa9b9a44327933f2ca207ceaeab68e5b750369a3daba87a6a731c7e4  openspec/changes/archive/2026-07-31-sync-borrowing-review-m34-baseline (tree manifest)
```

## 验证计划与当前状态

- RED 已验证：`tests/test_repository_lifecycle.py` 在恢复前为 `4 failed, 2 passed`，失败原因正是缺失白名单文件、缺少 M45 注记和主规格占位 Purpose。
- 恢复后必须通过 lifecycle、治理、borrowing、skills、attention、collaboration 聚焦回归，再执行全量 `pytest`、Ruff、format、`git diff --check`、`uv build` 和 OpenSpec strict。
- 不执行 PyPI 上传、正式 tag、发布自动化；普通开发分支 push 只有在用户明确授权后才可进行。
