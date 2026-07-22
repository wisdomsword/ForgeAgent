# M16 FileWrite Allowlist 真实模型黑盒脚本设计

## 目标

提供一个单命令验收脚本，通过真实 `forgeagent serve` 和真实模型验证同一个 FileWrite 操作在空 HTTP allowlist 下被拒绝、加入精确 `file/<path>` 后被允许。脚本只用于 M16 人工验收，不改变产品协议或运行时行为。

## 执行边界

- 使用动态空闲 loopback 端口、独立临时 allowed root、配置、日志和 JSONL 审计文件，不影响用户当前运行的服务。
- 使用现有 `.venv/bin/forgeagent`、`curl`、`jq` 和当前 shell 中已有的模型凭证；默认模型为 `claude-sonnet-5`，可由 `M16_MODEL` 覆盖。
- 两个阶段使用完全相同的目标文本，并内嵌唯一、完整的 ForgeAgent
  `<!-- ToolCall: ... -->` FileWrite 标记及精确 `path`/`content` 参数。目标明确要求
  模型原样发出该标记，不得改用 Exec、MCP、Python、shell 或其他工具。这样黑盒测试
  只验证文本协议解析、HTTP allowlist 和真实执行链，不把未公开工具语法的猜测能力混入判据。
- 每个阶段独立启动和关闭服务；脚本退出时通过 trap 清理后台进程，但保留临时证据目录。
- 真实模型调用会产生费用，且执行时长受 provider 延迟影响。

## 两阶段流程

### 阶段一：空 allowlist

1. 以 `allowlist: []` 启动服务。
2. 提交固定 FileWrite 目标并轮询到终态或超时。
3. 审计必须包含该 task 的 `confirmation.decision`，结果为 `denied`，安全参数表明操作是目标 FileWrite。
4. 目标文件必须不存在。

### 阶段二：精确 allowlist

1. 清理目标文件，以 `allowlist: [file/m16-allowlist.txt]` 重启服务。
2. 提交与阶段一完全相同的目标并轮询到终态或超时。
3. 审计必须包含该 task 的 `confirmation.decision`，结果为 `preapproved`，并包含成功的 FileWrite `tool.operation`。
4. 目标文件必须存在，且内容与固定期望文本完全一致。

## 结果判定

- `PASS`：两个阶段的审计决策、工具结果和文件断言全部满足。
- `FAIL`：服务无法启动、HTTP 契约错误、空 allowlist 仍预批准目标 FileWrite、精确 allowlist 拒绝目标 FileWrite、审计缺失/泄密，或文件内容错误。
- `INCONCLUSIVE`：真实模型没有调用目标 FileWrite、存在额外成功工具操作，或产生
  目标之外的文件 artifact。目标 FileWrite 已产生权威 decision/tool 事件后，额外
  失败工具操作只保留为诊断，不覆盖 allowlist 证据。该结果不说明 allowlist 正确
  或错误，脚本以非零状态退出并保留证据。

## 错误处理与输出

- 启动、HTTP 请求和轮询均使用有界超时；默认阶段超时可由 `M16_TIMEOUT_SECONDS` 覆盖。
- 启动失败时打印服务日志路径；阶段失败时打印终态响应、相关审计事件和证据目录。
- bearer token 使用 Python `secrets` 临时生成，不写入配置、终端摘要或审计。
- 成功时打印两个 task id、终态、审计判定和证据目录。

## 验证

- 对脚本执行 `bash -n` 和 ShellCheck（若本机已安装）。
- 使用小型 fake `forgeagent`/HTTP fixture 验证控制流、超时和退出码，不触发真实模型费用。
- 人工 opt-in 执行真实模型黑盒验收，作为最终外部证据。
