## Context

`run_check()` 通过 `python -I -m forgeagent._check_worker` 执行宿主冻结检查。worker 安装与 restricted executor 共用的 audit hook；该 hook 允许打开 `sys.prefix`/`sys.base_prefix` 下的 Python 文件，却只允许枚举项目副本目录。pytest 导入 `_pytest` 子模块时需要枚举 site-packages 包目录，因此合法依赖导入被拒绝并退化为 `ModuleNotFoundError`。

## Goals / Non-Goals

**Goals:**

- 让 check worker 可导入当前解释器环境中已安装的 Python 包。
- 保持工作副本之外的普通宿主目录枚举、写入、网络和进程创建拒绝。
- 不改变普通 restricted executor 的 audit hook 默认行为。

**Non-Goals:**

- 不允许模型自定义检查 argv、环境或依赖路径。
- 不把 RunCheck 改为宿主直接执行，也不放弃 `-I` 或临时副本。
- 不声称 Python audit hook 等价于 OS sandbox。

## Decisions

1. `_install_audit_hook` 增加私有目录枚举 roots 和精确文件路径参数。默认均为空以保持现有 executor 语义；只有 `_check_worker` 传入 `sys.prefix`、`sys.base_prefix` 和规范化后的 `os.devnull`。
2. `os.listdir`/`os.scandir` 的判定根集合为项目副本加上述只读 roots；`os.chdir` 仍只允许项目副本，所有 mutation 事件仍只允许项目副本。
3. pytest 捕获会打开固定 OS null device，因此 check worker 只对 `os.devnull` 的精确规范路径放行读写，不放行其父目录或其他设备。测试使用真实 `CheckDefinition(..., argv=(sys.executable, "-m", "pytest", "-q"))` 和项目内最小 pytest 文件，证明失败路径被消除；既有宿主目录枚举拒绝测试继续保护边界。

## Risks / Trade-offs

- [Python 环境目录名可被被测代码观察] → 仅放行目录枚举，不放行环境外内容；这是运行已安装依赖所需的最小可见性，并在 threat model 记录。
- [参数被普通 executor 误用] → 默认值为空，唯一产品调用点为 `_check_worker`。
- [平台 prefix 重复或符号链接] → audit hook 内部继续 `realpath` 规范化并去重，不新增路径回显。

## Migration Plan

无需数据或配置迁移。回滚时移除 check worker 的只读枚举 roots 参数即可恢复旧行为。

## Open Questions

无。
