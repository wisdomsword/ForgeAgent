## 1. FileWrite descriptor 边界

- [x] 1.1 新增失败测试，覆盖最终目标 symlink 替换、父目录 symlink 替换、根目录绑定替换和固定失败信息不变。
- [x] 1.2 实现基于 descriptor 的 `O_NOFOLLOW` 父目录遍历与最终写入，不新增依赖或公共 API 变更。
- [ ] 1.3 运行 FileWrite、headless 确认、golden 和威胁模型专项回归。

## 2. 项目 Memory 跨进程更新

- [ ] 2.1 新增失败测试，以两个独立 manager/进程覆盖不同 key 合并、同 key 后锁获得者胜、不安全 lock path 和锁/写入失败回滚。
- [ ] 2.2 实现稳定私有的 Memory lock file，以及锁内磁盘重载、准入/限额检查、合并和原子替换。
- [ ] 2.3 运行 Memory、CLI reload、identity 和 audit 专项回归。

## 3. Loop checkpoint 跨进程 CAS

- [ ] 3.1 新增失败测试，覆盖同 revision 重叠保存、重叠创建、不安全 lock file 和不同 Loop ID 并行。
- [ ] 3.2 实现每个 Loop 独立的稳定私有 lock file，以及锁内 create/save 校验和原子替换。
- [ ] 3.3 运行 Loop store、runner、HTTP 和 collaboration resume 专项回归。

## 4. 契约与完成门禁

- [ ] 4.1 更新 `docs/threat-model.md` 和受影响的公开文档，说明增强后的本地文件系统保证以及 advisory lock/网络文件系统残余边界。
- [ ] 4.2 运行格式化、Ruff、专项测试、完整 pytest、golden 20/20、包构建、OpenSpec strict 和 `git diff --check`。
- [ ] 4.3 完成两轮最终自审和独立代码审查；修复全部 Critical/Important 发现并记录验证报告。
