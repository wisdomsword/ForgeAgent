# Task 2 Report: M25 Frozen Evidence Derivation

## Scope

Implemented the M27 additive derivation only in the approved Task 2 files:

- `scripts/m27_m25_routing_analysis.py`
- `tests/test_m27_m25_routing_analysis.py`
- `docs/evaluation/m25/derived/m27-collaboration-routing/analysis.json`
- `docs/evaluation/m25/derived/m27-collaboration-routing/report.md`
- `docs/evaluation/m25/README.md`

The script imports the sibling independent recompute module, validates the frozen M25 summary before
reading metrics, validates the newly consumed raw fields, and writes JSON plus Markdown from temporary
files. It rejects output directories inside the frozen run directory.

## RED / GREEN

- RED: `UV_CACHE_DIR=/tmp/forgeagent-m27-uv-cache rtk uv run pytest -q tests/test_m27_m25_routing_analysis.py`
  failed as expected because `scripts/m27_m25_routing_analysis.py` did not exist (`2 failed`).
- GREEN: `UV_CACHE_DIR=/tmp/forgeagent-m27-uv-cache rtk uv run pytest -q tests/test_m27_m25_routing_analysis.py tests/test_m25_independent_recompute.py`
  passed (`9 passed`).

The new tests exercise a legal terminal record that completed runtime work but failed a check, verify both
false-completion denominators and raw termination reasons, verify model/family cost aggregates, reject raw
identity and summary tampering, reject an output directory nested in the frozen run directory, and remove
any partially published output if replacing the paired report fails.

## Real Frozen Evidence

```text
M27_ROUTING_ANALYSIS_OK runs=270 restored=none
INDEPENDENT_RECOMPUTE_OK runs=270
```

The derived report records the decision: no task family has a Triad solved rate strictly above Single.
Baseline ties; bugfix, feature, and refactor are lower. Therefore no automatic Triad category is restored.
The report explicitly states that M25 predates M26 frozen-check binding.

## Frozen Input Evidence

`git diff --exit-code -- docs/evaluation/m25/protocol.json docs/evaluation/m25/runs/2026-07-27-haiku-4-5-gpt-5-4-mini`
returned success. SHA-256 checks also remained unchanged:

```text
docs/evaluation/m25/protocol.json: OK
docs/evaluation/m25/runs/2026-07-27-haiku-4-5-gpt-5-4-mini/environment.json: OK
docs/evaluation/m25/runs/2026-07-27-haiku-4-5-gpt-5-4-mini/summary.json: OK
docs/evaluation/m25/runs/2026-07-27-haiku-4-5-gpt-5-4-mini/report.md: OK
```

## Quality Checks

```text
ruff check scripts/m27_m25_routing_analysis.py tests/test_m27_m25_routing_analysis.py: passed
ruff format --check scripts/m27_m25_routing_analysis.py tests/test_m27_m25_routing_analysis.py: passed
git diff --check: passed
```

## Self-review

1. The initial synthetic fixture made Triad quality-eligible in several families, so its assertion that no
   family was eligible was invalid. The assertion was removed; the frozen M25 run, rather than synthetic
   fixture shape, proves the real decision.
2. The generated analysis contains the required model/mode and family/mode aggregates, two false-completion
   rates, raw reasons, totals/means for calls, attempts, latency, and tokens. It does not modify or reinterpret
   frozen M25 artifacts.

## Commit

Pending at time of report generation. The Task 2 files are ready for the scoped commit
`feat: derive m25 collaboration routing evidence`.

## Risk Signals

- M25 is a finite historical sample and predates M26 evidence binding; its false-completion statistics must
  not be read as a measurement of the current bound-check Triad path.
- The compatibility dependency is intentionally local: the derivation imports only the independent M25
  recompute script, not the M25 generation or aggregation harness.

## Review Fix: Decision Consistency and Paired Publication

### RED

`UV_CACHE_DIR=/tmp/forgeagent-m27-uv-cache uv run pytest -q tests/test_m27_m25_routing_analysis.py`
failed with the two intended regressions: synthetic quality-eligible families were not copied to
`automatic_triad_restored_for`, and a simulated failure while replacing `report.md` deleted a pre-existing
`analysis.json`.

### GREEN

The derived decision now restores exactly the strictly quality-eligible families and constructs both the
machine `decision.reason` and report conclusion from that same restored list. For the real M25 evidence the
list remains empty, so the generated result is still `restored=none`.

`write_outputs` now moves any existing output member to a same-directory temporary backup before publishing
the replacement pair. If either publication fails, it removes newly published members and restores exactly
the prior state, including a complete pair and the one-file-present states. On success it removes backups.
Tests cover complete, analysis-only, and report-only pre-existing states plus normal successful replacement.
