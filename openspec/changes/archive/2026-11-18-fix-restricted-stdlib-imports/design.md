# Design

## Context

普通 worker 的 `main()` 没有为 audit hook 配置解释器可枚举目录；`_check_worker.py` 已传入 `(sys.base_prefix, sys.prefix)`。文件 open 与目录枚举策略不一致，使冷启动包的子模块发现失败。

## Goals / Non-Goals

恢复解释器库中的模块发现，不改变写入授权、目录外普通文件访问、网络、进程或回执保护。不预加载 unittest，不硬编码 Python 安装路径，不新增全盘权限或依赖。

## Decisions

- 普通 worker 入口复用 check worker 的解释器前缀枚举配置；不修改共享 hook 默认参数及其他调用者。
- 真实 subprocess 回归覆盖冷启动 unittest、嵌套标准库及项目测试执行，避免宿主预导入缓存掩盖问题。
- 增加直接目录访问及 symlink 越界、解释器前缀写入/创建目录拒绝回归，联跑现有网络、进程、回执测试。
- 真实验收使用新的 run 目录，同一固定目标与三模型角色，不覆盖原失败证据；只预批准两个测试文件的写入。

## Risks / Trade-offs

解释器前缀内目录现在可枚举，与既有可读文件范围及 check worker 保持一致。前缀内依赖仍属于受信任运行时；restricted 继续是应用级限制，不扩大其安全承诺。通过实际冷启动和反向边界测试验证此权限差异。

## Migration Plan

无持久化格式或配置迁移。回退单行入口参数即可恢复原行为，但会重新触发导入失败。
