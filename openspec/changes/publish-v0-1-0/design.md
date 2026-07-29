## Context

`0.1.0` 的源码版本、clean-wheel harness 与 required Linux Docker 证据已经冻结，但 README 作为 PyPI long description 仍声明候选未发布。PyPI 版本不可覆盖，Git tag 应保持不可变，因此发布必须确保上传字节、tag 指向和验证证据可关联，同时不得把凭据写入仓库或命令输出。

## Goals / Non-Goals

**Goals:**

- 让上传产物的公开描述准确表示 `0.1.0` 正式版本及其真实支持边界。
- 仅发布通过本地和 required Linux CI 的精确提交所构建的唯一 wheel/sdist。
- 以生产 PyPI 回读、下载摘要与远端 `v0.1.0` tag 证明发布结果。
- 通过进程级秘密注入使用已有凭据，避免 token 落盘或回显。

**Non-Goals:**

- 不改运行时代码、API、依赖或 `0.1.0` 版本号。
- 不扩展 M28 已冻结的平台、真实模型、sandbox、HTTP 或协作 v1 支持范围。
- 不创建 GitHub/GitLab Release 页面，也不发布容器镜像或签名制品。

## Decisions

1. **先冻结正式版描述，再运行门禁。** PyPI 使用 README 作为不可覆盖版本的 long description，必须在上传前移除 RC/未发布表述；历史 M28 记录继续保留，新的正式发布说明单独记录。
2. **从 CI 精确提交重建，而不复用旧 `dist/`。** 清理本项目构建产物后运行全量本地门禁并推送发布准备提交；仅当该提交的 required Linux pipeline 成功时，才从该精确提交重建并核对 wheel 内容与版本。
3. **本地 tag、上传、远端 tag 分阶段执行。** CI 通过后先在精确提交创建本地 annotated `v0.1.0` tag，上传生产 PyPI；上传及回读成功后才推送该 tag。相比先推 tag，这避免上传失败时公开一个不存在发行物的正式 tag；短暂的“PyPI 已发布但 tag 尚未推送”窗口可通过立即重试普通 tag push 恢复。
4. **凭据只经秘密管理器注入。** 优先使用 1Password `op run` 将 token 映射到发布进程环境，不读取 token 到聊天、文件或 shell 日志。若不存在可用凭据，发布在上传前停止，不创建远端 tag。
5. **发布后再提交证据。** PyPI URL、文件摘要、上传时间、tag 对象和 pipeline 证据写入不参与 sdist/wheel 的项目记录；它们可位于 tag 之后的 main 提交，不改变已发布字节。

## Risks / Trade-offs

- [PyPI 名称或版本在发布窗口被占用] → 上传前再次查询生产 PyPI；冲突即停止，绝不换名或覆盖。
- [上传成功但远端 tag 推送暂时失败] → 保留本地 tag 和不可变提交，重试普通 `git push origin refs/tags/v0.1.0`，禁止 force。
- [凭据缺失或 1Password 未解锁] → 在所有可逆验证完成后报告真实凭据阻塞，不输出秘密，不绕过到不受控配置。
- [文档声明超出证据] → 合同测试保留 M28 五类限制，并将平台和真实模型支持严格限定为已有证据。
