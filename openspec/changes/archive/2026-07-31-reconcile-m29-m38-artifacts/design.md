## Context

M44 分支从较早的干净 Git 基线连续开发，代码已经包含 M29-M38 的能力，但这些里程碑的大量流程工件只存在于主工作区未提交内容中。直接复制整个主工作区会把旧借鉴清单、过期测试计数、无关 agent 配置和用户文件带入 M45；完全忽略又会让 ACTION_PLAN 已完成行无法追溯到里程碑、归档 change 和主规格。

本 change 是仓库证据恢复，不是运行时功能开发。主工作区只读，M45 worktree 是唯一写入目标。

## Goals / Non-Goals

**Goals:**

- 恢复 M29-M38 缺失的里程碑和 Comet/OpenSpec/Superpowers 生命周期链。
- 恢复当前代码已经实现但主规格缺失的 M29、M31、M32、M34 契约。
- 保留 M44/M45 较新的 borrowing、HTTP、MCP 和里程碑指针事实。
- 清除全部主规格的归档器 `Purpose: TBD`，并用离线测试防止回归。
- 产出来源、SHA、采纳/拒绝理由和验证结果可追溯的 M45 对账报告。

**Non-Goals:**

- 不复制主工作区 `.agent/`、`.agents/`、`.claude/`、`.codex/`、`skills-lock.json`、`work/` 或其他无关文件。
- 不用旧 M30 主规格覆盖 M45 修复后的 `mcp-progressive-disclosure`。
- 不用旧 M34/M43 借鉴清单覆盖 M44 当前基线。
- 不修改运行时代码、依赖、持久数据、HTTP listener 或发布自动化。

## Decisions

### 1. 使用明确白名单，不做目录级全量同步

恢复范围固定为：8 个缺失 milestone、10 个缺失 archive、20 个缺失 Superpowers 工件、`docs/agent-governance-gates.md`、`tests/test_governance_docs.py`，以及经当前 change delta 合并的 4 个缺失主规格和 `skills-runtime` 增量。每个来源文件在复制前后记录 SHA256。

替代方案“复制主工作区所有未跟踪文件”被拒绝，因为无法区分用户文件、旧基线和当前 M45 事实。

### 2. 当前分支事实优先于历史来源

若目标路径已存在，不自动覆盖。已知冲突中：M45 的 borrowing spec 已到 M44，优于主工作区 M34 版本；M45 的 MCP spec 包含真实 manager 修复，优于旧 M30 版本；M44 的 HTTP action approval spec 在主工作区尚不存在。历史 archive 可以恢复用于 provenance，但不能反向更新这些主规格。

### 3. 缺失规格通过本 change 的 delta 合并

不直接把 `openspec/specs/` 当普通文件复制。4 个缺失能力作为 ADDED delta、M34 的 `skills-runtime` 作为 MODIFIED delta，由当前 Comet archive 统一合并；这样 OpenSpec 能验证要求格式和归档来源。历史 archive 原样恢复，仅作为当时的生命周期证据。

### 4. 历史里程碑附加对账注记

M29-M38 的原始范围、裁决和测试计数保留，但追加统一 M45 注记：计数只证明当时快照；当前实现由 M45 全量门禁重新证明；开发分支 push 与已移除的 PyPI/tag/发布自动化目标不同。M30 额外指向 M45 的修复归档，说明 M44 集成时 manager 契约曾缺失且已修复。

### 5. Purpose 必须描述能力，不允许模板占位

离线测试扫描 `openspec/specs/*/spec.md`，拒绝 `TBD - created by archiving` 和 delta-only 顶层标题。Purpose 只写一至两句能力边界，不改变 requirements。

## Risks / Trade-offs

- **历史工件曾来自脏工作区。** → 只接受 `.comet.yaml` 同时满足 `phase: archive`、`verify_result: pass`、`archived: true` 的 archive，并用当前 tests/specs 重新验证。
- **旧文档与新事实冲突。** → 不覆盖已存在目标；对恢复 milestone 追加 M45 注记；对账报告列出拒绝项。
- **一次恢复文件较多。** → 先用失败的清单测试锁定精确路径，再分“证据复制、规格合并、Purpose 清理”三批提交。
- **Purpose 清理跨越早期里程碑。** → 只改 Purpose，不改 requirements；OpenSpec strict 和全量 pytest 防止语义漂移。

## Migration Plan

1. 新增生命周期清单测试并确认缺失路径、TBD 和断链导致失败。
2. 从只读主工作区按白名单恢复历史工件，记录 SHA 和冲突决策。
3. 通过 delta 恢复缺失主规格与 M34 `skills-runtime` 增量。
4. 填写所有主规格 Purpose，运行 governance、borrowing、skills、attention、collaboration 和全量门禁。
5. 归档本 change。失败时回滚本 change 提交即可；无运行时数据迁移。

## Open Questions

无。所有来源和冲突裁决都必须在实现前进入白名单；发现白名单外文件时拒绝复制并记录，而不是扩大范围。
