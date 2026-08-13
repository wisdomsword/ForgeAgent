## ADDED Requirements

### Requirement: restricted 运行时前缀只读
ForgeAgent MUST 允许 restricted worker 读取 import 所需的已安装 Python 运行时前缀；但除非对应路径同时位于 `allowed_root` 内，任务代码 MUST NOT 在 `sys.base_prefix`、`sys.prefix` 或其 `site-packages` 后代中创建、修改、截断、重命名或删除文件。

#### Scenario: restricted 任务不能写入 site-packages
- **WHEN** restricted 任务代码在 `allowed_root` 外、当前解释器的 `site-packages` 目录下以写模式打开普通文件
- **THEN** ForgeAgent 以标准 restricted 文件访问拒绝阻止写入，并保持目标文件不变

#### Scenario: restricted 任务不能创建 .pth 启动文件
- **WHEN** restricted 任务代码尝试在 `allowed_root` 外、当前解释器的 `site-packages` 目录下创建或追加 `.pth` 文件
- **THEN** ForgeAgent 在文件创建前拒绝写入，后续 worker 启动不得从该路径执行攻击者控制的启动代码

#### Scenario: restricted 任务不能覆盖 worker 包文件
- **WHEN** restricted 任务代码尝试写入 `allowed_root` 外、`sys.prefix` 下已安装 `forgeagent` 包内的文件
- **THEN** ForgeAgent 以标准 restricted 文件访问拒绝阻止写入，并保持已安装 worker 包不变
