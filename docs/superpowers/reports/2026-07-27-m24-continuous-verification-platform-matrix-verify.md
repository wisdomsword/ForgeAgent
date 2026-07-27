# M24 Continuous Verification and Platform Matrix - Verification Report

Date: 2026-07-27

## Scope

M24 adds repository validation infrastructure only: two required GitLab jobs, an exact
container test marker, offline CI contracts, a platform evidence matrix, and milestone
documentation. It does not modify `src/forgeagent/`, collaboration behavior, credentials,
model routing, or sandbox policy.

## Results

| Gate | Result |
| --- | --- |
| CI/document contracts | `4 passed` |
| Complete offline pytest with Docker hidden from `PATH` | `2309 passed, 10 skipped` |
| Complete local pytest with Docker available | `2319 passed` |
| macOS Docker Desktop container marker | JUnit `tests=10`, `failures=0`, `errors=0`, `skipped=0` |
| Golden offline runner | `20/20 passed (100.0%)` |
| Ruff check | passed |
| Ruff format check | 108 files already formatted |
| OpenSpec strict | `20 passed, 0 failed` including the active M24 change |
| Wheel/sdist build | both artifacts built successfully |
| Release content boundary | passed as part of the complete pytest suite |
| Exact offline CI image bootstrap | Node 22.22.0, Python 3.11.2, uv 0.11.1, OpenSpec 1.4.1 |
| Exact Docker CLI image bootstrap | Docker 29.2.1, Python 3.12.13, uv 0.11.1 |
| Git diff whitespace check | passed |

The supplemental container run used macOS 26.5.1 arm64, Docker client/server 29.2.1,
a Linux arm64 daemon, and `python:3.11-slim` image
`sha256:e031123e3d85762b141ad1cbc56452ba69c6e722ebf2f042cc0dc86c47c0d8b3`.

## Self-review 1: Contracts and History

- Removed the M23 test that incorrectly required `milestones/latest` to point to M23
  forever; M23's milestone and evidence links remain immutable.
- Narrowed the M23 pyproject snapshot to the actual invariant: product runtime files,
  `uv.lock`, project dependencies, and development dependency groups remain unchanged.
  This permits the M24 pytest marker without weakening the M23 credential/runtime scope.
- Confirmed historical M22/M23 counts and reports were not rewritten. Only the current
  README and M24 records use the new verification counts.

## Self-review 2: CI Executability and Evidence Boundaries

- Found that OpenSpec 1.4.1 requires Node >=20.19; replaced the incompatible Debian
  Node package path with the verified multi-architecture tag `node:22.22.0-bookworm-slim`
  plus Debian Python 3.11.
- Added `--break-system-packages` to both Debian/Alpine bootstrap paths and executed the
  Docker CLI image bootstrap: Python 3.12.13, uv 0.11.1, Docker CLI 29.2.1.
- Found that ContainerBackend's same-path bind mount can fail against a remote DinD
  service when pytest uses private `/tmp`. The job now requires a `docker-privileged`
  Docker executor and fixes `TMPDIR` below `$CI_PROJECT_DIR`, the shared build volume.
- Confirmed both jobs are in the required `verify` stage, do not allow failure, publish
  their evidence, and make Docker daemon/image and JUnit count checks fatal.

## Independent Diff Review

The independent reviewer found no Critical issues and three Important issues. All were
fixed before the final gate:

- Expanded the platform matrix to exact platform tuples and explicit prerequisite,
  evidence, limitation, and next-trigger columns.
- Strengthened CI contracts to cover workflow failure policy, Git depth, artifacts,
  DinD endpoint/TLS/TMPDIR settings, privileged runner tag, and JUnit publication.
- Restored the full M23 pyproject snapshot invariant after removing only M24's pytest
  marker, rather than comparing dependency arrays alone.

Two Minor findings were also fixed: the marker contract now matches the exact ten named
`docker_required` tests, and the implementation plan records the real base commit SHA.
The final serial offline suite was rerun after all review fixes.

## OpenSpec Full Verification

| Dimension | Status |
| --- | --- |
| Completeness | 8/8 tasks complete; 4/4 requirements implemented |
| Correctness | 10/10 scenarios mapped to CI, tests, build evidence, or platform-state rules |
| Coherence | OpenSpec design, technical design, implementation plan, CI, tests, and public docs agree |

- Mandatory offline pipeline: `.gitlab-ci.yml` plus the structured CI contract cover all
  required commands, failure behavior, and Golden/dist artifacts.
- Release boundary: the offline job runs the existing real packaging contract and then
  emits fresh wheel/sdist artifacts; the final build and packaging tests passed.
- Linux Docker gate: the exact ten `docker_required` tests carry the integration marker;
  daemon/image preflight and JUnit tests/failures/errors/skips are fatal.
- Platform matrix: all four platform tuples have priority, state, prerequisites, evidence,
  limitations, and an explicit next Comet trigger; no unsupported tuple is `verified`.

No Critical, Warning, or Suggestion issue remains from the OpenSpec verification.

## Limitations

The GitLab pipeline itself was not executed because no target GitLab runner is available
in this workspace. Linux Docker therefore remains `configured`, not `verified`. Both job
images and their dependency bootstrap commands were executed locally, but that does not
prove GitLab scheduling, the privileged DinD service, or the shared build-volume topology.
The macOS Docker Desktop result is supplemental only. Podman is scheduled and Windows is
deferred; neither is claimed as supported or verified.
