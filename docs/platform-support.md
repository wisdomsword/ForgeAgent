# Platform Support Matrix

M24 records platform evidence separately from product claims. A status describes the
repository's current verification surface, not a promise that every host has been run.
`verified` is reserved for an executed, reproducible platform run; `configured` means the
required CI job exists but that platform tuple still lacks runner evidence. Each platform tuple
is evaluated independently.

| Platform tuple | Priority | Status | Prerequisites | Current evidence | Limitations | Next Comet trigger |
| --- | --- | --- | --- | --- | --- | --- |
| GitHub Actions Ubuntu 24.04 x86_64 + Docker Engine 28.0.4 | P0 | verified | GitHub-hosted runner, built-in daemon, same-host bind mounts and non-root execution | [Run 44272935741](https://github.com/wisdomsword/ForgeAgent/actions/runs/44272935741), commit bde9d22: both jobs passed; 10 zero-skip container tests and six installed-wheel checks; [evidence](superpowers/reports/2026-11-18-github-ci-verify.md) | This exact runner tuple and candidate only; later commits require their own run | Candidate, runner, image or workflow changes |
| M28 installed-wheel gate on required Linux Docker job | P0 | verified | Existing privileged Docker runner topology, Python 3.11 image, package-index access, non-root execution, exact candidate wheel, and both evidence artifacts | M28 required Linux Docker CI 运行: 10 container tests and all six installed-wheel checks passed; JUnit and `artifacts/ci/rc-smoke.json` published | The record proves only this runner topology and candidate; every later candidate commit must pass its own required pipeline | Candidate, runner topology, image, or gate contract changes |
| Linux Docker runner topology (M24 历史 container 运行) | P0 | verified | Linux Docker runner with Docker daemon, shared build volume, non-root job execution, and the checked-in JUnit contract | GitLab M24 历史 container 运行: 10 passed, 0 skipped, 0 failures, 0 errors; JUnit artifact generated | The record proves this runner topology only; it does not establish unrecorded Linux architectures, Podman, Windows, or every Linux executor | Any runner topology change, or a DinD/container contract failure |
| Linux + rootless Podman | P1 | scheduled | Product decision to support Podman; compatible CLI/mount/network/pids/user/kill semantics | No execution evidence | Current backend commands and hardening flags target Docker | Podman becomes a release target or a compatibility spike is scheduled |
| Windows native | P2 | deferred | Product decision to support Windows; path, locking, resource-limit, and container-tier design | No execution evidence | Drive-letter colons and Unix-specific isolation assumptions require design work | Windows becomes a release target |
| macOS arm64 + Docker Desktop Linux daemon | non-release | supplemental | Docker Desktop 29.8.0 and local `python:3.11-slim` | 2026-11-18: ten zero-skip container tests and all six installed-wheel checks passed; current report linked below | Linux VM daemon evidence does not prove native Linux runners, Podman, or Windows | Regression in local evidence or a change to the non-release smoke environment |

The current GitHub Actions workflow is [verify.yml](../.github/workflows/verify.yml).
Its Ubuntu 24.04 host uses the built-in Docker daemon and same-host bind mounts, runs as
an unprivileged user, enforces exactly ten integration tests with zero skips/failures/errors,
and executes all six installed-wheel smoke checks. This topology is now `verified`
for commit `bde9d22` by [its actual GitHub run](https://github.com/wisdomsword/ForgeAgent/actions/runs/44272935741)
and downloaded JUnit/smoke artifacts. Historical GitLab results remain separate evidence;
later candidates must pass their own workflow run.

The required offline job also remains defined in [`.gitlab-ci.yml`](../.gitlab-ci.yml). It runs Ruff
check/format, the complete offline pytest suite, Golden 20/20, OpenSpec strict validation,
and wheel/sdist builds. The container job publishes a JUnit artifact and fails if the ten
marked tests are skipped, fail, or error.

The Linux job requires a privileged GitLab Docker executor tagged `docker-privileged`.
`TMPDIR` is placed below `$CI_PROJECT_DIR` so the job and DinD service see the same
same-path bind-mount source through GitLab's shared build volume. A runner with a different
executor or build-volume topology must prove that contract before being marked `verified`.

## M28 Release Candidate Gate

The M28 installed-wheel gate is verified by M28 required Linux Docker CI 运行. It built exactly one candidate
wheel, passed the ten container tests with zero skips, ran the six
clean-wheel/CLI/HTTP/Single/Duo/Triad checks in Python 3.11.15, and published both
`artifacts/ci/rc-smoke.json` and the container JUnit artifact. This result is commit-bound; a later
candidate must pass its own required pipeline. Local real-wheel verification alone does not satisfy
this Linux requirement.

M24 历史 container 运行 remains historical container-only evidence. It verifies the ten marked
container integration tests for that runner topology and must not be represented as an M28
installed-wheel smoke result.

Current-checkout verification is recorded in the
[release-readiness validation report](superpowers/reports/2026-11-18-fix-github-release-readiness-verify.md).
Do not substitute historical passing counts for the current candidate. GitHub and GitLab
pin uv 0.11.1 and OpenSpec 1.13.1. Dependency installation and image pulls require package-index
access; the tests and model mocks themselves run without provider credentials or real model calls.

The M28 local real-wheel gate and its Docker-daemon limitation are historical records in
[the frozen RC evidence](releases/0.1.0-rc.md). Current local Docker integration and
installed-wheel checks passed on 2026-11-18 as supplemental evidence below. Native
Linux GitHub runner execution and real-model checks remain unverified.

## Linux Docker Runner Evidence

On 2026-07-28, a Linux Docker runner executed the container gate manually as user `2000:2000`:

```text
10 passed, 4 deselected in 13.32s
```

The command wrote a non-empty `artifacts/ci/container-junit.xml`. The four deselected tests are
the non-integration unit tests in `tests/test_container_backend.py`; the ten marked integration
tests had zero skips, failures, and errors. Earlier root-owned artifacts and pytest cache entries
were removed before this run; the command itself was executed without `sudo`.

The required GitLab evidence was subsequently verified on 2026-07-28 by M24 历史 container 运行:
the job passed all ten marked integration tests with zero skips, failures, or errors and published
`artifacts/ci/container-junit.xml`. 更早的 container 运行 remains recorded as the audit trail for
the root bootstrap failure that motivated the non-root `su-exec` fix.

## Supplemental Local Evidence

On 2026-11-18, macOS 26.4 arm64 with Docker Desktop client/server 29.8.0 ran the
ten integration tests with `tests=10`, `failures=0`, `errors=0`, `skipped=0`
(`10 passed, 4 deselected in 14.82s`). This includes the receipt-write and
metadata-parent-move protections added by the release-readiness maintenance change.
The same wheel passed all six clean-install smoke checks inside a non-root
`python:3.11-slim` container running Python 3.11.18. The daemon was Linux aarch64,
kernel `7.0.12-linuxkit`, and the image digest was
`sha256:07d4824036af339fa1b6ef769cc99d9c10a141769538b52b3b597c84f7a7b535`.
The test subprocess explicitly retained the active Docker endpoint while pytest
isolated HOME. Commands, JUnit/JSON locations, wheel digest and scope are recorded
in the [current verification report](superpowers/reports/2026-11-18-fix-github-release-readiness-verify.md#supplemental-docker-integration-2026-11-18).
This local run does not mark the configured GitHub runner topology as verified.

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
