# M43 Python 执行路径 Rewrite / Dependency Baseline

- 测量日期：2026-07-31
- 基线提交：`a14630ff`
- evidence schema：`forgeagent.executor-rewrite-baseline.v1`
- 最终 verdict：`keep_python`
- 适用范围：`TrustedBackend`、`RestrictedBackend` 与条件可用的 `ContainerBackend`

## 结论

两次同机、同命令测量均未发现 Python 执行路径达到预先固定的性能、可靠性或维护成本瓶颈阈值。最终 evidence 中 trusted trivial execute 中位数为 `0.010625 ms`；restricted 中位数为 `108.947834 ms`、吞吐为 `9.077731 ops/s`，分别满足 `<= 1.0 ms`、`<= 250.0 ms` 和 `>= 4.0 ops/s`。restricted 的 20/20 正常执行、worker crash 后恢复和 timeout 后恢复全部成功；两个失败 block 各自在临时允许目录写入一次哨兵，宿主观测到每个哨兵恰好一个字节，因此不是硬编码的“未重放”声明。

本机 container CLI/daemon/固定 `python:3.11-slim` 镜像组合未满足离线可用条件，报告状态为 `not_available`，不是通过或已测量。`rustc` 与 `cargo` 虽存在，但没有维护所有者，也没有完成构建、排障、打包、剖析和回滚演练，因此 team capability 为 `not_ready`。

M43 的 `keep_python` 不授权 Rust 重写，不新增依赖，也不批准任何运行时切换。未来只有出现真实需求、同一指标在同机干净复测后仍越阈，并补齐兼容、团队能力和回滚证据，才可另建 full Comet change 做单模块试验。

## 六项门禁

| metric | baseline | threshold | evidence | migration | rollback trigger |
| --- | --- | --- | --- | --- | --- |
| performance | 第二轮：trusted median `0.010625 ms`；restricted median `108.947834 ms`、`9.077731 ops/s`；container `not_available` | trusted median `> 1.0 ms`；restricted median `> 250.0 ms` 或 `< 4.0 ops/s`；越阈还须同机干净复测和真实需求 | `executor-rewrite-baseline.json` 的 15 个原始样本、`perf_counter_ns` 聚合；首轮聚合见下文 | 独立 full change 只替换一个内部模块，保留 Python path | 干净复测未达改善目标、p95 回归，或把 container 开销误归因于 Python |
| reliability | trusted `20/20`、restricted `20/20`；crash/timeout 均形成结构化失败且下一 block 成功 | 正常控制面失败 `0`；crash/timeout recovery 必须为 `true`；禁止失败 block 无条件重放 | 真实 subprocess fault injection；每个故障 block 写一次临时哨兵，最终均精确为一个字节；现有 executor/restricted/container/escape 专项 | 旧路径与现有 one-shot JSON worker protocol 全程保留 | 任一恢复失败、控制面崩溃、状态污染或无条件重放 |
| maintenance cost | `executor.py` 457 行、`_sandbox_worker.py` 238 行、`runtime.py` 55 行，共 750 行；直接运行时依赖 8 | 当前边界 `> 1000` 行或直接依赖 `> 8` 才构成候选瓶颈；未来候选模块 `<= 400` 行且新增依赖为 0 | 标准库 AST/字节统计与 `tomllib` 依赖计数 | 候选保持单模块，不引入 FFI framework、生成器、注册器或第二套 protocol | 需要新依赖/抽象层，或候选超过 400 行才能成立 |
| compatibility | `ExecResult` 五字段、三 backend 名称、restricted JSON state roundtrip 和 one-shot JSON protocol 均保持 | 现有契约测试失败 0；public interface 变化 0；字段和 state roundtrip 精确保持 | `tests/test_executor.py`、`test_restricted_backend.py`、`test_container_backend.py`、`test_escape.py`、`test_policy_wiring.py` | 未来试验保持 backend API、worker frame、CLI/config/HTTP 不变 | 任一结果 shape、sandbox、状态、CLI、配置或 HTTP 契约变化 |
| team capability | Python/uv/pytest/Ruff 已验证；`rustc/cargo` 可执行；候选维护演练 `not_run` | 必须有明确 owner，并完成目标平台 build、debug、package、profiling、rollback 演练 | evidence 只记录工具存在，不把安装状态当作团队能力；当前 status `not_ready` | 试验前完成所有权、交接和五类演练 | 无人能在目标平台诊断并回退候选，立即停止 |
| migration/rollback risk | M43 runtime/schema/config/data 变化均为 0；legacy Python path 保留 | 只允许单模块；保留旧路径；禁止状态转换和无条件重放 | technical design、base-ref diff、最终归因审查；当前 status `ready` | 新 change 内显式 selector/fallback，零持久化迁移 | 需要数据转换、旧路径提前删除、故障污染状态或无法单独关闭候选 |

## 两次同口径结果

| run | trusted median | restricted median | restricted throughput | performance status | verdict |
| --- | ---: | ---: | ---: | --- | --- |
| 首轮 | `0.009959 ms` | `109.946416 ms` | `9.185010 ops/s` | `within_threshold` | `keep_python` |
| 最终 | `0.010625 ms` | `108.947834 ms` | `9.077731 ops/s` | `within_threshold` | `keep_python` |

最终 15 个原始 timing samples、环境摘要与六项完整记录位于
`docs/evaluation/m43/executor-rewrite-baseline.json`。首轮没有越阈，因此不存在需要确认的 performance bottleneck；第二轮用于证明结论不依赖单次偶然样本，未修改任何 threshold。

## 可复现命令

```bash
rtk uv run python scripts/m43_executor_rewrite_baseline.py \
  --output docs/evaluation/m43/executor-rewrite-baseline.json
rtk uv run pytest -q tests/test_m43_executor_rewrite_baseline.py \
  tests/test_executor.py tests/test_restricted_backend.py \
  tests/test_container_backend.py tests/test_escape.py tests/test_policy_wiring.py
```

脚本只调用本地工具，不访问网络、不拉取镜像、不读取凭据。计时是本机 evidence，不是跨平台 SLA。Docker/Linux 或真实 container 未运行时必须保留 `not_available`/未验证口径，不能写成 pass。

## 未来单模块试验门禁

后续试验只有在以下条件同时满足时才能立项：

1. 六项记录继续具备 baseline、threshold、evidence、migration 和 rollback trigger；
2. 至少一项真实使用瓶颈在同机干净复测后确认越阈；
3. compatibility、team capability、migration/rollback risk 均为 `ready`；
4. 对目标平台和边界存在真实 verifier；
5. 单独建立 full Comet change，保留当前 Python 实现和确定性回滚路径。

M43 没有达到上述试验触发条件。推荐保持现有 Python 执行路径，待真实需求和新证据出现后重新测量。
