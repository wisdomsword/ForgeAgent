---
role: technical-design
status: proposed
---

# M19 本地确定性人类验收设计

## 目标

提供一个不需要 API Key、不访问网络、不污染真实用户配置的一键验收入口，让人类通过
真实 TTY 直接验证 M19 最关键的可观察行为：项目 Skill 信任、渐进加载、`/reload`
快照替换、斜杠指令动态候选和当前会话方向键历史。

唯一入口：

```bash
uv run python scripts/m19-skills-human-smoke.py
```

## 范围边界

验收脚本使用生产 `repl()`、`SkillRegistry`、Task/Step、协议解析和 prompt-toolkit
输入路径，只把真实模型客户端替换为项目已有的 `MockClient` 等价脚本客户端。

明确不做：

- 不启动本地 HTTP 模型服务，不验证 OpenAI/Anthropic SDK 传输层。
- 不读取、覆盖或输出真实 `~/.forgeagent` 配置及 API Key。
- 不增加 ForgeAgent 产品命令、测试专用产品分支或持久 REPL 历史。
- 不自动伪造斜杠菜单与方向键结论；这两项必须由人类观察后确认。

## 架构

### 隔离夹具

脚本在系统临时目录创建独立 HOME 和项目根，进入临时项目后再启动 REPL。夹具包含：

- 用户级 `review-python` Skill，带 `USER_SKILL` marker。
- 同名项目级 Skill V1，带 `PROJECT_SKILL_V1` marker。
- 运行过程中写入的项目级 Skill V2，带 `PROJECT_SKILL_V2` marker。

退出时无论成功、失败或 Ctrl-C 都清理临时目录。真实 HOME 仅保存在进程内用于恢复，
不写入任何内容。

### 确定性客户端

每个普通目标创建一个两轮脚本客户端：

1. 第一轮返回只读 `Skill(name="review-python")` ToolCall。
2. 第二轮检查反馈消息中是否出现当前任务预期的 marker，再返回完成状态和明确的
   `PASS progressive loading: <marker>`；缺少 marker 时返回失败状态并记录原因。

第一次普通任务创建客户端时，脚本在 Task 已持有 V1 快照之后把磁盘 Skill 改为 V2。
因此第一次任务必须仍看到 V1；只有用户执行 `/reload`、重新确认摘要并运行第二个任务
后，才允许看到 V2。这同时验证快照不可变性和 reload 替换语义。

### 人类交互步骤

脚本启动前打印编号清单，REPL 中由人类完成：

1. 首次项目 Skill 确认输入 `y`。
2. 在同一个提示符依次键入 `/`、`m`，观察候选逐字符过滤；退格回 `/` 后键入 `re`
   再观察一次。期间不要回车；清空输入后执行 `/help`。
3. 在新提示符按上键回放 `/help`，再按下键回到空输入；不要回车执行回放内容。
4. 输入普通目标 `review first snapshot`，观察 V1 渐进加载 PASS。
5. 输入 `/reload`，对变化后的项目 Skill 再次输入 `y`。
6. 输入 `review reloaded snapshot`，观察 V2 渐进加载 PASS。
7. 输入 `quit` 退出。

REPL 退出后，脚本分别询问斜杠候选和方向键历史是否符合观察；默认答案为否，防止直接
回车误报成功。

## 自动判定

脚本最终仅在以下条件全部成立时退出码为 0：

- 第一项普通任务反馈包含 `PROJECT_SKILL_V1`。
- 第二项普通任务反馈包含 `PROJECT_SKILL_V2`。
- 两个任务都通过真实 Skill ToolCall → feedback → completed 两轮链路。
- 临时 HOME 中生成了 `skills-trust.json`，且 reload 后批准记录与 V2 内容匹配。
- 人类明确确认斜杠动态候选通过。
- 人类明确确认上下键历史通过。

任一条件失败时输出逐项 PASS/FAIL、建议重试步骤并以非零码退出；不使用笼统异常代替
验收结论。

## 错误处理

- 非 TTY 启动：立即报错，说明该验收必须在交互终端运行。
- 缺少 uv 环境或依赖：由一键命令原样返回错误，不尝试联网安装。
- Mock 脚本轮次异常、Skill 未读到或信任文件不可用：记录对应检查失败，仍恢复 HOME、
  工作目录并清理夹具。
- Ctrl-C：以取消状态退出，不写真实配置。

## 文件与文档

- 新增 `scripts/m19-skills-human-smoke.py`：夹具、确定性客户端、真实 REPL 驱动和汇总。
- 更新 `README.md` Skills 小节：增加一键命令、适用范围和“必须真实 TTY”说明。

## 验证

实现后至少执行：

- `uv run ruff check scripts/m19-skills-human-smoke.py`
- `uv run ruff format --check scripts/m19-skills-human-smoke.py`
- 在真实 PTY 中完整走完清单并得到总结果 `PASS`、退出码 0。
- 再走一个拒绝或遗漏确认的失败分支，证明最终退出码非零且临时目录仍被清理。
- `git diff --check`
