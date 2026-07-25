# P2/P3 运行时韧性与证据验证报告

## 结论

P2/P3 已合并在同一个 Comet change 中处理。实现新增宿主冻结的 Evaluator
检查、可执行 MCP hung-call 回归和有界搜索 fallback；native tool-call 流式聚合继续由
既有回归覆盖。未执行的外部模型调用和不可用容器平台不声明通过。

## 已实现契约

- `RunCheck` 只接受已注册检查 ID。argv、环境和超时由可信宿主拥有；标准 CLI/HTTP
  schema 不暴露该权限。
- 检查拒绝全部 symlink 和特殊文件，把项目复制到临时树，只允许当前 Python 入口通过
  restricted audit-hook worker 执行。读写限制在副本内，禁止网络、spawn、fork、exec 和
  进程信号控制。输出用固定 head/tail 内存上限持续 drain；超时或取消终止 POSIX 进程组。
- Planner/Generator/Evaluator 边界取消后不再构造下一角色或 rejection attempt。provider
  调用仍只承诺 cooperative cancel。
- 原永久 skip 的 MCP hung-call 测试现启动真实本地 stdio server，其工具永不返回；测试
  验证固定 deadline、generation 失效和有界 close。
- 搜索先尝试首选内置引擎，失败或零结果时最多尝试另一个内置引擎一次。每次请求独立
  使用既有 SSRF/redirect 策略。最终优先级为：任一结果、blocked、unavailable、两次零结果。

## 证据矩阵

| 证据 | 结果 |
| --- | --- |
| 复审修复后最终完整 pytest | 使用全新临时 uv cache：`2125 passed, 10 skipped` |
| 最新沙箱内完整 pytest | `2101 passed, 12 failed, 22 skipped`；11 项 loopback 与 1 项 package build 环境失败 |
| Check/Collaboration/MCP 专项 | 最终安全与契约专项 `329 passed` |
| 搜索专项 | `27 passed` |
| 搜索 + SSRF + CLI 相邻专项 | `108 passed, 2 skipped` |
| Native tool-call 静默聚合 fallback | `1 passed, 25 deselected` |
| Container + MCP 矩阵 | `219 passed, 10 skipped`；skip 均为 Docker daemon/image 可用性检查 |
| 离线 golden | `20/20 passed` |
| Ruff | format check 与 lint 通过 |
| 打包 | wheel/sdist 构建通过；共享 uv cache 的损坏条目曾导致依赖安装失败，全新临时 cache 下完整 packaging test 通过 |
| OpenSpec | 归档前 strict `18/18` 通过 |
| 宿主 | macOS 26.5.1，Darwin arm64 |
| Docker | CLI 29.2.1 存在；有界启动 Docker Desktop 后 daemon 仍不可用 |
| Linux Docker / Podman | 当前环境不可用，未验证 |
| 真实模型 golden / single-Triad / credentialed Evaluator | 检测到凭证，但仓库派生 payload/destination 外发未获具体授权；未验证 |

## P3 裁决

- Native tool-call 流式片段聚合已有实现，专项 fallback 回归通过。
- 持久 REPL 历史继续延期，直到出现跨进程/会话回忆需求，并先完成存储、脱敏、保留和
  opt-out 契约评审。
- 语义摘要继续延期，直到 sliding-window eviction 对真实工作负载造成可测损害，且确定性
  评估集能证明其优于抽取式方案。
- 音视频输入继续延期，直到至少一个已配置 provider 和 CLI/HTTP transport 需要它，并先
  设计大小、类型、存储和成本限制。
- 响应侧多模态继续延期，直到消费者需要 typed binary artifact，并具备显式渲染、存储和
  safe projection 契约。
- Model router、scheduler、plugin market、team memory/approval、MCP Apps UI 和 memory
  confidence/decay 不进入本 change；需要独立用户需求和设计。

## 残留风险

- `RunCheck` 使用 Python audit-hook 隔离，不是 OS/container 密封 sandbox。native/kernel
  bypass 与恶意同宿主 copy/check race 仍是残留风险。
- 取消不能异步杀死在途 provider 调用；MCP 依赖 SDK deadline 与 session generation 失效。
- 搜索 HTML 仍依赖 provider 页面布局，即使已有 fallback。
- 在具备授权和环境后，必须重跑 Docker 与真实 provider 证据，才能声明对应矩阵通过。

## 评审闭环

独立 thorough review 找到五个 Important：项目检查以宿主权限运行、输出存储/回读无界、
descendant 终止不完整、MCP stale success、Evaluator 构造前取消窗口。修复分别加入 restricted
Python worker、流式有界 capture、grace 后无条件尝试 POSIX group SIGKILL、await 后 MCP
generation/session 复检和角色启动守卫。

两轮自审进一步加入进程信号控制拒绝，并清除 design/spec/plan 中残留的 fake-session 旧方案。
最终专项为 `329/329`，完整 pytest 为 `2125/2125`，保留 10 个 Docker 环境 skip。
