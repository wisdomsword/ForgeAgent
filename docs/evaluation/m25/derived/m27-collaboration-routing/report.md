# M27 M25 协作路由派生分析

## 结论

M27 不恢复任何任务类别的自动 Triad：没有类别的 Triad solved rate 严格高于 Single。
默认保持 Single；用户显式选择或可信宿主已绑定冻结检查时仍可使用 Triad。

M25 早于 M26 冻结检查绑定。下列误完成和终止原因是历史结果，不能作为当前 evidence-bound Triad 质量的证明。

## 冻结输入

- runs: 270
- protocol SHA-256: `42fc536b22472d175c97f38c1fe2b4ad14f607fdf890c2fa2c4a700fee79e93c`
- environment SHA-256: `d5a2ca6bac51c03c816f23eb280b0f3f764f4bf8aa6d7f33cd95981a963fecd6`
- frozen manifest SHA-256: `06d9e38f54772767b91fcea0552a0b819005b099ab3cc818a90ef1dacc62d355`

## 任务类别比较

| 类别 | Single solved | Triad solved | Single 延迟均值 (s) | Triad 延迟均值 (s) | Single 调用均值 | Triad 调用均值 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| baseline | 73.3% | 73.3% | 73.312 | 144.486 | 5.97 | 11.63 |
| bugfix | 85.0% | 45.0% | 78.519 | 166.489 | 5.85 | 9.30 |
| feature | 20.0% | 5.0% | 124.789 | 270.645 | 7.05 | 9.25 |
| refactor | 45.0% | 15.0% | 84.121 | 248.222 | 7.30 | 11.00 |

## 误完成与终止原因

误完成定义为 `runtime_completed == true && solved == false`。率同时以 scheduled runs 和 runtime-completed runs 为分母；原因按 raw `runtime_reason` 原样分类。完整机器读数见 `analysis.json`。

## 策略裁决

quality eligible: none
automatic Triad restored: none
