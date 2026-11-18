# Design

## Decisions

- 复用现有五项 real Golden、OpenAI-compatible client、CLI 协作入口与 restricted 独立检查，不复制核心执行环路。
- 配置只引用环境变量名；基础地址必须为无 userinfo/query/fragment 的 HTTPS 根地址。模型能力数值是可调验收预算，不冒充服务商极限。
- 默认仅 dry-run，付费请求需显式 opt-in。跨 suite 使用一个请求预算，SDK 只尝试一次；不自动重做不确定的图像请求。
- 输出只写入仓库 artifacts 下的新目录，已有证据不可覆盖；已知敏感值脱敏。固定协作目标只批准两个候选文件写入。
- 图像请求使用不自动跳转的标准库 HTTPS 客户端，要求 base64 PNG；核对请求尺寸，视觉质量另需人工检查。
- Python 依赖和外部工具通过已有锁定/安装说明提供，不将库、镜像、第三方 Skills 或真实凭据 vendoring 入库。

## Risks / Trade-offs

真实请求收费且依赖外部服务，默认 CI 仅使用离线替身验证新入口。原始记录可能含任务/环境信息，即使脱敏仍应私有保存。图像支持范围限定当前验收的 base64 PNG，其他交付格式须明确扩展后验证。
