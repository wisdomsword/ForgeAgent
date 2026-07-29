## 1. RC smoke 合同

- [x] 1.1 为 clean-wheel 环境隔离、报告 schema、失败非零与脱敏边界增加测试。
- [x] 1.2 为安装后 CLI、真实 loopback HTTP 和显式 Single/Duo/Triad 离线终态增加测试。

## 2. RC smoke 实现

- [x] 2.1 实现单一 `0.1.0` RC smoke harness：构建/接收 wheel、创建 Python 3.11 venv、安装并验证模块与 console script 来源。
- [x] 2.2 实现 CLI/HTTP/Single/Duo/Triad 子检查和原子、版本化 JSON 报告，不新增运行时依赖或产品命令。
- [ ] 2.3 让 packaging 合同调用同一 harness，并保留现有 wheel/sdist 内容负向边界。

## 3. Linux Docker CI

- [ ] 3.1 在既有 required Linux Docker job 中构建候选 wheel、以非 root 用户运行 RC smoke，并校验六类证据全部通过。
- [ ] 3.2 发布 RC JSON 与既有 container JUnit artifact；保持十项 container integration 精确计数、零 skip 约束。

## 4. 发布冻结

- [ ] 4.1 编写 `0.1.0` RC 发布说明，冻结安装、能力、验证口径、正式发布阻塞条件和五类已知限制。
- [ ] 4.2 更新 README、平台支持矩阵和文档合同测试，确保不把未执行或历史证据描述为当前通过。

## 5. 验证与收尾

- [ ] 5.1 运行 RC/packaging/CLI/HTTP/协作专项、Ruff、完整 pytest、Golden 20/20、OpenSpec strict、build 与本机可用的 Docker 门禁。
- [ ] 5.2 完成独立代码审查与两轮最终一致性复审，修复全部发现并记录无法执行的环境证据。
- [ ] 5.3 生成 M28 验证报告与 milestone，更新 `ACTION_PLAN.md` 和 `milestones/latest`，归档 change。
