## 1. 复现与修复

- [x] 1.1 以 TDD 覆盖 CLI 私有 context JSON 覆盖、默认加载不变和无效覆盖失败
- [x] 1.2 让 M22 脚本仅对子进程设置 4000/2000 feedback 预算并保持原生 stdio

## 2. 验证

- [x] 2.1 运行专项、Ruff、完整 pytest、OpenSpec strict，并复核真实失败现场不再受 40/120 用户配置影响
