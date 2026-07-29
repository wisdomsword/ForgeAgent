# Task 2 Report: M28 Wheel Packaging and Linux Docker Gate

## Outcome

DONE_WITH_CONCERNS. The packaging contract now runs the single M28 release-candidate harness against the
real built wheel from a non-repository directory. The GitLab Linux Docker job builds exactly one
`forgeagent-0.1.0-*.whl`, runs the harness with Python 3.11 as UID/GID 1000, checks the exact six-pass JSON
contract, and always publishes `artifacts/ci/rc-smoke.json` alongside the existing JUnit report.

## Changed Product Files

- `.gitlab-ci.yml`
- `tests/test_packaging.py`
- `tests/test_m28_release_ci.py`

## TDD Evidence

RED command:

```text
UV_CACHE_DIR=/tmp/forgeagent-m28-uv-cache uv run pytest -q tests/test_m28_release_ci.py tests/test_packaging.py -k 'release_ci or wheel_and_sdist'
```

Failed as expected. The first failure showed that `artifacts/ci/rc-smoke.json` was absent from the Linux
job artifacts; the job also lacked the harness and exact report checks.

GREEN command:

```text
UV_CACHE_DIR=/tmp/forgeagent-m28-uv-cache uv run pytest -q tests/test_m28_release_ci.py tests/test_packaging.py tests/test_continuous_verification.py
9 passed in 37.34s
```

This includes a real wheel build, clean harness install, offline CLI/HTTP/Single/Duo/Triad execution, and
the adjacent M24 CI contracts that preserve DinD, preflight, non-root execution, and exact 10-test/no-skip
JUnit assertions.

## Quality Evidence

```text
ruff check tests/test_packaging.py tests/test_m28_release_ci.py: All checks passed!
ruff format --check tests/test_packaging.py tests/test_m28_release_ci.py: 2 files already formatted
git diff --check: passed
```

## Implementation Notes

The fixed `python:3.11-slim` container performs a non-editable bootstrap install of the exact candidate
wheel so the parent harness module can import its driver dependencies. The harness then independently
creates its own clean venv, installs the snapshotted wheel, and proves that every product import comes from
that venv. The Docker invocation forwards only project-local `HOME` and `TMPDIR`; it does not pass provider
credentials or use source/editable imports.

## Risks

- Live Docker execution is configured-only in this local run because `docker info` reported:
  `Cannot connect to the Docker daemon at unix:///Users/admin/.docker/run/docker.sock.` The full GitLab
  runner execution remains Task 4 evidence.
- The container bootstrap requires package-index access for wheel dependencies, as does the harness clean
  venv install. The CI image and candidate wheel itself are fixed; dependency hashes remain governed by the
  project lock for the host build, while isolated wheel installation exercises published metadata.

## Commit

Pending at report generation; intended message: `ci: gate Linux releases on installed-wheel smoke`.

## Review Fix Round 1

### Root Cause

- The folded shell command used `test ... && test ...;` without an explicit terminating guard. In a GitLab script item, a false intermediate command did not prevent the subsequent wheel assignment and Docker invocation.
- The bootstrap used `pip install && harness`, so a pip failure bypassed the only report writer and contradicted the `artifacts: when: always` evidence contract.

### RED Evidence

```text
UV_CACHE_DIR=/tmp/forgeagent-m28-uv-cache uv run pytest -q tests/test_m28_release_ci.py
2 failed, 2 passed in 0.03s
```

The failures specifically reported the missing `|| exit 1` wheel guards and missing explicit bootstrap fallback.

### Fix

- Replaced the wheel cardinality/file checks with explicit `|| exit 1` guards.
- Wrapped bootstrap installation in `if ...; then ...; else ...; exit 1; fi`.
- On bootstrap failure, Python 3.11 stdlib writes the exact bounded schema atomically: `clean-wheel=failed`, all five downstream checks `not-run`, `passed=false`, and the candidate wheel SHA-256.
- Added actual shell cardinality execution for zero/one/two wheels and direct execution/assertion of the stdlib fallback report.

### GREEN Evidence

```text
UV_CACHE_DIR=/tmp/forgeagent-m28-uv-cache uv run pytest -q tests/test_m28_release_ci.py tests/test_continuous_verification.py
8 passed in 0.12s

UV_CACHE_DIR=/tmp/forgeagent-m28-uv-cache uv run ruff check tests/test_m28_release_ci.py
All checks passed!

UV_CACHE_DIR=/tmp/forgeagent-m28-uv-cache uv run ruff format --check tests/test_m28_release_ci.py
1 file already formatted

git diff --check
passed
```

### Residual Risk

The Docker daemon remains unavailable locally, so the whole container command is contract-tested rather than executed end to end. The shell cardinality fragment and bootstrap fallback program are executed directly by focused tests.

### Fix Commit

`00ad2115c32aecf9e067be9dac4c1e6ed416a6c2` (`fix: fail closed in release candidate CI`)
