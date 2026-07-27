# Platform Support Matrix

M24 records platform evidence separately from product claims. A status describes the
repository's current verification surface, not a promise that every host has been run.
`verified` is reserved for an executed, reproducible platform run; `configured` means the
required CI job exists but its runner evidence is still pending.

| Platform tuple | Priority | Status | Prerequisites | Current evidence | Limitations | Next Comet trigger |
| --- | --- | --- | --- | --- | --- | --- |
| Linux amd64/arm64 + Docker Engine | P0 | configured | Privileged GitLab Docker executor tagged `docker-privileged`; shared build volume | Required DinD job and strict 10-test JUnit contract are checked in | No target Linux runner result yet | First target runner result, or any DinD topology failure |
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
Golden `20/20`.

## Supplemental Local Evidence

On 2026-07-27, macOS 26.5.1 arm64 with Docker Desktop client/server 29.2.1 ran:

```bash
.venv/bin/python -m pytest -q tests/test_container_backend.py \
  -m container_integration --junitxml=/tmp/forgeagent-m24-evidence/container-junit.xml
```

The JUnit record reported `tests=10`, `failures=0`, `errors=0`, `skipped=0` in 12.076s.
The daemon was Linux arm64 and `python:3.11-slim` resolved to
`sha256:e031123e3d85762b141ad1cbc56452ba69c6e722ebf2f042cc0dc86c47c0d8b3`.
This is supplemental macOS Docker Desktop evidence only; the Linux runner remains
`configured` until its required GitLab job publishes equivalent evidence.
