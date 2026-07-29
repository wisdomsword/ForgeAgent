## 1. 正式版合同冻结

- [x] 1.1 先将发布文档合同改为正式版期望并验证其因现有 RC 状态而失败
- [x] 1.2 更新 README 与 `0.1.0` 正式发布说明，保留五类已知限制，并使聚焦合同测试通过

## 2. 精确候选验证

- [ ] 2.1 完成本地 Ruff、全量 pytest、Golden、OpenSpec strict、build、制品元数据/内容和 clean-wheel 发布冒烟
- [ ] 2.2 提交并推送发布准备改动，验证该精确提交的 required Linux pipeline 全部成功

## 3. 生产发布与回读

- [ ] 3.1 安全确认生产 PyPI 名称/版本和凭据，创建本地 annotated `v0.1.0` tag，并上传唯一 wheel/sdist
- [ ] 3.2 回读 PyPI JSON 和文件摘要、从 PyPI 下载 clean-wheel 冒烟，并推送/回读远端 tag 到同一提交

## 4. 证据与收尾

- [ ] 4.1 记录正式发布证据、里程碑续接和最终限制，运行两轮一致性审查并修复发现的问题
- [ ] 4.2 完成 OpenSpec/Comet 验证、规范同步与归档，提交并推送收尾证据
