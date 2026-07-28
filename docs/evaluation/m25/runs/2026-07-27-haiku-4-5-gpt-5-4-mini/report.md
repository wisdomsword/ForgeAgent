# M25 Programming Mode Quality-Cost Evaluation

## Protocol
- Models: ["claude-haiku-4-5", "gpt-5.4-mini"]
- Tasks: 9
- Repetitions per model and mode: 5
- Protocol SHA-256: `42fc536b22472d175c97f38c1fe2b4ad14f607fdf890c2fa2c4a700fee79e93c`

## Environment
- Environment schema: `forgeagent.m25.mode-evaluation.environment/v1`
- Environment SHA-256: `d5a2ca6bac51c03c816f23eb280b0f3f764f4bf8aa6d7f33cd95981a963fecd6`

## Evidence Completeness
- Runs: 270/270

## Model: claude-haiku-4-5

### Mode: single
- Scheduled runs: 45
- Task completion: 23/45 (0.511)
- First acceptance: N/A
- Rejections: N/A
- Corrections: N/A
- Tokens: {"cached_tokens": {"max": 0, "mean": 0.0, "median": 0, "min": 0, "sum": 0}, "input_tokens": {"max": 65802, "mean": 26451.6, "median": 23925, "min": 4189, "sum": 1190322}, "output_tokens": {"max": 12867, "mean": 4387.333333333333, "median": 3383, "min": 938, "sum": 197430}, "reasoning_tokens": {"max": 0, "mean": 0.0, "median": 0, "min": 0, "sum": 0}, "usage_missing_calls": 0}
- Model calls: {"max": 10, "mean": 7.777777777777778, "median": 8, "min": 2, "sum": 350}
- Provider attempts: {"max": 10, "mean": 7.777777777777778, "median": 8, "min": 2, "sum": 350}
- End-to-end latency: {"max": 155.6252554579405, "mean": 56.97717275923739, "median": 46.182245458010584, "min": 12.16546233301051, "sum": 2563.9727741656825}
- Usage missing rate: 0/350 (0.000)

### Mode: duo
- Scheduled runs: 45
- Task completion: 18/45 (0.400)
- First acceptance: 27/45 (0.600)
- Rejections: {"max": 2, "mean": 0.28888888888888886, "median": 0, "min": 0, "sum": 13}
- Corrections: {"max": 2, "mean": 0.28888888888888886, "median": 0, "min": 0, "sum": 13}
- Tokens: {"cached_tokens": {"max": 0, "mean": 0.0, "median": 0, "min": 0, "sum": 0}, "input_tokens": {"max": 42325, "mean": 15794.244444444445, "median": 14025, "min": 1956, "sum": 710741}, "output_tokens": {"max": 14405, "mean": 5978.666666666667, "median": 4737, "min": 923, "sum": 269040}, "reasoning_tokens": {"max": 0, "mean": 0.0, "median": 0, "min": 0, "sum": 0}, "usage_missing_calls": 0}
- Model calls: {"max": 25, "mean": 11.355555555555556, "median": 11, "min": 2, "sum": 511}
- Provider attempts: {"max": 25, "mean": 11.355555555555556, "median": 11, "min": 2, "sum": 511}
- End-to-end latency: {"max": 382.1535149590345, "mean": 88.20431382789329, "median": 64.05488512502052, "min": 11.925534666981548, "sum": 3969.1941222551977}
- Usage missing rate: 0/511 (0.000)

### Mode: triad
- Scheduled runs: 45
- Task completion: 23/45 (0.511)
- First acceptance: 35/45 (0.778)
- Rejections: {"max": 2, "mean": 0.13333333333333333, "median": 0, "min": 0, "sum": 6}
- Corrections: {"max": 2, "mean": 0.13333333333333333, "median": 0, "min": 0, "sum": 6}
- Tokens: {"cached_tokens": {"max": 0, "mean": 0.0, "median": 0, "min": 0, "sum": 0}, "input_tokens": {"max": 48680, "mean": 16331.666666666666, "median": 13458, "min": 735, "sum": 734925}, "output_tokens": {"max": 19897, "mean": 6836.333333333333, "median": 6870, "min": 758, "sum": 307635}, "reasoning_tokens": {"max": 0, "mean": 0.0, "median": 0, "min": 0, "sum": 0}, "usage_missing_calls": 1}
- Model calls: {"max": 30, "mean": 10.4, "median": 9, "min": 2, "sum": 468}
- Provider attempts: {"max": 30, "mean": 10.4, "median": 9, "min": 2, "sum": 468}
- End-to-end latency: {"max": 319.0958830830641, "mean": 84.36034844811333, "median": 70.6170607500244, "min": 8.589282416040078, "sum": 3796.2156801651}
- Usage missing rate: 1/468 (0.002)

## Model: gpt-5.4-mini

### Mode: single
- Scheduled runs: 45
- Task completion: 30/45 (0.667)
- First acceptance: N/A
- Rejections: N/A
- Corrections: N/A
- Tokens: {"cached_tokens": {"max": 27392, "mean": 9892.977777777778, "median": 9216, "min": 0, "sum": 445184}, "input_tokens": {"max": 111736, "mean": 23557.88888888889, "median": 19322, "min": 5933, "sum": 1060105}, "output_tokens": {"max": 28250, "mean": 7462.933333333333, "median": 6509, "min": 2762, "sum": 335832}, "reasoning_tokens": {"max": 19180, "mean": 5272.822222222222, "median": 4678, "min": 1139, "sum": 237277}, "usage_missing_calls": 0}
- Model calls: {"max": 10, "mean": 5.177777777777778, "median": 5, "min": 2, "sum": 233}
- Provider attempts: {"max": 10, "mean": 5.177777777777778, "median": 5, "min": 2, "sum": 233}
- End-to-end latency: {"max": 477.6595427909633, "mean": 119.64377432134158, "median": 106.18530449992977, "min": 51.62054608401377, "sum": 5383.969844460371}
- Usage missing rate: 0/233 (0.000)

### Mode: duo
- Scheduled runs: 45
- Task completion: 11/45 (0.244)
- First acceptance: 7/45 (0.156)
- Rejections: {"max": 2, "mean": 1.2, "median": 2, "min": 0, "sum": 54}
- Corrections: {"max": 2, "mean": 1.2, "median": 2, "min": 0, "sum": 54}
- Tokens: {"cached_tokens": {"max": 29696, "mean": 9750.755555555555, "median": 7680, "min": 1792, "sum": 438784}, "input_tokens": {"max": 59333, "mean": 21767.37777777778, "median": 16641, "min": 4199, "sum": 979532}, "output_tokens": {"max": 38257, "mean": 15882.288888888888, "median": 14480, "min": 1292, "sum": 714703}, "reasoning_tokens": {"max": 32597, "mean": 12821.044444444444, "median": 11477, "min": 903, "sum": 576947}, "usage_missing_calls": 0}
- Model calls: {"max": 21, "mean": 8.422222222222222, "median": 8, "min": 2, "sum": 379}
- Provider attempts: {"max": 21, "mean": 8.422222222222222, "median": 8, "min": 2, "sum": 379}
- End-to-end latency: {"max": 710.4091987500433, "mean": 272.51618528796047, "median": 247.20546020800248, "min": 28.58865675004199, "sum": 12263.228337958222}
- Usage missing rate: 0/379 (0.000)

### Mode: triad
- Scheduled runs: 45
- Task completion: 12/45 (0.267)
- First acceptance: 8/45 (0.178)
- Rejections: {"max": 2, "mean": 1.4222222222222223, "median": 2, "min": 0, "sum": 64}
- Corrections: {"max": 2, "mean": 1.4222222222222223, "median": 2, "min": 0, "sum": 64}
- Tokens: {"cached_tokens": {"max": 28672, "mean": 10114.844444444445, "median": 9984, "min": 2560, "sum": 455168}, "input_tokens": {"max": 97085, "mean": 28021.022222222222, "median": 24082, "min": 5923, "sum": 1260946}, "output_tokens": {"max": 43819, "mean": 18883.244444444445, "median": 19205, "min": 2185, "sum": 849746}, "reasoning_tokens": {"max": 34309, "mean": 14589.511111111111, "median": 14289, "min": 1088, "sum": 656528}, "usage_missing_calls": 0}
- Model calls: {"max": 25, "mean": 10.488888888888889, "median": 10, "min": 3, "sum": 472}
- Provider attempts: {"max": 25, "mean": 10.488888888888889, "median": 10, "min": 3, "sum": 472}
- End-to-end latency: {"max": 1029.0639354579616, "mean": 316.566428406578, "median": 305.98684804106597, "min": 35.937285000109114, "sum": 14245.489278296009}
- Usage missing rate: 0/472 (0.000)

## Task Families

| Family | Model | Mode | Runs | Completion |
| --- | --- | --- | ---: | --- |
| baseline | claude-haiku-4-5 | single | 15 | 10/15 (0.667) |
| baseline | claude-haiku-4-5 | duo | 15 | 10/15 (0.667) |
| baseline | claude-haiku-4-5 | triad | 15 | 13/15 (0.867) |
| baseline | gpt-5.4-mini | single | 15 | 12/15 (0.800) |
| baseline | gpt-5.4-mini | duo | 15 | 7/15 (0.467) |
| baseline | gpt-5.4-mini | triad | 15 | 9/15 (0.600) |
| bugfix | claude-haiku-4-5 | single | 10 | 8/10 (0.800) |
| bugfix | claude-haiku-4-5 | duo | 10 | 6/10 (0.600) |
| bugfix | claude-haiku-4-5 | triad | 10 | 7/10 (0.700) |
| bugfix | gpt-5.4-mini | single | 10 | 9/10 (0.900) |
| bugfix | gpt-5.4-mini | duo | 10 | 1/10 (0.100) |
| bugfix | gpt-5.4-mini | triad | 10 | 2/10 (0.200) |
| feature | claude-haiku-4-5 | single | 10 | 0/10 (0.000) |
| feature | claude-haiku-4-5 | duo | 10 | 0/10 (0.000) |
| feature | claude-haiku-4-5 | triad | 10 | 0/10 (0.000) |
| feature | gpt-5.4-mini | single | 10 | 5/10 (0.500) |
| feature | gpt-5.4-mini | duo | 10 | 2/10 (0.200) |
| feature | gpt-5.4-mini | triad | 10 | 1/10 (0.100) |
| refactor | claude-haiku-4-5 | single | 10 | 5/10 (0.500) |
| refactor | claude-haiku-4-5 | duo | 10 | 2/10 (0.200) |
| refactor | claude-haiku-4-5 | triad | 10 | 3/10 (0.300) |
| refactor | gpt-5.4-mini | single | 10 | 4/10 (0.400) |
| refactor | gpt-5.4-mini | duo | 10 | 1/10 (0.100) |
| refactor | gpt-5.4-mini | triad | 10 | 0/10 (0.000) |

## Tasks

| Task | Family | Model | Mode | Runs | Completion |
| --- | --- | --- | --- | ---: | --- |
| csv-region-summary | baseline | claude-haiku-4-5 | single | 5 | 3/5 (0.600) |
| csv-region-summary | baseline | claude-haiku-4-5 | duo | 5 | 4/5 (0.800) |
| csv-region-summary | baseline | claude-haiku-4-5 | triad | 5 | 5/5 (1.000) |
| csv-region-summary | baseline | gpt-5.4-mini | single | 5 | 3/5 (0.600) |
| csv-region-summary | baseline | gpt-5.4-mini | duo | 5 | 2/5 (0.400) |
| csv-region-summary | baseline | gpt-5.4-mini | triad | 5 | 3/5 (0.600) |
| fix-range-compression | baseline | claude-haiku-4-5 | single | 5 | 4/5 (0.800) |
| fix-range-compression | baseline | claude-haiku-4-5 | duo | 5 | 4/5 (0.800) |
| fix-range-compression | baseline | claude-haiku-4-5 | triad | 5 | 5/5 (1.000) |
| fix-range-compression | baseline | gpt-5.4-mini | single | 5 | 5/5 (1.000) |
| fix-range-compression | baseline | gpt-5.4-mini | duo | 5 | 3/5 (0.600) |
| fix-range-compression | baseline | gpt-5.4-mini | triad | 5 | 4/5 (0.800) |
| normalize-events | baseline | claude-haiku-4-5 | single | 5 | 3/5 (0.600) |
| normalize-events | baseline | claude-haiku-4-5 | duo | 5 | 2/5 (0.400) |
| normalize-events | baseline | claude-haiku-4-5 | triad | 5 | 3/5 (0.600) |
| normalize-events | baseline | gpt-5.4-mini | single | 5 | 4/5 (0.800) |
| normalize-events | baseline | gpt-5.4-mini | duo | 5 | 2/5 (0.400) |
| normalize-events | baseline | gpt-5.4-mini | triad | 5 | 2/5 (0.400) |
| fix-ttl-expiration-boundary | bugfix | claude-haiku-4-5 | single | 5 | 4/5 (0.800) |
| fix-ttl-expiration-boundary | bugfix | claude-haiku-4-5 | duo | 5 | 4/5 (0.800) |
| fix-ttl-expiration-boundary | bugfix | claude-haiku-4-5 | triad | 5 | 3/5 (0.600) |
| fix-ttl-expiration-boundary | bugfix | gpt-5.4-mini | single | 5 | 4/5 (0.800) |
| fix-ttl-expiration-boundary | bugfix | gpt-5.4-mini | duo | 5 | 1/5 (0.200) |
| fix-ttl-expiration-boundary | bugfix | gpt-5.4-mini | triad | 5 | 2/5 (0.400) |
| fix-invoice-discount-composition | bugfix | claude-haiku-4-5 | single | 5 | 4/5 (0.800) |
| fix-invoice-discount-composition | bugfix | claude-haiku-4-5 | duo | 5 | 2/5 (0.400) |
| fix-invoice-discount-composition | bugfix | claude-haiku-4-5 | triad | 5 | 4/5 (0.800) |
| fix-invoice-discount-composition | bugfix | gpt-5.4-mini | single | 5 | 5/5 (1.000) |
| fix-invoice-discount-composition | bugfix | gpt-5.4-mini | duo | 5 | 0/5 (0.000) |
| fix-invoice-discount-composition | bugfix | gpt-5.4-mini | triad | 5 | 0/5 (0.000) |
| add-topological-batches | feature | claude-haiku-4-5 | single | 5 | 0/5 (0.000) |
| add-topological-batches | feature | claude-haiku-4-5 | duo | 5 | 0/5 (0.000) |
| add-topological-batches | feature | claude-haiku-4-5 | triad | 5 | 0/5 (0.000) |
| add-topological-batches | feature | gpt-5.4-mini | single | 5 | 4/5 (0.800) |
| add-topological-batches | feature | gpt-5.4-mini | duo | 5 | 2/5 (0.400) |
| add-topological-batches | feature | gpt-5.4-mini | triad | 5 | 1/5 (0.200) |
| add-jsonl-dead-letter-output | feature | claude-haiku-4-5 | single | 5 | 0/5 (0.000) |
| add-jsonl-dead-letter-output | feature | claude-haiku-4-5 | duo | 5 | 0/5 (0.000) |
| add-jsonl-dead-letter-output | feature | claude-haiku-4-5 | triad | 5 | 0/5 (0.000) |
| add-jsonl-dead-letter-output | feature | gpt-5.4-mini | single | 5 | 1/5 (0.200) |
| add-jsonl-dead-letter-output | feature | gpt-5.4-mini | duo | 5 | 0/5 (0.000) |
| add-jsonl-dead-letter-output | feature | gpt-5.4-mini | triad | 5 | 0/5 (0.000) |
| refactor-notification-routing | refactor | claude-haiku-4-5 | single | 5 | 3/5 (0.600) |
| refactor-notification-routing | refactor | claude-haiku-4-5 | duo | 5 | 2/5 (0.400) |
| refactor-notification-routing | refactor | claude-haiku-4-5 | triad | 5 | 3/5 (0.600) |
| refactor-notification-routing | refactor | gpt-5.4-mini | single | 5 | 2/5 (0.400) |
| refactor-notification-routing | refactor | gpt-5.4-mini | duo | 5 | 1/5 (0.200) |
| refactor-notification-routing | refactor | gpt-5.4-mini | triad | 5 | 0/5 (0.000) |
| refactor-config-precedence | refactor | claude-haiku-4-5 | single | 5 | 2/5 (0.400) |
| refactor-config-precedence | refactor | claude-haiku-4-5 | duo | 5 | 0/5 (0.000) |
| refactor-config-precedence | refactor | claude-haiku-4-5 | triad | 5 | 0/5 (0.000) |
| refactor-config-precedence | refactor | gpt-5.4-mini | single | 5 | 2/5 (0.400) |
| refactor-config-precedence | refactor | gpt-5.4-mini | duo | 5 | 0/5 (0.000) |
| refactor-config-precedence | refactor | gpt-5.4-mini | triad | 5 | 0/5 (0.000) |

## Failures And Usage Gaps
- Failed runs: ["004-csv-region-summary-gpt-5-4-mini-r1-duo", "005-csv-region-summary-gpt-5-4-mini-r1-triad", "007-csv-region-summary-gpt-5-4-mini-r2-triad", "009-csv-region-summary-gpt-5-4-mini-r2-duo", "012-csv-region-summary-claude-haiku-4-5-r2-single", "014-csv-region-summary-claude-haiku-4-5-r3-single", "015-csv-region-summary-claude-haiku-4-5-r3-duo", "016-csv-region-summary-gpt-5-4-mini-r3-single", "029-csv-region-summary-gpt-5-4-mini-r5-single", "030-csv-region-summary-gpt-5-4-mini-r5-duo", "032-fix-range-compression-gpt-5-4-mini-r1-duo", "033-fix-range-compression-gpt-5-4-mini-r1-triad", "037-fix-range-compression-claude-haiku-4-5-r2-single", "045-fix-range-compression-gpt-5-4-mini-r3-duo", "059-fix-range-compression-claude-haiku-4-5-r5-duo", "061-normalize-events-claude-haiku-4-5-r1-duo", "062-normalize-events-claude-haiku-4-5-r1-triad", "063-normalize-events-claude-haiku-4-5-r1-single", "066-normalize-events-gpt-5-4-mini-r1-duo", "069-normalize-events-gpt-5-4-mini-r2-triad", "071-normalize-events-claude-haiku-4-5-r2-single", "072-normalize-events-claude-haiku-4-5-r2-duo", "076-normalize-events-gpt-5-4-mini-r3-duo", "077-normalize-events-gpt-5-4-mini-r3-triad", "079-normalize-events-gpt-5-4-mini-r4-triad", "081-normalize-events-gpt-5-4-mini-r4-duo", "082-normalize-events-claude-haiku-4-5-r4-duo", "085-normalize-events-claude-haiku-4-5-r5-triad", "088-normalize-events-gpt-5-4-mini-r5-single", "091-fix-ttl-expiration-boundary-gpt-5-4-mini-r1-duo", "092-fix-ttl-expiration-boundary-gpt-5-4-mini-r1-triad", "097-fix-ttl-expiration-boundary-claude-haiku-4-5-r2-duo", "102-fix-ttl-expiration-boundary-gpt-5-4-mini-r2-duo", "103-fix-ttl-expiration-boundary-gpt-5-4-mini-r3-single", "104-fix-ttl-expiration-boundary-gpt-5-4-mini-r3-duo", "105-fix-ttl-expiration-boundary-gpt-5-4-mini-r3-triad", "111-fix-ttl-expiration-boundary-claude-haiku-4-5-r4-triad", "112-fix-ttl-expiration-boundary-gpt-5-4-mini-r4-duo", "115-fix-ttl-expiration-boundary-gpt-5-4-mini-r5-triad", "119-fix-ttl-expiration-boundary-claude-haiku-4-5-r5-triad", "120-fix-ttl-expiration-boundary-claude-haiku-4-5-r5-single", "123-fix-invoice-discount-composition-claude-haiku-4-5-r1-duo", "125-fix-invoice-discount-composition-gpt-5-4-mini-r1-duo", "126-fix-invoice-discount-composition-gpt-5-4-mini-r1-triad", "127-fix-invoice-discount-composition-gpt-5-4-mini-r2-duo", "128-fix-invoice-discount-composition-gpt-5-4-mini-r2-triad", "131-fix-invoice-discount-composition-claude-haiku-4-5-r2-duo", "135-fix-invoice-discount-composition-claude-haiku-4-5-r3-single", "136-fix-invoice-discount-composition-gpt-5-4-mini-r3-triad", "138-fix-invoice-discount-composition-gpt-5-4-mini-r3-duo", "140-fix-invoice-discount-composition-gpt-5-4-mini-r4-duo", "141-fix-invoice-discount-composition-gpt-5-4-mini-r4-triad", "142-fix-invoice-discount-composition-claude-haiku-4-5-r4-triad", "146-fix-invoice-discount-composition-claude-haiku-4-5-r5-duo", "148-fix-invoice-discount-composition-gpt-5-4-mini-r5-duo", "149-fix-invoice-discount-composition-gpt-5-4-mini-r5-triad", "154-add-topological-batches-claude-haiku-4-5-r1-duo", "155-add-topological-batches-claude-haiku-4-5-r1-triad", "156-add-topological-batches-claude-haiku-4-5-r1-single", "157-add-topological-batches-claude-haiku-4-5-r2-triad", "158-add-topological-batches-claude-haiku-4-5-r2-single", "159-add-topological-batches-claude-haiku-4-5-r2-duo", "160-add-topological-batches-gpt-5-4-mini-r2-single", "162-add-topological-batches-gpt-5-4-mini-r2-triad", "163-add-topological-batches-gpt-5-4-mini-r3-duo", "164-add-topological-batches-gpt-5-4-mini-r3-triad", "166-add-topological-batches-claude-haiku-4-5-r3-single", "167-add-topological-batches-claude-haiku-4-5-r3-duo", "168-add-topological-batches-claude-haiku-4-5-r3-triad", "169-add-topological-batches-claude-haiku-4-5-r4-duo", "170-add-topological-batches-claude-haiku-4-5-r4-triad", "171-add-topological-batches-claude-haiku-4-5-r4-single", "172-add-topological-batches-gpt-5-4-mini-r4-triad", "174-add-topological-batches-gpt-5-4-mini-r4-duo", "176-add-topological-batches-gpt-5-4-mini-r5-duo", "177-add-topological-batches-gpt-5-4-mini-r5-triad", "178-add-topological-batches-claude-haiku-4-5-r5-triad", "179-add-topological-batches-claude-haiku-4-5-r5-single", "180-add-topological-batches-claude-haiku-4-5-r5-duo", "181-add-jsonl-dead-letter-output-claude-haiku-4-5-r1-single", "182-add-jsonl-dead-letter-output-claude-haiku-4-5-r1-duo", "183-add-jsonl-dead-letter-output-claude-haiku-4-5-r1-triad", "184-add-jsonl-dead-letter-output-gpt-5-4-mini-r1-duo", "185-add-jsonl-dead-letter-output-gpt-5-4-mini-r1-triad", "186-add-jsonl-dead-letter-output-gpt-5-4-mini-r1-single", "187-add-jsonl-dead-letter-output-gpt-5-4-mini-r2-triad", "189-add-jsonl-dead-letter-output-gpt-5-4-mini-r2-duo", "190-add-jsonl-dead-letter-output-claude-haiku-4-5-r2-duo", "191-add-jsonl-dead-letter-output-claude-haiku-4-5-r2-triad", "192-add-jsonl-dead-letter-output-claude-haiku-4-5-r2-single", "193-add-jsonl-dead-letter-output-claude-haiku-4-5-r3-triad", "194-add-jsonl-dead-letter-output-claude-haiku-4-5-r3-single", "195-add-jsonl-dead-letter-output-claude-haiku-4-5-r3-duo", "196-add-jsonl-dead-letter-output-gpt-5-4-mini-r3-single", "197-add-jsonl-dead-letter-output-gpt-5-4-mini-r3-duo", "198-add-jsonl-dead-letter-output-gpt-5-4-mini-r3-triad", "199-add-jsonl-dead-letter-output-gpt-5-4-mini-r4-duo", "200-add-jsonl-dead-letter-output-gpt-5-4-mini-r4-triad", "201-add-jsonl-dead-letter-output-gpt-5-4-mini-r4-single", "202-add-jsonl-dead-letter-output-claude-haiku-4-5-r4-single", "203-add-jsonl-dead-letter-output-claude-haiku-4-5-r4-duo", "204-add-jsonl-dead-letter-output-claude-haiku-4-5-r4-triad", "205-add-jsonl-dead-letter-output-claude-haiku-4-5-r5-duo", "206-add-jsonl-dead-letter-output-claude-haiku-4-5-r5-triad", "207-add-jsonl-dead-letter-output-claude-haiku-4-5-r5-single", "208-add-jsonl-dead-letter-output-gpt-5-4-mini-r5-triad", "209-add-jsonl-dead-letter-output-gpt-5-4-mini-r5-single", "210-add-jsonl-dead-letter-output-gpt-5-4-mini-r5-duo", "212-refactor-notification-routing-gpt-5-4-mini-r1-duo", "213-refactor-notification-routing-gpt-5-4-mini-r1-triad", "214-refactor-notification-routing-claude-haiku-4-5-r1-triad", "217-refactor-notification-routing-claude-haiku-4-5-r2-single", "218-refactor-notification-routing-claude-haiku-4-5-r2-duo", "220-refactor-notification-routing-gpt-5-4-mini-r2-duo", "221-refactor-notification-routing-gpt-5-4-mini-r2-triad", "223-refactor-notification-routing-gpt-5-4-mini-r3-triad", "224-refactor-notification-routing-gpt-5-4-mini-r3-single", "225-refactor-notification-routing-gpt-5-4-mini-r3-duo", "226-refactor-notification-routing-claude-haiku-4-5-r3-duo", "227-refactor-notification-routing-claude-haiku-4-5-r3-triad", "228-refactor-notification-routing-claude-haiku-4-5-r3-single", "231-refactor-notification-routing-claude-haiku-4-5-r4-duo", "232-refactor-notification-routing-gpt-5-4-mini-r4-single", "234-refactor-notification-routing-gpt-5-4-mini-r4-triad", "235-refactor-notification-routing-gpt-5-4-mini-r5-duo", "236-refactor-notification-routing-gpt-5-4-mini-r5-triad", "237-refactor-notification-routing-gpt-5-4-mini-r5-single", "241-refactor-config-precedence-claude-haiku-4-5-r1-duo", "242-refactor-config-precedence-claude-haiku-4-5-r1-triad", "243-refactor-config-precedence-claude-haiku-4-5-r1-single", "244-refactor-config-precedence-gpt-5-4-mini-r1-triad", "246-refactor-config-precedence-gpt-5-4-mini-r1-duo", "247-refactor-config-precedence-gpt-5-4-mini-r2-single", "248-refactor-config-precedence-gpt-5-4-mini-r2-duo", "249-refactor-config-precedence-gpt-5-4-mini-r2-triad", "250-refactor-config-precedence-claude-haiku-4-5-r2-triad", "252-refactor-config-precedence-claude-haiku-4-5-r2-duo", "253-refactor-config-precedence-claude-haiku-4-5-r3-single", "254-refactor-config-precedence-claude-haiku-4-5-r3-duo", "255-refactor-config-precedence-claude-haiku-4-5-r3-triad", "256-refactor-config-precedence-gpt-5-4-mini-r3-duo", "257-refactor-config-precedence-gpt-5-4-mini-r3-triad", "258-refactor-config-precedence-gpt-5-4-mini-r3-single", "259-refactor-config-precedence-gpt-5-4-mini-r4-triad", "261-refactor-config-precedence-gpt-5-4-mini-r4-duo", "262-refactor-config-precedence-claude-haiku-4-5-r4-duo", "263-refactor-config-precedence-claude-haiku-4-5-r4-triad", "265-refactor-config-precedence-claude-haiku-4-5-r5-triad", "266-refactor-config-precedence-claude-haiku-4-5-r5-single", "267-refactor-config-precedence-claude-haiku-4-5-r5-duo", "268-refactor-config-precedence-gpt-5-4-mini-r5-single", "269-refactor-config-precedence-gpt-5-4-mini-r5-duo", "270-refactor-config-precedence-gpt-5-4-mini-r5-triad"]
- Usage-missing runs: ["204-add-jsonl-dead-letter-output-claude-haiku-4-5-r4-triad"]

## Limitations
- Nine fixed tasks and five repetitions per model and mode remain descriptive evidence.
- Provider-side model weights cannot be independently pinned or verified.
- Local platform, date, and provider routes limit generalization.
- Results do not establish a cross-model ranking or product recommendation.

这些结果是固定协议下的描述性证据；本报告不生成模式排序或产品推荐。
