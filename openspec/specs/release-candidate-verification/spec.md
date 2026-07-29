# release-candidate-verification Specification

## Purpose
TBD - created by archiving change m28-v0-1-release-candidate. Update Purpose after archive.
## Requirements
### Requirement: 发布候选必须从干净 wheel 安装验收
ForgeAgent `0.1.0` 发布候选 MUST 在新建的 Python 3.11 隔离环境中只从构建出的 wheel 安装运行时及依赖。验收 MUST 清除 `PYTHONPATH`、`PYTHONHOME` 等源码覆盖，并证明导入模块与 console script 均来自该隔离环境；不得用仓库 `src/` 或开发虚拟环境冒充安装成功。

#### Scenario: 干净 wheel 安装成功
- **WHEN** RC 门禁构建 wheel 并在空隔离环境安装该 wheel
- **THEN** `forgeagent` 可导入、所需包资源可读取、console script 可执行，且模块路径位于隔离环境内

#### Scenario: 源码树遮蔽安装缺陷
- **WHEN** wheel 缺文件或安装后入口损坏，但仓库源码仍可直接导入
- **THEN** 隔离探针仍失败，不得把源码导入结果计为 RC 通过

### Requirement: 安装后 CLI 冒烟必须离线且确定
RC 门禁 MUST 通过 wheel 生成的 `forgeagent` console script 执行无凭据、无网络、非交互的 CLI 冒烟，并核对稳定的成功状态和关键输出。CLI 冒烟 MUST NOT 发起真实模型请求。

#### Scenario: 安装后 CLI 可用
- **WHEN** 隔离环境执行 CLI 帮助和内置模型目录探针
- **THEN** 两个命令均以零状态退出，并显示 ForgeAgent 命令帮助和包内模型信息

#### Scenario: console script 未生成或资源缺失
- **WHEN** wheel 未安装 `forgeagent` 入口或 CLI 不能读取包内资源
- **THEN** CLI 冒烟失败并阻止 RC 通过

### Requirement: 安装后 HTTP 冒烟覆盖真实请求生命周期
RC 门禁 MUST 使用安装后代码启动仅绑定 loopback 临时端口的 HTTP 服务，通过真实 HTTP 请求验证鉴权、提交、查询与取消生命周期，并在结束后有界关闭服务。该冒烟 MUST 使用确定性本地任务替身，不加载凭据、MCP、Memory、Skills 或外部模型。

#### Scenario: HTTP 提交查询取消成功
- **WHEN** smoke client 使用合法 bearer token 提交一个受控任务、查询其公开状态并请求取消
- **THEN** 服务返回约定状态码与有界公开投影，任务进入稳定取消终态，监听线程和 worker 被关闭

#### Scenario: HTTP 鉴权仍生效
- **WHEN** smoke client 不带有效 bearer token 请求受保护端点
- **THEN** 服务拒绝请求且不创建任务

### Requirement: 安装后协作冒烟覆盖 Single Duo Triad
RC 门禁 MUST 使用安装后的运行时和确定性 MockClient 脚本分别执行显式 Single、Duo、Triad。Duo MUST 完成 Generator 与 Evaluator 的结构化提交；Triad MUST 额外完成 Planner 计划冻结；所有模式 MUST 验证稳定终态且不得访问真实 provider。

#### Scenario: 三种显式模式均完成
- **WHEN** RC 冒烟依次执行 Single、Duo、Triad 的固定离线脚本
- **THEN** Single 返回普通 completed 结果，Duo 与 Triad 返回各自 mode 的 completed 协作报告，Triad 包含已冻结并通过的计划项

#### Scenario: 任一角色或结构化提交回归
- **WHEN** Planner、Generator 或 Evaluator 的入口、工具协议、状态持久化或终态投影不再满足固定脚本
- **THEN** 对应模式失败，整个 RC 门禁返回非零状态

### Requirement: RC 冒烟产生机器可读且不泄密的证据
RC 门禁 MUST 原子写出一个版本化 JSON 报告，记录候选版本、Python 版本、wheel 文件摘要、各 smoke 名称与 pass/fail 状态。报告 MUST NOT 包含环境变量值、凭据、目标正文、模型回复、绝对临时路径或文件内容；任一检查失败时进程 MUST 非零退出且不得生成全通过结论。

#### Scenario: 全部检查通过
- **WHEN** clean-wheel、CLI、HTTP、Single、Duo、Triad 全部成功
- **THEN** JSON 报告完整列出六类成功证据并以零状态退出

#### Scenario: 检查失败
- **WHEN** 任一检查抛错、超时、被跳过或返回不符合契约的结果
- **THEN** 进程以非零状态退出，报告标记对应失败且不包含敏感诊断原文

### Requirement: 发布说明与已知限制在 RC 时冻结
仓库 MUST 提供 `0.1.0` RC 发布说明，明确安装命令、已交付入口、验证口径、发布前阻塞条件以及冻结的已知限制。限制 MUST 至少覆盖平台证据边界、真实模型验证边界、sandbox 安全边界、HTTP 暴露边界和协作 v1 边界；文档 MUST NOT 把未执行证据写成通过。

#### Scenario: 用户评估 RC
- **WHEN** 用户阅读 `0.1.0` RC 发布说明
- **THEN** 用户可区分已验证能力、opt-in 或未验证能力、已知限制及正式发布前仍需满足的条件

#### Scenario: 限制被静默弱化
- **WHEN** 文档删除必需限制类别或把历史、supplemental、配置态证据描述成当前正式验证
- **THEN** 发布文档合同测试失败并阻止 RC 通过

