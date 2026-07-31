# 里程碑 M41: CLI boundary extraction

- 状态: 已完成
- 起止: 2026-07-31 ~ 2026-07-31
- 对应 ACTION_PLAN 行: M41（见该文件 §四里程碑表）
- 前置里程碑: [milestone_040](milestone_040.md)
- 分发边界: 包索引发布、tag、push 和发布自动化不在当前目标中

## 目标与范围

先建立 performance、reliability、maintenance cost、compatibility、team capability、migration/rollback risk 六项 Rewrite/Dependency 基线，再按 parser/config、collaboration adapter、REPL、HTTP/client 顺序拆分 `forgeagent.cli`。保持命令行输出、HTTP 返回、旧导入、monkeypatch、资源关闭和领域契约不变；任一硬阈值失败则停止重构并保留原实现。

## 方案设计

- `forgeagent.cli` 保留 console entry point、命令分派与兼容 façade。
- 无可变依赖的纯函数可直接 re-export；会受 monkeypatch 或资源生命周期影响的入口保留薄 wrapper，并在每次调用时传递当前绑定。
- 四个私有模块只依赖现有领域模块，不反向导入 `forgeagent.cli`，不形成通用 DI 层。
- 六项终值与原始性能样本记录在 `docs/evaluation/m41/rewrite-dependency-baseline.md`；技术设计和实施计划位于 `docs/superpowers/specs/2026-07-31-cli-boundary-extraction-design.md` 与 `docs/superpowers/plans/2026-07-31-cli-boundary-extraction.md`。

## 子任务清单

- [x] 建立六项基线、硬阈值、回滚规则和 7 组帮助哈希。
- [x] 顺序提取 parser/config、collaboration adapter、REPL、HTTP/client 四个边界。
- [x] 保留动态 façade bindings、旧导入、输出、HTTP 与资源所有权契约。
- [x] 完成两轮自审并修复发现的三处兼容/归属问题。
- [x] 完成聚焦、全量、性能、结构、静态、构建和 OpenSpec 验证。
- [x] 完成 Comet verify、主规格合并和 change 归档。

## 交付物清单

- [x] `src/forgeagent/_cli_parser.py`：parser、evaluation 与纯配置解析边界。
- [x] `src/forgeagent/_cli_collaboration.py`：协作 CLI adapter 与报告投影。
- [x] `src/forgeagent/_cli_repl.py`：REPL 状态机、启动展示和命令调度。
- [x] `src/forgeagent/_cli_http.py`：真实 client 与 HTTP runtime 装配。
- [x] `src/forgeagent/cli.py`：稳定入口与运行时兼容门面。
- [x] `tests/test_m41_cli_boundaries.py`：结构、依赖、输出和动态绑定门禁。
- [x] `docs/evaluation/m41/rewrite-dependency-baseline.md`：六项基线与最终终值。
- [x] `docs/superpowers/reports/2026-07-31-cli-boundary-extraction-verify.md`：完整验证证据。

## 三次评审

### 技术方案评审

- [x] 四边界与 approved design 一致，没有新增命令、配置、schema、数据迁移或领域状态所有权。
- [x] `cli.py` 1789 行、边界模块最大 780 行、运行时依赖 8，全部满足停止阈值。
- [x] 没有引入框架、service locator、注册器、生成代码或第五个边界模块。

### 代码评审

- [x] 当前会话禁止启动子代理，主 agent 对 base-ref 完整 diff 与 CodeGraph 调用路径完成两轮独立自审，并如实记录该限制。
- [x] 修复直接 alias 导致 `cli.load_registry` monkeypatch 失效的问题。
- [x] 修复启动显示绕过当前 façade 能力 callback 的问题。
- [x] 修复两段配置解析仍滞留 `cli.py` 的边界遗漏。
- [x] M41 前已有的 5 行 `receipt_store` 工作区改动保持未提交，未被本里程碑覆盖。

### 验收评审

- [x] 性能：冷导入/parser 中位数 `110.761/0.547 ms`，低于 `136.140/0.672 ms`。
- [x] 结构：`cli.py` 1789 行；四模块 306/230/615/780 行；无反向 `forgeagent.cli` import。
- [x] 聚焦测试：`483 passed`；全量：`2549 passed, 10 skipped in 166.20s`。
- [x] Ruff check、134 文件 format check、`uv build`、diff check 通过。
- [x] OpenSpec strict：`32 passed, 0 failed`；Comet change 已归档。

## 遗留问题

- [ ] `cli.py` 距 1800 行阈值仅余 11 行 — 影响：后续直接向主模块增加职责会重新触发维护门禁 — 计划：新 CLI 逻辑进入既有四边界，只有兼容 façade/顶层分派保留在主模块。

## 续接指引

读取本文件与 `ACTION_PLAN.md`。M41 已完成 CLI 内部边界拆分，后续不得把 parser/config、Collaboration adapter、REPL 或 HTTP/client 职责回填 `cli.py`；继续保持分发目标移除，不执行包索引上传、tag、push 或发布自动化。Memory 迁移与 HTTP 远程动作审批绑定仍是条件候选，必须独立立项。
