# Platform Support Matrix

M24 records platform evidence separately from product claims. A status describes the
repository's current verification surface, not a promise that every host has been run.
`verified` is reserved for an executed, reproducible platform run; `configured` means the
required CI job exists but that platform tuple still lacks runner evidence. Each platform tuple
is evaluated independently.

| Platform tuple | Priority | Status | Prerequisites | Current evidence | Limitations | Next Comet trigger |
| --- | --- | --- | --- | --- | --- | --- |
| Linux amd64/arm64 + Docker Engine | P0 | configured | Linux Docker runner with Docker daemon, shared build volume, non-root job execution, and the checked-in JUnit contract | Manual runner: 10 passed, 0 skipped; GitLab Pipeline 48 / Job 245 reached Docker and failed because the job ran as root (`uid: 0`) | Required GitLab Job must pass after the non-root bootstrap fix; this does not prove Podman, Windows, or every Linux executor | Successful post-fix GitLab Job, or any runner topology change |
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

Current offline repository baseline: `2309 passed, 10 skipped`; OpenSpec strict `20/20`;
Golden `20/20`. The dated Linux runner evidence below is separate from this offline baseline. The
required GitLab job remains `configured` until a post-fix run passes.

## Linux Docker Runner Evidence

On 2026-07-28, a Linux Docker runner executed the container gate manually as user `2000:2000`:

```text
10 passed, 4 deselected in 13.32s
```

The command wrote a non-empty `artifacts/ci/container-junit.xml`. The four deselected tests are
the non-integration unit tests in `tests/test_container_backend.py`; the ten marked integration
tests had zero skips, failures, and errors. Earlier root-owned artifacts and pytest cache entries
were removed before this run; the command itself was executed without `sudo`. This is manual Linux
evidence, not a passing GitLab Pipeline result. Pipeline 48 / Job 245 confirmed Docker daemon and
image availability but failed at `test_t9_non_root_and_sys_masked` with `uid: 0`; the CI fix adds a
non-root `su-exec` bootstrap.

## Supplemental Local Evidence

On 2026-07-27, macOS 26.5.1 arm64 with Docker Desktop client/server 29.2.1 ran:

```bash
.venv/bin/python -m pytest -q tests/test_container_backend.py \
  -m container_integration --junitxml=/tmp/forgeagent-m24-evidence/container-junit.xml
```

The JUnit record reported `tests=10`, `failures=0`, `errors=0`, `skipped=0` in 11.79s.
The daemon was Linux arm64 and `python:3.11-slim` resolved to
`sha256:db3ff2e1800a8581e2c48a27c3995339d47bdf046da21c7627accd3d51053a93`.
This is supplemental macOS Docker Desktop evidence only; the Linux runner remains
`configured` until its required GitLab job publishes equivalent evidence.
