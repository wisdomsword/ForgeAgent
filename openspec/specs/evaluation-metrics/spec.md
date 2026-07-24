# evaluation-metrics Specification

## Purpose
TBD - created by archiving change eval-evaluator. Update Purpose after archive.
## Requirements
### Requirement: Evaluation metrics are aggregated from machine evidence
ForgeAgent SHALL create a versioned evaluation record by aggregating a golden runner
machine report and optional masked audit JSONL evidence. The record SHALL expose
golden pass rate, first-pass correctness, correction rounds, and cache-hit rate with
an explicit `null` value whenever its required input is unavailable or invalid.

#### Scenario: Complete machine evidence produces all metrics
- **WHEN** a valid golden report and completed-task audit events with valid token
  denominators are aggregated
- **THEN** the record contains deterministic values for all four M20 metrics and
  identifies the source report schema

#### Scenario: Missing metric inputs do not fabricate a value
- **WHEN** audit evidence is absent, malformed, or lacks a valid metric denominator
- **THEN** the affected metric is `null` and the golden pass rate remains derived
  solely from the valid golden report

### Requirement: Evaluation trends are local, bounded, and comparable
ForgeAgent SHALL atomically persist evaluation records to a caller-selected local
directory, retain a bounded chronological index, and compare a new record with the
latest compatible prior record without requiring a service, network request, or
model credential.

#### Scenario: A newer record is compared to its predecessor
- **WHEN** a valid record follows a valid record with the same evaluation schema
- **THEN** the trend output contains per-metric deltas and identifies both run IDs

#### Scenario: A corrupt historical record is encountered
- **WHEN** the trend directory contains an invalid or incompatible record
- **THEN** aggregation ignores that record with a fixed diagnostic and preserves
  valid current-record output

### Requirement: Evaluation data remains a safe projection
ForgeAgent SHALL accept only finite JSON scalar/container values in evaluation
records and SHALL NOT store prompts, model messages, raw tool arguments, absolute
paths, secret values, or unbounded audit detail.

#### Scenario: Unsafe audit payload is excluded
- **WHEN** an audit event includes an unrecognized parameter or a value outside the
  evaluation projection
- **THEN** the stored record contains no copy of that value and continues to report
  the independently available metrics
