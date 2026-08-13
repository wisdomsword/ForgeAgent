## 1. restricted 写边界

- [x] 1.1 为 restricted 后端补 RED 子进程回归，覆盖 runtime prefix 普通写、`.pth` 创建，以及 `allowed_root` 外已安装 worker 文件写入三条路径。
- [x] 1.2 收紧 restricted worker 的 audit hook 安装方式：runtime prefix 继续可读以保证 import，但写权限只保留给 `allowed_root`。

## 2. 文档与验证

- [x] 2.1 更新 `docs/threat-model.md`，准确描述 runtime prefix 导入边界，并移除“运行时前缀可写”的错误暗示。
- [x] 2.2 运行新的 restricted 回归、相关聚焦 pytest 与全量 pytest，把仍存在的已知 S8 基线单独记录为非本 hotfix 问题。
