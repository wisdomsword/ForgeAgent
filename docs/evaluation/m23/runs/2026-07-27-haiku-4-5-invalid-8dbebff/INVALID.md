# Invalid M23 Evaluation Batch

This directory preserves the first 27-run batch for audit only. It is not valid M23 quality
evidence and must not be aggregated with the v2 protocol.

- Protocol: `forgeagent.m23.mode-evaluation/v1`
- Protocol SHA-256: `cf37be264871d983f09d6a9a2a0453306e8f6c9c2d9e4bb16c43ad59adbb1fc3`
- Invalidated: 2026-07-27
- Reason: the CSV and event checks attempted nested `subprocess.run` calls inside the restricted
  check worker, so those checks failed independently of candidate quality. The v1 protocol also
  did not independently prove that immutable task fixtures remained unchanged.

The v2 protocol removes nested process creation, records fixture-integrity checks, and hardens
run/aggregate output-root validation. Do not cite the completion rates in this directory.
