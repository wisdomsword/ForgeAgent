# M23 Single/Duo/Triad Quality-Cost Evaluation

## Protocol
- Model ID: `claude-haiku-4-5`
- Repetitions: 3
- Protocol SHA-256: `bb6a9aaded0dee6a3599d9b004e17eeb9543c76cb3c79c284e960786e36383e4`

## Environment
- Environment schema: `forgeagent.m23.mode-evaluation.environment/v1`
- Environment SHA-256: `dc1b5ff1f207971862677f3692a3ad0821ff6b6dd53b885d7f5be2c0b59b6f76`

## Evidence Completeness
- Runs: 27/27

## Metrics By Mode
### Single
- Task completion: 5/9 (0.556)
- First acceptance: N/A
- Rejections: N/A
- Corrections: N/A
- Model calls: {"max": 10, "mean": 8.444444444444445, "median": 9, "min": 4, "sum": 76}
- Provider attempts: {"max": 10, "mean": 8.444444444444445, "median": 9, "min": 4, "sum": 76}
- Tokens: {"cached_tokens": {"max": 0, "mean": 0.0, "median": 0, "min": 0, "sum": 0}, "input_tokens": {"max": 35642, "mean": 25303.0, "median": 27134, "min": 9686, "sum": 227727}, "output_tokens": {"max": 6435, "mean": 4079.222222222222, "median": 3710, "min": 2452, "sum": 36713}, "reasoning_tokens": {"max": 0, "mean": 0.0, "median": 0, "min": 0, "sum": 0}, "usage_missing_calls": 0}
- End-to-end latency: {"max": 84.72946858301293, "mean": 48.930719139015615, "median": 46.68737279204652, "min": 20.0748003750341, "sum": 440.3764722511405}
- Usage missing rate: 0/76 (0.000)

### Duo
- Task completion: 8/9 (0.889)
- First acceptance: 8/9 (0.889)
- Rejections: {"max": 1, "mean": 0.1111111111111111, "median": 0, "min": 0, "sum": 1}
- Corrections: {"max": 1, "mean": 0.1111111111111111, "median": 0, "min": 0, "sum": 1}
- Model calls: {"max": 20, "mean": 10.11111111111111, "median": 9, "min": 2, "sum": 91}
- Provider attempts: {"max": 20, "mean": 10.11111111111111, "median": 9, "min": 2, "sum": 91}
- Tokens: {"cached_tokens": {"max": 0, "mean": 0.0, "median": 0, "min": 0, "sum": 0}, "input_tokens": {"max": 31522, "mean": 14429.888888888889, "median": 11935, "min": 1624, "sum": 129869}, "output_tokens": {"max": 10217, "mean": 4651.111111111111, "median": 4594, "min": 2037, "sum": 41860}, "reasoning_tokens": {"max": 0, "mean": 0.0, "median": 0, "min": 0, "sum": 0}, "usage_missing_calls": 0}
- End-to-end latency: {"max": 125.95393562503159, "mean": 63.54198728235335, "median": 51.94663704105187, "min": 23.653889166074805, "sum": 571.8778855411801}
- Usage missing rate: 0/91 (0.000)

### Triad
- Task completion: 9/9 (1.000)
- First acceptance: 9/9 (1.000)
- Rejections: {"max": 0, "mean": 0.0, "median": 0, "min": 0, "sum": 0}
- Corrections: {"max": 0, "mean": 0.0, "median": 0, "min": 0, "sum": 0}
- Model calls: {"max": 15, "mean": 12.444444444444445, "median": 13, "min": 7, "sum": 112}
- Provider attempts: {"max": 15, "mean": 12.444444444444445, "median": 13, "min": 7, "sum": 112}
- Tokens: {"cached_tokens": {"max": 0, "mean": 0.0, "median": 0, "min": 0, "sum": 0}, "input_tokens": {"max": 33071, "mean": 21493.444444444445, "median": 20312, "min": 7233, "sum": 193441}, "output_tokens": {"max": 10263, "mean": 7395.555555555556, "median": 7611, "min": 4434, "sum": 66560}, "reasoning_tokens": {"max": 0, "mean": 0.0, "median": 0, "min": 0, "sum": 0}, "usage_missing_calls": 0}
- End-to-end latency: {"max": 136.80918516707607, "mean": 79.30039683826423, "median": 74.45505908399355, "min": 39.39735650003422, "sum": 713.7035715443781}
- Usage missing rate: 0/112 (0.000)

## Metrics By Task
- `csv-region-summary`: 3 runs per mode
- `fix-range-compression`: 3 runs per mode
- `normalize-events`: 3 runs per mode

## Failures And Usage Gaps
- Failed runs: ["01-csv-region-summary-r1-single", "08-csv-region-summary-r3-single", "18-fix-range-compression-r3-duo", "24-normalize-events-r2-single", "26-normalize-events-r3-single"]
- Usage-missing runs: []

## Limitations
- 固定任务且每种模式仅重复三次，属于小样本描述性证据。
- 服务端模型权重版本无法由本地独立验证。

这些结果来自固定协议下的小样本描述性评估；本报告不自动宣称 Triad 优于 Single，也不据此作产品决策。
