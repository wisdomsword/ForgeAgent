# Proposal

## Why

公开项目已能独立安装，但依赖/可选工具说明分散，最近五模型验收的一次性脚本只在本地。贡献者无法从 checkout 复现相同验收范围。

## What Changes

- 提供不含密钥和实际网关地址的模型路由、能力与验收配置示例。
- 将已验证的文本 Golden、流式、Duo/Triad、图像 API 检查整理为显式 opt-in 的统一验收入口。
- 提供依赖分类、安装与可选开发工具说明；用离线测试验证配置、预算、脱敏及验收判定。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `continuous-verification`：从公开 checkout 可复现的安全 opt-in 模型验收。

## Impact

新增仓库脚本、示例、文档与测试，不新增产品运行依赖，不改变内置模型注册或默认 CI 的无模型凭据合同。原始响应、生成物与用户凭据继续保存在忽略目录或用户环境中。
