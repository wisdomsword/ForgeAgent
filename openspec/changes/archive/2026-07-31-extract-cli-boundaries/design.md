## Context

`forgeagent.cli` 既是 console-script 入口，也是历史测试和内部调用方的兼容导入面。当前模块把参数解析、配置装载、协作运行装配、REPL 状态机、HTTP 服务装配及若干展示工具放在同一文件中。直接重命名或移动函数会破坏大量 `forgeagent.cli.<name>` monkeypatch 点，因此本次不能把“文件拆小”误当成“兼容已保持”。

六项 Rewrite/Dependency 基线和停止阈值记录在 `docs/evaluation/m41/rewrite-dependency-baseline.md`。它们是实施许可的一部分，不是完成后补写的说明。

## Goals / Non-Goals

**Goals:**

- 将 parser/config、collaboration adapter、REPL、HTTP/client 分离为私有内部模块。
- 让 `forgeagent.cli` 收敛为稳定入口、兼容 façade 和顶层命令分派。
- 保留历史导入、monkeypatch、输出、退出码、HTTP schema、资源关闭与安全边界。
- 用按边界提交和门禁让每一步可以单独定位与回退。

**Non-Goals:**

- 不增加或删除命令、选项、配置键、HTTP 字段或运行模式。
- 不重写 Task、Loop、Collaboration、MCP、Memory、Skills 或 HTTP service 领域逻辑。
- 不引入 DI 框架、插件注册器、全局 service locator、代码生成或新依赖。
- 不修改进入 M41 前已有的用户工作区改动，不恢复任何分发目标。

## Decisions

### 1. 保留 `forgeagent.cli` 作为兼容 façade

对无可变依赖的纯函数，`cli.py` 可以直接 re-export。对依赖测试替换点或生命周期所有权的入口，`cli.py` 保留薄 wrapper，并把当次调用需要的 class/callback/value 显式传给内部实现。这样 monkeypatch 仍命中 `forgeagent.cli`，内部模块不反向导入 `cli.py`，避免循环依赖。

不采用“移动后更新全部测试 monkeypatch 路径”，因为它会改变现有测试契约并掩盖第三方内部调用回归；也不采用 `sys.modules` alias 或动态代理，因为其行为隐式且排障成本更高。

### 2. 四个单向内部边界

- `_cli_parser.py`：`argparse` parser 构建、严格 JSON/evaluation 命令解析及纯配置值解析；不得启动网络、MCP、Task 或 HTTP server。
- `_cli_collaboration.py`：Single/Duo/Triad CLI adapter；只负责已有 Runner/Task 的装配和公开报告渲染，不拥有领域状态迁移。
- `_cli_repl.py`：REPL 会话状态机、启动展示和命令调度；通过显式 bindings 调用 `cli.py` 暴露的既有执行/命令函数。
- `_cli_http.py`：HTTP runtime 配置和服务装配；通过显式 bindings 使用现有 `http_server`、`TaskService`、Loop/Collaboration 组件，不改变 HTTP domain model。

内部模块可以依赖领域模块，但不得互相形成环或导入 `forgeagent.cli`。`cli.py` 负责从当前模块全局值构造 bindings，因此历史 monkeypatch 继续生效。

### 3. 按风险从低到高迁移

顺序固定为 parser/config → collaboration adapter → REPL → HTTP/client。每步先补/运行本边界回归，再移动实现并复测；失败只回退当前 M41 步骤。最后才评估六项阈值，未达标则停止并回退 M41 提取，不以放宽阈值宣称完成。

### 4. 性能和结构门禁使用同口径复测

性能使用独立 Python 进程的中位数，避免单进程模块缓存伪造改善。结构用 AST 和文件字节统计；兼容用 7 个帮助入口字节哈希、既有 pytest 和旧导入/monkeypatch 回归。不得在实施后更换采样方法或删除失败场景。

## Risks / Trade-offs

- [显式 bindings 增加少量样板] → 只为真实 monkeypatch/lifecycle 边界建冻结 dataclass，不建立通用容器。
- [机械迁移可能改变函数 globals 的解析位置] → façade wrapper 在每次调用时从 `cli.py` 当前 globals 构造 bindings，并用现有 monkeypatch 测试验证。
- [HTTP/REPL 资源关闭顺序漂移] → 保留原 `try/finally` 所有权，增加/保留 close、cancel、startup failure 专项测试。
- [性能受机器噪声影响] → 比较 15 个独立进程的中位数，20% 作为材料性退化阈值；超阈值后只允许同口径干净复测一次。
- [为了行数阈值产生过度拆分] → 新模块固定为四个边界，最大 900 行；禁止再建 manager/factory/registry 层。

## Migration Plan

1. 固化基线、帮助哈希和结构契约。
2. 提取 parser/config，保持 `build_parser` 等旧名称可导入。
3. 提取 collaboration adapter，并通过 façade bindings 保持替换点。
4. 提取 REPL 会话状态机与启动展示，保留 slash handler 和执行入口契约。
5. 提取 HTTP/client 装配，保留服务错误投影、关闭和返回值。
6. 执行六项复测；任一硬阈值失败则回退 M41 提取提交并保留基线文档作为停止证据。

## Open Questions

无。用户已授权在决策点进行两轮自审后采用推荐方案；本设计选择单 change、branch 隔离、TDD 和 standard review，不引入子代理。
