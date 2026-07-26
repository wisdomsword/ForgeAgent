## Context

`RestrictedBackend` 以 `allowed_root` 作为任务工作目录语义，并通过当前 Python 解释器执行 `-m forgeagent._sandbox_worker`。未启用 isolated mode 时，解释器会优先搜索当前工作目录；攻击者只需在任务目录放置同名包，即可让伪造 worker 在任何 audit hook、环境限制或模型代码捕获逻辑之前运行。

## Goals / Non-Goals

**Goals:**

- restricted worker 只能从解释器的可信安装路径解析。
- 保持真实 worker 对当前 Python 环境中 ForgeAgent 包的正常导入。
- 用真实子进程测试锁定模块劫持回归。

**Non-Goals:**

- 不把 Python audit hook 提升为 OS 级 sandbox。
- 不重构 worker 协议、环境清理或 container backend。
- 不增加自定义 bootstrap 文件、依赖或公共配置。

## Decisions

1. 在 restricted worker 命令中加入 Python 原生 `-I`。它同时忽略 `PYTHON*` 环境配置、用户 site-packages，并从模块搜索路径移除当前工作目录，直接消除 `allowed_root` 模块劫持。
2. 不移动 `_sandbox_worker.main()` 内的 `Runtime` import。该 import 必须读取已安装包，且单独调整 hook 前后顺序不能防止 `-m` 阶段已经发生的 worker 劫持。
3. 回归测试在真实 `allowed_root` 下创建伪造 `forgeagent/_sandbox_worker.py` 与 `runtime.py`，通过外部标记文件证明两者均未执行，同时断言真实 restricted 代码仍成功运行。
4. container backend 保持不变。它把最小 worker skeleton 只读挂载到 `/opt/fa` 并显式设置 `PYTHONPATH=/opt/fa`；本 hotfix 不扩大平台改动面。

## Risks / Trade-offs

- [Editable 安装在 isolated mode 下不可见] -> 当前项目的 venv editable 路径由安装元数据提供；先由真实回归验证，若解释器环境不支持则停止而不是引入更复杂 launcher。
- [用户 site-packages 中的 ForgeAgent 不再参与 worker 解析] -> 这是安全修复的预期行为；worker 应与启动 ForgeAgent 的当前解释器安装绑定。
- [Python 原生/内核绕过仍存在] -> threat model 继续声明 restricted 是 application-layer isolation，恶意高风险代码使用 container。

## Migration Plan

无需配置或数据迁移。回滚仅需移除 restricted worker 命令中的 `-I`，但会重新暴露已验证的模块劫持路径。

## Open Questions

无。
