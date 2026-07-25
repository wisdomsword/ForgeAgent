## 1. Evaluator 隔离检查与取消边界

- [ ] 1.1 以失败测试定义 `CheckDefinition`、`RunCheck` 仅接收检查 ID、默认不注册和未知 ID 不启动子进程
- [ ] 1.2 以失败测试定义临时副本排除规则、无 shell/最小环境/固定 cwd、输出脱敏与上限、退出码和清理
- [ ] 1.3 以失败测试定义 timeout/cancel 终止检查进程组，并验证取消后不启动下一协作角色或 rejection attempt
- [ ] 1.4 实现最小 `RunCheck` 工具、registry 接线和宿主注入接口，不扩大 CLI/HTTP 请求 schema 或普通 Evaluator 权限

## 2. MCP 与搜索可靠性

- [ ] 2.1 将永久 skip 的 MCP hung-call 占位改为短 deadline 本地回归，验证固定 timeout、迟到结果隔离和有界 close
- [ ] 2.2 以失败测试定义搜索首选引擎网络失败、非成功状态和零结果时的单次固定 fallback，以及 blocked/unavailable/zero 的最终优先级
- [ ] 2.3 实现双引擎有界 fallback，确保每次请求继续独立经过既有 SSRF、redirect、scheme 和 proxy 策略

## 3. P2/P3 证据与裁决

- [ ] 3.1 在可用环境运行 container 真实集成矩阵；若 Docker/镜像或 Linux/Podman 环境缺失，记录精确阻塞而不伪造通过
- [ ] 3.2 使用现有凭证运行既有 5 项 real-model golden、credentialed Evaluator 和小型 single/Triad 对比，记录模型、费用边界、原始通过率与失败原因
- [ ] 3.3 复核 native tool-call 流式聚合已有实现与回归；为持久 REPL 历史、语义摘要、音视频和响应侧多模态记录明确重启触发条件
- [ ] 3.4 更新 README、ACTION_PLAN、威胁模型、协作文档与里程碑续接状态，只陈述已验证保证和本机证据

## 4. 验证与收尾

- [ ] 4.1 运行相关专项、完整 pytest、Ruff format/check、离线 golden、wheel/sdist、OpenSpec strict 和 diff check
- [ ] 4.2 完成两轮需求/设计/实现自审与独立代码审查，修复所有 Critical/High/Important 问题
- [ ] 4.3 生成验证报告和里程碑收尾记录，归档 change，并按验证结果处理工作分支
