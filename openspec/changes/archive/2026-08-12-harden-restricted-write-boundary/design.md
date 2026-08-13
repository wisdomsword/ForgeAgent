## Context

restricted worker 目前在 `_install_audit_hook()` 中把 `real_root`、`sys.base_prefix` 和 `sys.prefix` 一起放入 `allowed`。读取导入时这是必需的，但在 `main()` 调用点没有启用 `writes_only_in_root=True`，导致写访问也继承了运行时前缀白名单。仓库内 `_check_worker` 已使用 `writes_only_in_root=True`，说明现有实现已经支持“前缀只读、项目根可写”的正确模式。

## Goals / Non-Goals

**Goals:**

- 消除 restricted worker 对 Python 运行时前缀的写权限。
- 保持 runtime prefix 的读访问，避免破坏正常 import。
- 用真实子进程回归固定三条已确认逃逸路径。
- 同步 threat model 的边界表述。

**Non-Goals:**

- 不修改 trusted/container tier。
- 不引入新的 sandbox 配置面、资源限制或错误文案。
- 不顺手修复 S5、S6、S8 等其他问题。

## Decisions

1. 在 restricted worker 的 `main()` 调用 `_install_audit_hook()` 时启用 `writes_only_in_root=True`。这样保留 runtime prefix 的读白名单，但把所有写类 `open` 事件收紧到 `allowed_root`。
2. 回归测试放在 `tests/test_restricted_backend.py`，继续使用真实 `python -I -m forgeagent._sandbox_worker` 子进程，而不是 mock audit hook。
3. 三个回归点分别覆盖：普通 `site-packages` 文件写入、`.pth` 文件创建、以及 worker 自身模块文件写入；三者都应返回固定 restricted 拒绝，且不暴露越界宿主路径。
4. threat model 只修正 S1 相关句子：T7 明确 `-I` 不禁用安装环境自身 `site-packages`；T2/T7 residual risk 去掉“可写 runtime prefix”这一错误暗示。

## Risks / Trade-offs

- [runtime prefix 读写被一起收紧，导致 import 失败] -> 只在写访问时启用 `writes_only_in_root`；读路径继续允许 `sys.base_prefix` / `sys.prefix`。
- [测试依赖当前环境是否存在 site-packages] -> 测试通过 `sys.prefix` / `sysconfig` 在 worker 内动态定位当前环境真实 site-packages，而不是硬编码路径。
- [已有错误断言依赖旧行为] -> 本 change 只新增安全回归，不保留任何允许写 runtime prefix 的旧断言。
