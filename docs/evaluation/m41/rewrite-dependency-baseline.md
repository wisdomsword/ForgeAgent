# M41 Rewrite / Dependency Baseline

- 测量日期：2026-07-31
- 基线提交：`a2c9925`（测量包含工作区中进入 M41 前已有的 5 行 `receipt_store` 接线，不归入 M41）
- 目标：拆分 CLI 内部职责；保持所有外部行为和测试契约不变
- 停止规则：任一硬阈值不满足时，回退 M41 自身提取并保留进入 M41 前的工作区状态

## 六项门禁

| metric | baseline | threshold | evidence | migration | rollback trigger |
| --- | --- | --- | --- | --- | --- |
| `performance` | 15 个独立 Python 进程：`forgeagent.cli` 冷导入中位数 113.450 ms、p95 131.284 ms；`build_parser()` 中位数 0.560 ms、p95 0.577 ms | 同机同命令复测的两个中位数均不得超过基线 20%（136.140 ms、0.672 ms） | 文末基准命令的原始 JSON；实施后同命令复测 | 仅改变内部 import/委托路径，逐边界验证 | 任一中位数超阈值且一次干净复测仍超阈值 |
| `reliability` | `tests/test_cli.py`、`tests/test_collaboration_integrations.py`、`tests/test_http_task_service.py` 共 349 passed；M40 全量 2534 passed、10 skipped | 聚焦与全量均零失败；既有 skip 不得因 M41 增加 | pytest 原始结果、最终验证报告 | 每个边界先保持 façade，再迁移实现 | 新失败、异常吞噬、资源关闭或生命周期回归 |
| `maintenance cost` | `cli.py` 3226 行、129220 字节、73 个顶层符号、54 条顶层 import 语句；8 个项目运行时直接依赖 | `cli.py` 不超过 1800 行；任一新增边界模块不超过 900 行；运行时直接依赖仍为 8；不得新增框架/注册器/插件层 | AST/文件统计、`uv tree --depth 1`、Ruff | 按 parser/config → collaboration adapter → REPL → HTTP/client 顺序提取 | 结构阈值不满足，或为达阈值引入额外抽象/依赖 |
| `compatibility` | 7 个帮助入口退出码均为 0、stderr 为空；stdout SHA-256 见下表；349 个边界测试通过 | 帮助输出字节、退出码、stderr hash 全部一致；旧 `forgeagent.cli` 导入与 monkeypatch 位置继续工作；HTTP 契约测试全绿 | 帮助输出哈希、parser 测试、CLI/HTTP 回归 | `forgeagent.cli` 保留兼容名称和薄 wrapper | 任一输出、退出码、HTTP shape、默认值或旧导入变化 |
| `team capability` | Python 3.11+、stdlib argparse/http、现有 pytest/Ruff/uv；无额外语言或构建工具 | 继续只使用团队已有 Python/pytest/Ruff/uv；每个模块职责可由名称和模块 docstring 直接识别 | 依赖树、模块清单、Ruff、设计/计划评审 | 用现有函数和显式依赖注入，不引入容器框架或代码生成 | 需要新语言、运行时依赖、隐式注册或专有生成工具才能维护 |
| `migration/rollback risk` | 无 CLI 数据迁移；当前单模块可由 Git 回退；工作区含 M41 外既有改动 | 无数据/config/schema 迁移；四个边界各自可验证、可单独回退；M41 不覆盖或提交既有用户改动 | 分边界提交、dirty-worktree 归因、`git diff --check`、最终 diff 审查 | 先 façade 后实现，保持旧入口并逐步切换 | 无法单独回退、污染既有改动、需要双写/状态迁移或出现行为差异 |

## 帮助输出基线

| argv | exit | stdout bytes | stdout SHA-256 | stderr SHA-256 |
| --- | ---: | ---: | --- | --- |
| `--help` | 0 | 1608 | `7b99003897c90cf32c86bfb198f251222327e03bf8e2faaeada98c89ec9c76b3` | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| `run --help` | 0 | 773 | `14a60081cb8f530692a01f3e840fd554cd4f1e9cd46a98e5483db10908e7589a` | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| `loop --help` | 0 | 906 | `dc990fa9c6acc1b3a40a7cd8ba58b72384e2688d451c386bcdd0bfc541d49e8f` | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| `serve --help` | 0 | 159 | `01f9c0fa42fe5fa7541f9ff53867a808aa1da1c259ecc5b79ea6b71ae309dcfc` | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| `evaluate --help` | 0 | 553 | `cb8204fa8b055822b5438b8dab2aeb49d5a72d8488360e0915e32e2a181f08e7` | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| `models --help` | 0 | 86 | `eab585f6c180a6c82ed779d1d977903fe935569cb181364ee3569f1d5d5aea05` | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| `smoke --help` | 0 | 415 | `ef2c9b04e1e36969b6333264080ffb67aab79ebdfd9dc6a5b7de7ff68aa6dc05` | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |

## 可复现命令

性能、结构、依赖和帮助哈希均使用仓库现有 `uv run python`、`uv tree --depth 1` 与标准库测量，不读取凭据、不访问网络。最终验证报告必须记录同口径复测结果；不得用不同采样方式替换基线后再宣称达标。

## 最终同口径复测

- `performance`：15 个独立进程的冷导入中位数 `110.761 ms`、最大样本 `118.191 ms`；`build_parser()` 中位数 `0.547 ms`、最大样本 `0.623 ms`，均低于 `136.140/0.672 ms` 硬阈值。
- `reliability`：边界聚焦测试 `483 passed`；归档后全量测试 `2549 passed, 10 skipped in 168.06s`，未增加 skip。
- `maintenance cost`：`cli.py` 为 1789 行、70572 字节、48 个顶层符号、44 条顶层 import；`_cli_parser.py` 306 行、`_cli_collaboration.py` 230 行、`_cli_repl.py` 615 行、`_cli_http.py` 780 行；8 个运行时直接依赖。
- `compatibility`：7 组帮助输出由 `tests/test_m41_cli_boundaries.py` 逐字节校验；旧门面导入和运行时 monkeypatch 绑定由新增回归覆盖。
- `team capability`：仍仅使用 Python、pytest、Ruff 与 uv；未新增框架、注册器、生成器或依赖。
- `migration/rollback risk`：无数据、配置或 schema 迁移；四个边界按独立 commit 提取；进入 M41 前已有的 5 行 `receipt_store` 工作区改动保持未提交。

原始 15 进程样本（毫秒）：

```json
{
  "import_ms": [115.907041, 108.619042, 108.247375, 108.545750, 110.761375, 116.702583, 115.616333, 116.566917, 115.563041, 118.190584, 112.227459, 109.677500, 108.737250, 109.560417, 109.055083],
  "parser_ms": [0.620750, 0.534042, 0.546875, 0.550750, 0.553000, 0.552625, 0.553500, 0.623125, 0.611125, 0.534083, 0.529666, 0.519750, 0.544625, 0.537334, 0.531208]
}
```
