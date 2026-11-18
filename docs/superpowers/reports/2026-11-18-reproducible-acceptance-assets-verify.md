# 可复现验收资产验证

日期：2026-11-18。新增资产不改变产品运行时依赖、默认模型或沙箱权限。

## 交付范围

- `docs/dependencies.md`、`CONTRIBUTING.md`：从公开 checkout 安装、开发、构建及可选工具边界。
- `examples/gateway/`：三个文本模型的 registry/routing 示例与五个模型的验收配置。
- `scripts/live_model_acceptance.py`：默认 dry-run；显式付费授权、有限请求预算、环境凭据、独立协作检查和图像尺寸判定。
- `tests/test_live_model_acceptance.py`：离线替身覆盖配置、预算、脱敏、错误候选、尺寸不符、异常图像及证据覆盖边界。

## 实际验证

测试先行的失败结果：

```text
13 failed in 0.32s
```

当时公共入口和示例尚未创建，失败原因为 `public acceptance entry point is missing`
及缺少示例文件；这是预期的 RED 阶段。

完整回归执行结果（当时收集了新增的 19 项用例）：

```text
3181 passed, 11 skipped in 265.70s (0:04:25)
```

之后增加 JSON 转义脱敏和匹配尺寸两项用例，最终定向回归（21 项新增验收测试与
6 项现有文档测试）结果：

```text
27 passed in 0.81s
```

- Ruff check：`All checks passed!`；format：`162 files already formatted`。
- 离线 Golden：20/20。
- OpenSpec strict：归档前 43/43，包括本次 change；归档后主规格校验 42/42。
- wheel/sdist 构建成功；检查两种产物均无 `.cache/` 或 `artifacts/`。
- 默认 `--suite all` 实际执行返回 dry-run，未传付费开关。
- 新增/修改内容扫描已知真实敏感环境值：0 命中。此检查不等于对所有未知秘密的保证。
- 公共文档相对链接有效；README 未引入里程碑编号。

构建首次因沙箱 DNS 限制无法下载 hatchling：

```text
Caused by: error sending request for url (https://pypi.org/simple/hatchling/)
Caused by: client error (Connect)
Caused by: dns error
Caused by: failed to lookup address information: nodename nor servname provided, or not known
```

允许联网后重跑构建成功，没有更改依赖声明或锁文件。

## 边界

本轮没有新增真实收费请求，不把历史模型结果视为新入口的真实服务通过证据。
图像自动检查仅验证 PNG 头部和尺寸，不是完整解码或视觉质量评估。
本地完整回归的 11 项跳过不构成 Docker 集成通过证明；推送后由 GitHub 独立 Linux Docker
job 强制执行十项零跳过测试及安装后六项冒烟。交付结果以最终提交的 GitHub Actions 为准。
原始产物保留在忽略的 artifacts 中，不发布用户环境、凭据或原始模型运行记录。
