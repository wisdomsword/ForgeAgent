# Platform Support Matrix

M24 records platform evidence separately from product claims. A status describes the
repository's current verification surface, not a promise that every host has been run.
`verified` is reserved for an executed, reproducible platform run; `configured` means the
required CI job exists but that platform tuple still lacks runner evidence. Each platform tuple
is evaluated independently.

| Platform tuple | Priority | Status | Prerequisites | Current evidence | Limitations | Next Comet trigger |
| --- | --- | --- | --- | --- | --- | --- |
| M28 installed-wheel gate on required Linux Docker job | P0 | verified | Existing privileged Docker runner topology, Python 3.11 image, package-index access, non-root execution, exact candidate wheel, and both evidence artifacts | M28 Pipeline 57 / Job 263: 10 container tests and all six installed-wheel checks passed; JUnit and `artifacts/ci/rc-smoke.json` published | The record proves only this runner topology and candidate; every later candidate commit must pass its own required pipeline | Candidate, runner topology, image, or gate contract changes |
| Linux Docker runner topology (Pipeline 50 / Job 249) | P0 | verified | Linux Docker runner with Docker daemon, shared build volume, non-root job execution, and the checked-in JUnit contract | GitLab Pipeline 50 / Job 249: 10 passed, 0 skipped, 0 failures, 0 errors; JUnit artifact generated | The record proves this runner topology only; it does not establish unrecorded Linux architectures, Podman, Windows, or every Linux executor | Any runner topology change, or a DinD/container contract failure |
| Linux + rootless Podman | P1 | scheduled | Product decision to support Podman; compatible CLI/mount/network/pids/user/kill semantics | No execution evidence | Current backend commands and hardening flags target Docker | Podman becomes a release target or a compatibility spike is scheduled |
| Windows native | P2 | deferred | Product decision to support Windows; path, locking, resource-limit, and container-tier design | No execution evidence | Drive-letter colons and Unix-specific isolation assumptions require design work | Windows becomes a release target |
| macOS arm64 + Docker Desktop Linux daemon | non-release | supplemental | Docker Desktop 29.2.1 and local `python:3.11-slim` | Dated local JUnit 10/10 below | Linux VM daemon evidence does not prove native Linux runners, Podman, or Windows | Regression in local evidence or a change to the non-release smoke environment |

The required offline job is defined in [`.gitlab-ci.yml`](../.gitlab-ci.yml). It runs Ruff
check/format, the complete offline pytest suite, Golden 20/20, OpenSpec strict validation,
and wheel/sdist builds. The container job publishes a JUnit artifact and fails if the ten
marked tests are skipped, fail, or error.

The Linux job requires a privileged GitLab Docker executor tagged `docker-privileged`.
`TMPDIR` is placed below `$CI_PROJECT_DIR` so the job and DinD service see the same
same-path bind-mount source through GitLab's shared build volume. A runner with a different
executor or build-volume topology must prove that contract before being marked `verified`.

## M28 Release Candidate Gate

The M28 installed-wheel gate is verified by M28 Pipeline 57 / Job 263. It built exactly one candidate
wheel, passed the ten container tests with zero skips, ran the six
clean-wheel/CLI/HTTP/Single/Duo/Triad checks in Python 3.11.15, and published both
`artifacts/ci/rc-smoke.json` and the container JUnit artifact. This result is commit-bound; a later
candidate must pass its own required pipeline. Local real-wheel verification alone does not satisfy
this Linux requirement.

M24 Pipeline 50 / Job 249 remains historical container-only evidence. It verifies the ten marked
container integration tests for that runner topology and must not be represented as an M28
installed-wheel smoke result.

Current offline repository baseline: `3055 passed, 11 skipped`; OpenSpec strict `42/42`;
Golden `20/20`. M28 local RC evidence on 2026-07-29 is: focused release contracts `47 passed`,
Ruff check/format and wheel/sdist build passed. The unique built wheel ran
the six clean-wheel/CLI/HTTP/Single/Duo/Triad checks successfully with Python 3.11.15. The first full
pytest attempt was `2 failed, 2401 passed, 10 skipped`; both scheduler-dependent MCP wall-clock
assertions reproduced in isolation. Commit `83ba892` changed only the tests to assert deterministic
forwarded budgets, left production MCP code unchanged, and that fresh full run passed with
`2403 passed, 10 skipped`. The final baseline is `2409 passed, 10 skipped` after adding the hostile-proxy,
Golden cold-start, and private pip-cache regressions.

The local Docker client is 29.2.1, but `docker info` could not connect to
`/Users/admin/.docker/run/docker.sock`. Therefore no supplemental local container integration or
Linux-container RC smoke was run for M28. This local limitation does not replace or weaken the
required GitLab Linux result above.

## Linux Docker Runner Evidence

On 2026-07-28, a Linux Docker runner executed the container gate manually as user `2000:2000`:

```text
10 passed, 4 deselected in 13.32s
```

The command wrote a non-empty `artifacts/ci/container-junit.xml`. The four deselected tests are
the non-integration unit tests in `tests/test_container_backend.py`; the ten marked integration
tests had zero skips, failures, and errors. Earlier root-owned artifacts and pytest cache entries
were removed before this run; the command itself was executed without `sudo`.

The required GitLab evidence was subsequently verified on 2026-07-28 by Pipeline 50 / Job 249:
the job passed all ten marked integration tests with zero skips, failures, or errors and published
`artifacts/ci/container-junit-50.xml`. Pipeline 48 / Job 245 remains recorded as the audit trail for
the root bootstrap failure that motivated the non-root `su-exec` fix.

## Supplemental Local Evidence

On 2026-07-27, macOS 26.5.1 arm64 with Docker Desktop client/server 29.2.1 ran:

```bash
.venv/bin/python -m pytest -q tests/test_container_backend.py \
  -m container_integration --junitxml=/tmp/forgeagent-m24-evidence/container-junit.xml
```

The JUnit record reported `tests=10`, `failures=0`, `errors=0`, `skipped=0` in 11.79s.
The daemon was Linux arm64 and `python:3.11-slim` resolved to
`sha256:db3ff2e1800a8581e2c48a27c3995339d47bdf046da21c7627accd3d51053a93`.
This is supplemental macOS Docker Desktop evidence only; it does not expand the verified
Linux Docker runner topology to another architecture, Podman, or Windows.
