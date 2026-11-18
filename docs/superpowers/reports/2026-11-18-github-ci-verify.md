# GitHub CI 首次实跑证据

用户授权将当前 main 推送至 `wisdomsword/ForgeAgent`。保留 GitLab origin，新增 github 远端，只推 main，没有强推、推 tag 或发布软件包。

## 已验证运行

- [Verify / push / 44272935741](https://github.com/wisdomsword/ForgeAgent/actions/runs/44272935741)
- 源码提交：`bde9d225e344e4bd1ef87117b4d8f26e27c78714`。
- `offline-verification` 与 `linux-docker-container` 两个 job 均为 success，运行总体为 success。
- 首次状态查询存在延迟，额外手动触发的重复运行 `44272945262` 已取消，不计为验收结果。

## 离线门禁

原生 GitHub Ubuntu runner 实际输出：

```text
3161 passed, 11 skipped in 267.33s (0:04:27)
Totals: 42 passed, 0 failed (42 items)
```

Ruff lint、格式检查、离线 Golden 20/20、严格规格检查、wheel 和 sdist 构建均成功。该 job 没有预拉取容器镜像，十项容器测试作为跳过记录；另有可选跨解释器检查跳过。容器专用 job 独立强制十项零跳过，不把两个 job 的测试数相加后冒充一次全量测试。

## Linux Docker 与安装后检查

日志记录 Ubuntu 24.04.5 LTS、x86_64、内核 `7.0.0-1017-azure`，Docker client/server 28.0.4。使用 GitHub host daemon 与同路径挂载，非 root 运行。

```text
10 passed, 4 deselected in 12.76s
```

下载后的 `container-junit.xml` 已解析并断言：tests=10、failures=0、errors=0、skipped=0。

`rc-smoke.json` 记录 Python 3.11.18，`passed: true`，六项全部 passed：clean-wheel、cli、http、single、duo、triad。这里的协作安装冒烟使用确定性客户端，与[真实模型复验](2026-11-18-fix-restricted-stdlib-imports-verify.md)分别计证。

候选 wheel SHA-256：`a906d7af7cfd45892ed6d48112477f664bcff4347632331832bd5d7949b39469`，与本地最终候选一致。

## 原始证据与适用范围

原始运行元数据、完整日志、离线构建/Golden 产物和 Docker JUnit/smoke 产物保存在忽略的 `artifacts/github-ci/44272935741/`。公开 Actions 页面也保留运行与 artifact 下载入口。

该记录只验证上述提交与 runner tuple，不外推其他架构、Podman、Windows 或后续提交。README 的后续整理会单独提交并触发新 CI；最终结果应查看与最终提交相同 SHA 的运行。

GitHub 有非阻塞提示：所固定的部分 actions 使用 Node 20 元数据，被 runner 强制运行在 Node 24；本次两个 job 通过。升级 actions 版本未纳入本次文档整理。
