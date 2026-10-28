# 标准 Skills SDK 兼容能力规格

## 概述

ForgeAgent 的 skill 发现与加载（`src/forgeagent/skills.py`）在 native 严格格式之外，增加一条**标准 Skills SDK 兼容路径**。兼容路径接受标准 Skills SDK 技能——front matter 为 `name` + `description`、正文为自由 Markdown 的技能——并把它映射到 ForgeAgent 内部统一表示。兼容路径在磁盘文件仍超过 native 32KB 上限时允许加载（上限 256KB），但加载后的内存正文仍被截断到 32KB，以保持内存有界。全部既有安全属性（名称格式、symlink 包含、secret 掩码、目录信任确认、raw/effective digest 绑定）在兼容路径下保持有效。

## 兼容识别规则

- 一项技能当且仅当 front matter **不含 `trigger`** 且 **含 `description`**（`format_version` 缺省或为 1）时，被识别为标准 Skills SDK 技能并走兼容路径。
- front matter 含 `trigger` 的技能走既有 native 严格路径，行为不变。
- front matter 同时含 `trigger` 与 `description` 的技能被拒绝（`invalid format`）。
- 兼容技能的名称必须匹配其发现目录名且符合 `^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$`。

## 映射规则

- **trigger**：由 `description` 派生——折叠空白为单个空格、去除首尾空白，结果限制为单行 ≤240 字符（超长时在最近空格处截断，无空格则硬截断）。
- **Steps**：技能正文（front matter 之后的全部内容）经去首尾空白后作为 Steps。
- **Failure Branches**：合成固定文本（声明该技能未声明显式失败分支，应观察工具错误与用户所述结果）。
- **Completion Criteria**：合成固定文本（步骤遵循且用户确认目标达成即完成）。

## 有界与安全

- 磁盘上限：兼容技能文件 >256KB 被拒绝（`invalid format`）。
- 内存正文上限：Steps 被截断到 ≤32KB（按 UTF-8 字节，截断在完整字符边界）。
- 名称、trigger、Steps 均经 `mask_secrets` 掩码；合成节不含用户内容。
- symlink 包含检查（由发现层在解析前执行）对兼容技能同样生效。
- raw digest 绑定**完整磁盘内容**（含 32KB 截断点之后的字节）；effective digest 绑定截断后的渲染表示。截断点之后的磁盘变更仍使 raw digest 改变并触发信任重新确认。

## 验收场景

### Scenario: 标准技能经兼容路径加载

Given 一项标准 Skills SDK 技能（front matter `name` + `description`、自由正文）

When `SkillRegistry` 发现并解析该技能

Then 该技能被加载，trigger 由 description 派生（单行、≤240 字符、无换行），正文成为 Steps，Failure Branches 与 Completion Criteria 为合成文本。

验收：A1

### Scenario: native 严格格式路径不变

Given 一项 native 技能（front matter `name` + `trigger`、含 `## Steps`/`## Failure Branches`/`## Completion Criteria`）

When `SkillRegistry` 发现并解析该技能

Then 该技能按 native 严格路径加载；native 非法情形（未知 front matter key、多行 trigger、同时含 trigger 与 description）仍被拒绝。

验收：A2

### Scenario: 磁盘与内存大小边界

Given 一项 native 技能磁盘大小 >32KB，或一项兼容技能

When `SkillRegistry` 解析该技能

Then native >32KB 被拒绝；兼容技能正文被截断到 ≤32KB（内存有界）。

验收：A3

### Scenario: 非法兼容技能拒绝

Given 一项兼容技能磁盘 >256KB、正文为空、缺 description、空白 description，或其 front matter 名称不匹配发现目录名

When `SkillRegistry` 解析该技能

Then 该技能被拒绝（`invalid format` 或 `invalid name`）。

验收：A4

### Scenario: raw digest 绑定完整磁盘内容

Given 一项已确认信任的兼容技能，其正文在 32KB 截断点之后有一个唯一标记

When 仅修改该标记（不改变截断后的正文）

Then raw digest 改变，信任记录触发重新确认。

验收：A5

### Scenario: 兼容技能经完整管线加载

Given 一项兼容技能作为 project skill，与一项 user 侧 native 技能并存

When `SkillRegistry.load` 执行完整管线（发现、信任确认、catalog、read、digest）

Then 兼容技能出现在 catalog、`read` 各节可用、信任记录写入、二次加载（内容不变）不重新提示、与 user 侧 native 技能共存。

验收：A6
