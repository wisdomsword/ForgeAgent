## 1. 三态模型

- [x] 1.1 写 RED 回归，固定三态推导、旧布尔构造兼容和矛盾状态拒绝。
- [x] 1.2 实现权威 `completion_state` 与 verified-only `completed` 兼容投影。

## 2. 公开投影

- [x] 2.1 写 RED 并修改 CLI，使 prose 回答显示 `answered (unverified)` 而非 `completed`。
- [x] 2.2 为 HTTP 和 task outcome audit 追加一致三态，保持 Loop/evaluation/golden verified-only 判定。
- [x] 2.3 运行 Task、CLI、HTTP、Loop 与 evaluation 聚焦回归。
