---
comet_change: extract-cli-boundaries
role: technical-design
canonical_spec: openspec
---

# M41 CLI Boundary Extraction 技术设计

## 1. 现状与约束

`src/forgeagent/cli.py` 当前 3226 行，既包含稳定对外入口，也包含四组内部装配职责。大量测试通过 `forgeagent.cli` 替换 class、factory 和 helper；普通 re-export 只能保留名称，不能保留被移动函数查找 globals 的位置。因此兼容性必须覆盖“调用时依赖解析”，不能只覆盖 import 成功。

M41 是纯内部重构：无新命令、无 schema/config/data 迁移、无新依赖、无发布动作。`docs/evaluation/m41/rewrite-dependency-baseline.md` 的六项阈值是停止门禁。

## 2. 模块图与依赖方向

```text
console script / tests
          |
          v
   forgeagent.cli  (entry point + compatibility facade + main dispatch)
      |       |       |       |
      v       v       v       v
  _cli_   _cli_collab  _cli_   _cli_
  parser  oration      repl    http
      \       |          |       /
       \      v          v      /
        +--- existing domain modules ---+
```

四个内部模块之间不得互相导入，也不得导入 `forgeagent.cli`。`cli.py` 可以导入四个内部模块；领域模块不得新增对内部 CLI 模块的依赖。

## 3. 边界清单

### 3.1 `_cli_parser.py`

迁移 `build_parser`、严格 JSON/evaluation 辅助函数及只读 parser/config 处理。稳定领域类型直接导入。`cli.py` 直接绑定并 re-export 历史函数名；这些函数不依赖可替换的 `cli.py` globals。

验收：七个帮助输出逐字节一致，parser action/default 测试通过，模块不导入 HTTP、MCP 或 Task 启动路径。

### 3.2 `_cli_collaboration.py`

迁移协作报告渲染、计划确认、模式确认和 `run_collaboration_once` 实现。定义最小冻结 `CollaborationBindings`，只传入历史上从 `forgeagent.cli` 替换的 Task/Runner/factory/render 等调用点。`cli.py` wrapper 保留原签名，并在每次调用时构造 bindings。

稳定的数据模型、枚举和纯函数由内部模块直接导入。Runner/Task 的状态迁移仍由 collaboration/task 领域模块拥有。

验收：Single/Duo/Triad、planner confirmation、client context validation、report rendering 和既有 `cli_module.<dependency>` monkeypatch 测试通过。

### 3.3 `_cli_repl.py`

迁移 prompt-toolkit reader、TTY 判定、启动展示、显示暂停、启动摘要和 REPL 循环。定义 `ReplBindings`，包含 run/run-collaboration、MCP 构建、身份/Memory/Skill 装载、slash handlers、路由审计等由 façade 暴露的调用点。

REPL implementation 继续拥有 MCP 的 `try/finally close()` 和会话级 usage/staged images；wrapper 不截获异常、不复制状态。

验收：非 TTY 零启动噪声、TTY 摘要、reload 原子切换、slash 命令、staged image、模式路由、MCP close 和旧 monkeypatch 路径全部通过。

### 3.4 `_cli_http.py`

迁移 client/context 校验、HTTP runtime settings、策略冲突检查、owned server 关闭和 `serve_http` 实现。定义 `HttpBindings`，由 façade 逐调用传入 build client、registry、MCP、身份/Memory/Skill、Loop/Collaboration 和 server adapter 等可替换依赖。

HTTP implementation 继续拥有 TaskService/receipt store/Loop/Collaboration 的装配与 server shutdown；`HttpStartupError` 可在内部定义后由 `cli.py` re-export，错误文本和 main 的捕获路径保持不变。

验收：配置严格性、context validation、startup failure、signal shutdown、cancel、receipt、Loop/Collaboration、返回 shape 和 stderr 投影测试通过。

## 4. Façade 规则

1. 原公开或测试使用的 `forgeagent.cli` 名称继续存在。
2. wrapper 保持原签名、默认值、返回类型和异常类型。
3. bindings 在调用时创建，不在 import 时冻结，确保 monkeypatch 生效。
4. 内部实现不得通过动态 import、`sys.modules`、全局 service locator 或反向 import 获取 façade。
5. wrapper 不新增日志、捕获、重试或资源所有权。

## 5. TDD 与迁移步骤

1. RED：新增 M41 结构测试，先证明当前 3226 行单文件不满足目标；新增帮助哈希和代表性 façade 替换测试并保持绿。
2. GREEN parser/config：机械迁移、re-export、聚焦测试。
3. GREEN collaboration：添加 bindings 契约测试，迁移并跑协作专项。
4. GREEN REPL：添加当前调用替换与 close 测试，迁移并跑 REPL/startup 专项。
5. GREEN HTTP/client：添加当前调用替换与 shutdown 测试，迁移并跑 HTTP 专项。
6. REFACTOR：只删除确认无调用的旧 imports/重复实现；不做领域重写。
7. 全量门禁和两轮审查；任一硬阈值最终失败即回退 M41 实现。

## 6. 验证矩阵

| 风险 | 定向证据 |
| --- | --- |
| parser/help 漂移 | 7 个 argv 的 exit/stdout/stderr hash + parser tests |
| monkeypatch 失效 | 代表性 façade dependency replacement tests + 既有测试 |
| Collaboration 语义漂移 | collaboration integrations/runner/stop projection tests |
| REPL 生命周期漂移 | CLI、startup blackbox、identity/Skills/Memory tests |
| HTTP 生命周期漂移 | HTTP server/task service、Loop、receipt、cancel tests |
| import 环或性能退化 | import smoke、15 进程中位数、CodeGraph/AST import 检查 |
| 结构未收敛 | `cli.py <= 1800`、每个边界模块 `<= 900`、直接依赖仍为 8 |

## 7. 回滚

每个边界单独提交。聚焦测试失败时只修复或撤销当前边界；不得进入下一边界。最终阈值失败时撤销 M41 实现提交，保留基线和失败证据；进入 M41 前的用户改动按原 diff 保留。不存在数据回滚、双写或兼容期。
