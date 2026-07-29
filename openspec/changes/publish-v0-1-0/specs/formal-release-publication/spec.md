## ADDED Requirements

### Requirement: 正式发行物必须声明真实发布状态与边界
ForgeAgent `0.1.0` 的 PyPI long description 和正式发布说明 MUST 明确表示这是正式版本，提供稳定的 PyPI 安装命令和版本化 tag，并继续公开 M28 冻结的平台、真实模型、sandbox、HTTP 与协作 v1 已知限制。正式版公开描述 MUST NOT 保留“Release Candidate”“不是正式发布”或“尚未发布到包索引”等状态。

#### Scenario: 正式版公开元数据被冻结
- **WHEN** 从发布提交构建 wheel 与 sdist
- **THEN** 两种制品中的项目元数据均为 `forgeagent` `0.1.0`，long description 指向正式发布说明且不包含候选未发布表述

#### Scenario: 已知限制仍然可见
- **WHEN** 用户阅读正式发布说明
- **THEN** 用户可区分已验证范围、opt-in 或未验证能力，以及平台、真实模型、sandbox、HTTP 和协作 v1 五类限制

### Requirement: 正式发布必须绑定精确通过门禁的候选
维护者 MUST 仅从通过完整本地门禁和 required Linux Docker pipeline 的精确提交构建正式发行物。构建后 MUST 核对版本、制品内容边界、wheel 安装冒烟以及 wheel/sdist 元数据；旧 `dist/` 或不同提交的产物不得上传。

#### Scenario: 精确候选通过后允许上传
- **WHEN** 发布提交的本地全量验证和 required Linux pipeline 全部成功，且重新构建的制品检查通过
- **THEN** 唯一 `0.1.0` wheel 与 sdist 可进入生产 PyPI 上传步骤

#### Scenario: 门禁或制品检查失败
- **WHEN** 任一 required 门禁失败、跳过，或制品无法关联到发布提交
- **THEN** 发布 MUST 停止，且不得上传 PyPI 或推送正式 tag

### Requirement: PyPI 与 tag 发布结果必须可独立回读
正式发布 MUST 上传到生产 PyPI，并创建指向发布提交的 annotated `v0.1.0` tag。完成条件 MUST 包括 PyPI JSON 可见 `0.1.0`、PyPI 文件摘要与本地上传制品一致、下载后的 clean-wheel 冒烟通过，以及远端 tag 可解析到同一发布提交。发布过程 MUST NOT 在仓库、日志或报告中暴露凭据。

#### Scenario: PyPI 上传和 tag 推送成功
- **WHEN** 上传返回成功且 PyPI 回读、下载摘要、clean-wheel 冒烟和远端 tag 回读全部一致
- **THEN** 发布记录可声明 `forgeagent==0.1.0` 与 `v0.1.0` 正式发布完成，并列出非秘密证据

#### Scenario: 凭据或外部发布步骤失败
- **WHEN** 凭据不可用、PyPI 拒绝上传、回读不一致或普通 tag push 失败
- **THEN** 过程 MUST 保留已有可恢复状态、报告精确失败步骤并停止夸大完成状态，且不得通过覆盖版本、force push 或泄露 token 恢复
