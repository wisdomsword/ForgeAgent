# M27 最终整分支独立审查

## 结论

独立 reviewer 对 `1273e90b00adeab0b85d3db7bdc0463c82e7dc2a..HEAD` 的 M27 tracked diff
执行静态审查。审查先后发现 5 个 Important、无 Critical；全部问题均按 TDD 修复，并经过受影响
测试、Ruff、完整仓库验证与 reviewer 复审。最终结论为 **Approved**，没有剩余 Critical 或
Important finding。

## Findings 与修复

1. CLI/REPL Single 分支把 `None` 传给 audit emitter，测试只证明 helper 被调用，没有证明事件持久化。
   修复后调用方 audit sink 贯穿 CLI、REPL 与 Loop；安装后的 `run`、`loop`、REPL 默认使用
   `~/.forgeagent/audit.jsonl`。初始化失败在任务执行前返回 2，并输出不含路径和目标的固定错误；
   注入 sink 始终优先。
2. REPL 缺少 `/single <goal>`。修复补齐命令分发、帮助和补全，并记录 `reason=explicit`、
   `requested_mode=single`。
3. Loop 把无模式输入误记为显式 Single。修复在 checkpoint 冻结 `collaboration_mode_source`，CLI 与
   HTTP 未传模式投影 `default`，显式 single/duo/triad 投影 `explicit`，resume 复用冻结来源。
4. legacy Duo/Triad checkpoint 缺来源字段时被错误默认为 default。迁移规则只对旧格式推导：
   Duo/Triad 为 explicit，Single 或缺模式为 default；新格式的显式 Single 保持 explicit。
5. 单次路由审计的敏感边界与重复计数需要真实事件验证。测试现在断言 Single/Duo/Triad 各入口只
   产生一次有界 route event，且 payload 不含 goal、argv、path 或检查内容。

## 独立验证证据

- 最终审查修复受影响集合：`532 passed, 10 skipped`。
- 扩大 M27 回归：`582 passed, 10 skipped`。
- 当前沙箱可执行仓库基线：`2336 passed, 22 skipped`。
- 未排除完整尝试：`12 failed, 2339 passed, 22 skipped`；11 项 loopback 与 1 项隔离 packaging
  环境失败在主验证报告逐项保留。
- Ruff check、115 files format、OpenSpec strict `21/21`、Golden `20/20`、离线 wheel/sdist build
  与 diff check 通过。

## 已知边界

- Reviewer 最终复审本身为静态审查，没有重复运行测试；测试证据由主代理独立执行并记录在验证报告。
- 当前沙箱不能为 11 项 M16 黑盒分配 loopback port，隔离 packaging 也不能在线解析 Hatchling。
- M25 派生输出不承诺强制终止、文件系统损坏或外部并发改写下的跨文件原子性；状态不确定时返回
  非零并保留恢复证据。
