## Decisions

1. `RestrictedLimits` 是冻结的严格 Pydantic 值对象，默认值保持 30s/10s/512MiB。
2. 用户配置位于主配置 YAML 的 `restricted` mapping；CLI 三个全局 flag 仅覆盖显式提供的字段。
3. Task 只把限制传给 restricted backend；container 与 trusted 行为不变。
4. worker 将 stdout/stderr 同步镜像到系统临时目录中的宿主私有文件，每流最多保留 8KiB；audit hook 仅允许这些精确文件。
5. CPU soft limit 使用配置值，hard limit 多一秒，以便优先收到 SIGXCPU；SIGKILL 仍只报告可能由资源限制导致。
