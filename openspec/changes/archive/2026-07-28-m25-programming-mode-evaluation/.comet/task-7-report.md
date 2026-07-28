# Task 7 Report: Independent Recompute and Evidence Safety

- Base commit: `f937f73`
- Head commit: `817a49f`

## RED

All three independent recompute tests failed because the standalone script did not exist.

## GREEN

- Independent recompute and recursive safety focus: `6 passed`
- Full M23/M25/independent suites: `118 passed`
- Ruff and diff checks: passed
- CLI output: `INDEPENDENT_RECOMPUTE_OK runs=270`

The script imports no harness aggregation or rendering code. It reconstructs the fixed schedule, recomputes protocol/environment/RunSpec SHA-256 values, validates 270 terminal identities and routes, and independently compares model/family/task additive totals, denominators, and rates to summary output.
