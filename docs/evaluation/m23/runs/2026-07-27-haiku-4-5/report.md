# M23 Single/Duo/Triad Quality-Cost Evaluation

## Protocol
- Model ID: `claude-haiku-4-5`
- Repetitions: 3
- Protocol SHA-256: `cf37be264871d983f09d6a9a2a0453306e8f6c9c2d9e4bb16c43ad59adbb1fc3`

## Environment
- Environment schema: `forgeagent.m23.mode-evaluation.environment/v1`
- Environment SHA-256: `b01e489b8c5cc54f1dda6025a319f2cb24a8298c677761451be7058fa4ce0e1e`

## Evidence Completeness
- Runs: 27/27

## Metrics By Mode
### Single
- Task completion: 3/9 (0.333)
- First acceptance: N/A
- Rejections: N/A
- Corrections: N/A
- Model calls: {"max": 10, "mean": 7.555555555555555, "median": 8, "min": 4, "sum": 68}
- Provider attempts: {"max": 10, "mean": 7.555555555555555, "median": 8, "min": 4, "sum": 68}
- Tokens: {"cached_tokens": {"max": 0, "mean": 0.0, "median": 0, "min": 0, "sum": 0}, "input_tokens": {"max": 37349, "mean": 23416.88888888889, "median": 22018, "min": 9003, "sum": 210752}, "output_tokens": {"max": 6299, "mean": 4100.333333333333, "median": 3555, "min": 2408, "sum": 36903}, "reasoning_tokens": {"max": 0, "mean": 0.0, "median": 0, "min": 0, "sum": 0}, "usage_missing_calls": 0}
- End-to-end latency: {"max": 72.02796495798975, "mean": 44.89681366188193, "median": 39.514617749955505, "min": 25.58220920804888, "sum": 404.07132295693737}
- Usage missing rate: 0/68 (0.000)

### Duo
- Task completion: 3/9 (0.333)
- First acceptance: 7/9 (0.778)
- Rejections: {"max": 2, "mean": 0.4444444444444444, "median": 0, "min": 0, "sum": 4}
- Corrections: {"max": 2, "mean": 0.4444444444444444, "median": 0, "min": 0, "sum": 4}
- Model calls: {"max": 29, "mean": 12.666666666666666, "median": 11, "min": 6, "sum": 114}
- Provider attempts: {"max": 29, "mean": 12.666666666666666, "median": 11, "min": 6, "sum": 114}
- Tokens: {"cached_tokens": {"max": 0, "mean": 0.0, "median": 0, "min": 0, "sum": 0}, "input_tokens": {"max": 50990, "mean": 17804.88888888889, "median": 15032, "min": 5556, "sum": 160244}, "output_tokens": {"max": 14631, "mean": 6367.555555555556, "median": 4695, "min": 3129, "sum": 57308}, "reasoning_tokens": {"max": 0, "mean": 0.0, "median": 0, "min": 0, "sum": 0}, "usage_missing_calls": 0}
- End-to-end latency: {"max": 182.3452629999956, "mean": 78.9013458981127, "median": 50.79050941707101, "min": 28.85646737506613, "sum": 710.1121130830143}
- Usage missing rate: 0/114 (0.000)

### Triad
- Task completion: 2/9 (0.222)
- First acceptance: 7/9 (0.778)
- Rejections: {"max": 2, "mean": 0.2222222222222222, "median": 0, "min": 0, "sum": 2}
- Corrections: {"max": 2, "mean": 0.2222222222222222, "median": 0, "min": 0, "sum": 2}
- Model calls: {"max": 29, "mean": 13.555555555555555, "median": 14, "min": 2, "sum": 122}
- Provider attempts: {"max": 29, "mean": 13.555555555555555, "median": 14, "min": 2, "sum": 122}
- Tokens: {"cached_tokens": {"max": 0, "mean": 0.0, "median": 0, "min": 0, "sum": 0}, "input_tokens": {"max": 65486, "mean": 25023.444444444445, "median": 22250, "min": 1089, "sum": 225211}, "output_tokens": {"max": 20905, "mean": 7814.888888888889, "median": 6762, "min": 1207, "sum": 70334}, "reasoning_tokens": {"max": 0, "mean": 0.0, "median": 0, "min": 0, "sum": 0}, "usage_missing_calls": 0}
- End-to-end latency: {"max": 197.51893166697118, "mean": 78.04255958347737, "median": 73.59427712508477, "min": 13.137026083073579, "sum": 702.3830362512963}
- Usage missing rate: 0/122 (0.000)

## Metrics By Task
- `csv-region-summary`: 3 runs per mode
- `fix-range-compression`: 3 runs per mode
- `normalize-events`: 3 runs per mode

## Failures And Usage Gaps
- Failed runs: ["01-csv-region-summary-r1-single", "02-csv-region-summary-r1-duo", "03-csv-region-summary-r1-triad", "04-csv-region-summary-r2-duo", "05-csv-region-summary-r2-triad", "06-csv-region-summary-r2-single", "07-csv-region-summary-r3-triad", "08-csv-region-summary-r3-single", "09-csv-region-summary-r3-duo", "14-fix-range-compression-r2-triad", "19-normalize-events-r1-single", "20-normalize-events-r1-duo", "21-normalize-events-r1-triad", "22-normalize-events-r2-duo", "23-normalize-events-r2-triad", "24-normalize-events-r2-single", "25-normalize-events-r3-triad", "26-normalize-events-r3-single", "27-normalize-events-r3-duo"]
- Usage-missing runs: []

## Limitations
- 固定任务且每种模式仅重复三次，属于小样本描述性证据。
- 服务端模型权重版本无法由本地独立验证。

这些结果来自固定协议下的小样本描述性评估；本报告不自动宣称 Triad 优于 Single，也不据此作产品决策。
