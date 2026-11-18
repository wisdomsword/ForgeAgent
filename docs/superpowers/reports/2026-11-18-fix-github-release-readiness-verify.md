# GitHub release-readiness verification

Change: `fix-github-release-readiness`. This report distinguishes the current checkout
from historical M23/M25/M28 evidence. No publishing, tag creation, or push is authorized
by these checks.

## Focused release-readiness checks

- Initial failing run: `10 failed, 136 passed, 1 skipped in 18.01s`. This reproduced
  the six pre-existing baseline/history failures and the four new release contracts.
- Final affected suite: `160 passed, 1 skipped in 18.08s` across
  `test_release_readiness`, `test_continuous_verification`, `test_m28_release_ci`,
  `test_m28_release_docs`, `test_borrowing_roadmap`, `test_documentation_index`,
  `test_repository_lifecycle`, `test_m23_mode_evaluation`, and `test_m25_mode_evaluation`.
  The skip is the existing cross-interpreter digest check when all supported Python
  interpreters are not installed (`python3.11` missing in this environment).
- OpenSpec CLI: `1.13.1`; `openspec validate --all --strict` initially reported
  `41 passed, 2 failed (43 items)` because configuration/image-input Purpose text
  was shorter than 50 characters. Descriptive Purpose text now passes:
  `43 passed, 0 failed (43 items)`.
- Targeted Ruff check and format verification: passed for the five modified/new
  Python release-contract modules. `git diff --check`: passed.
- Git check-ignore contracts cover `.env*`, loops, collaborations, receipts,
  `MEMORY.md`, Memory directories, and backups, while project AGENTS/Skills stay
  shareable.
- GitHub CI is configured for an offline job and a separate non-root Linux Docker
  gate using the Ubuntu host daemon. Its JUnit assertion was executed locally
  against valid evidence and missing-test/skip/failure/error cases. Remote GitHub
  runner execution and its installed-wheel artifacts have not been observed. All
  workflow shell blocks also passed `bash -n`.

The [portable M23 audit](../../evaluation/m23-frozen-evidence.md) describes the
verified historical source comparison and immutable 62-file manifest. M23/M25 tests
no longer need pruned historical Git objects. An isolated copy without `.git` passed
both contracts, and deliberate modification of its protocol file was rejected
(`PORTABLE_EVIDENCE_OK without .git; modified evidence rejected`).

## Integration evidence

Final current-checkout integration gates passed on macOS arm64 with Python 3.14.7;
the before-commit full-suite run included all ten Docker integration cases.

pytest: `3159 passed, 1 skipped`；OpenSpec strict: `42/42`.

The earlier integration run preceded Docker startup and returned `3149 passed,
11 skipped`: ten unavailable Docker integration tests and one optional
cross-interpreter PATH check. Its historical count is preserved below. The current
full-suite result above was measured separately and retains only the optional PATH
check skip; see the before-commit evidence at the end of this report.
Python 3.11.15 was separately installed in an isolated
validation environment using the repository lock: 258 targeted runtime/client/tool
tests passed. This does not claim native Linux execution.

Earlier full-suite output, before Docker startup:

```text
3149 passed, 11 skipped in 263.33s (0:04:23)
```

Ruff lint passed, Ruff format reported 160 formatted files, and diff whitespace
checks passed. Before archiving, OpenSpec CLI 1.13.1 reported
`43 passed, 0 failed (43 items)`.
Golden passed 20/20. Wheel and sdist builds passed; the packaging contract ran in
the full suite. The standalone clean-wheel harness on Python 3.11.15 passed all
six checks: clean-wheel, CLI, real loopback HTTP, Single, Duo, and Triad. Wheel
SHA-256: `0884f6cb08f19db7efe99344c0e5159975d42330ae77c19bf942a094db5e0482`.
Local command evidence lives under ignored `artifacts/release-audit/`: final-pytest.xml,
final-pytest.log, final-openspec.log, final-golden/results.json, final-dist/ and
clean-wheel-python311.json.

Read-only independent reviews covered runtime authority/catalog/capture changes and
tool/parser/rendering changes. Review findings were reproduced with failing tests,
fixed, and verified; no requested-review blocker remained. The final 24 execution
boundary regressions and 125 combined documentation/Golden/runtime tests passed.

Initial integration output:

```text
FAILED tests/test_collaboration_docs.py::test_readme_current_verification_section_is_unique_and_structured
FAILED tests/test_golden_runner.py::test_g14_allows_cold_worker_start_after_timeout
FAILED tests/test_release_runtime_boundaries.py::test_pathological_json_frames_are_structured_failures[excessive-nesting]
3 failed, 3146 passed, 11 skipped in 263.87s (0:04:23)
```

The documentation contract now checks the single linked verification report.
The cold-start regression intercepts actual worker creation through Popen, retaining
the delayed second-worker and deadline assertions. The JSON test permits successful
parsing of valid nested data on interpreters with iterative decoders, while asserting
that decoder errors remain structured execution failures.

Real-model/provider requests and Linux Docker runner execution are not implied by
local offline checks.


## Audit closure map

| Audit item | Implementation and regression evidence |
| --- | --- |
| 1 Receipt authority | Protected file/worker paths and descriptor handling, read-only container metadata mount, catalog plus initialization marker; runtime boundary tests cover deletion, ancestor moves, permission changes, restart loss, adoption, write failure and capacity. |
| 2 FileRead | Opened-regular-file checks, non-blocking/no-follow reads and 1 MiB cap; file-tool tests cover FIFO, growth, oversize, newline and masking behavior. |
| 3 Output bounds | 8 KiB worker stream prefixes, parent pipe draining with 1 MiB result cap, safe recovery captures; oversized stdout/stderr/state/direct-frame tests preserve previous state. |
| 4 Baseline failures | M52 navigation and maintenance notes corrected; M23/M25 use frozen portable evidence; complete pytest passes. |
| 5 GitHub CI | Offline and non-root Linux Docker jobs, exact ten zero-skip JUnit checks and six installed-wheel checks; executable workflow contracts pass. Remote execution remains unverified. |
| 6 Git ignores | Credential and runtime-state ignores with shareable AGENTS/Skills retained; git check-ignore contracts pass. |
| 7 Working directory | Restricted project cwd independent from filesystem authority; relative writes and full-disk grant regressions pass. |
| 8 Invalid types | Tool identity becomes parse error; HTTP enum fields become 400; authenticated request regressions pass. |
| 9 Retry ownership | SDK retries disabled; mock HTTP tests verify actual attempts for both providers and complete/stream paths. |
| 10 Discovery | Five-second per-operation maximum, shorter request timeout respected, deterministic client close, typed cache and atomic replacement tests pass. |
| 11 Input bounds | Skill reads bounded before decode, native compatibility limits preserved, image loading stops at image 21; byte-count and count regressions pass. |
| 12 Literal rendering | Final outcomes, Survey, MCP, search, evaluation and REPL external text render literally; unmatched-tag regressions pass. |
| 13 Onboarding/security | README begins with installation/credentials/first use and risk boundaries; SECURITY.md documents supported versions and private reporting. |

## Supplemental Docker integration, 2026-11-18

The user started Docker and authorized real container verification. Host: macOS
26.4 arm64, Python 3.14.7. Docker client/server: 29.8.0. Daemon: Docker Desktop
Linux aarch64, kernel `7.0.12-linuxkit`. Image: `python:3.11-slim`, digest
`sha256:07d4824036af339fa1b6ef769cc99d9c10a141769538b52b3b597c84f7a7b535`.

The first probe skipped all ten cases because pytest isolates HOME and therefore
hid the Docker Desktop context. The successful run explicitly supplied the current
context endpoint through DOCKER_HOST only to the test subprocess. No global Docker
configuration or shell environment was changed. Its JUnit record is
`artifacts/release-audit/docker-integration-junit.xml`:

```text
10 passed, 4 deselected in 14.82s
tests=10 failures=0 errors=0 skipped=0
```

This executes real worker/state exchange, same-path project writes, rejection of
receipt writes and metadata-parent moves, timeout termination and subsequent work,
exception capture, host-filesystem isolation, no-network behavior, process limits,
non-root execution, masked /sys and credential-free container environments.

The exact wheel recorded above was installed and checked in a fresh non-root Linux
container using the same image. Source was mounted read-only; output, temporary
directories and the bootstrap user installation were confined to the ignored
`artifacts/release-audit/docker-wheel/` directory. The clean-wheel harness then
created its own isolated installation. `rc-smoke.json` reports Python **3.11.18**,
`passed: true`, the same wheel SHA-256 and all six checks passed: clean-wheel, CLI,
real loopback HTTP, Single, Duo and Triad. Bootstrap and harness output is retained
in `smoke.log`. No live model credentials or external MCP service were used.

Reproduce Docker Desktop integration while retaining pytest's isolated HOME:

```python
import os
import subprocess

endpoint = subprocess.check_output(
    ["docker", "context", "inspect", "--format", "{{.Endpoints.docker.Host}}"],
    text=True,
).strip()
subprocess.run(
    ["uv", "run", "pytest", "-q", "tests/test_container_backend.py",
     "-m", "container_integration", "-ra",
     "--junitxml=artifacts/release-audit/docker-integration-junit.xml"],
    env={**os.environ, "DOCKER_HOST": endpoint},
    check=True,
)
```

## Remaining verification limits

The current local Docker Desktop container and installed-wheel checks passed.
This is supplemental macOS-hosted Linux VM evidence; it does not establish native
Linux/GitHub runner topology, other architectures, Podman or Windows. The configured
required GitHub CI job still needs an actual remote run. Restricted descriptor
resolution branches were reviewed and exercised with controlled Darwin probes;
the container execution tier does not turn those into native Linux host evidence.
No real provider or external MCP request, publication, tag creation, remote push
or reference-project modification was performed.

## Archive and pre-commit verification, 2026-11-18

The completed change was archived at
[`2026-11-18-fix-github-release-readiness`](../../../openspec/changes/archive/2026-11-18-fix-github-release-readiness/).
All sixteen tasks were complete. OpenSpec synchronized nine added requirements
across eight main specifications and validated the archive. The subsequent strict
validation passed `42 passed, 0 failed (42 items)`; the earlier 43-item total included
the then-active change. ACTION_PLAN now links to the archive.

Fresh Ruff lint and format checks passed (160 files), Golden passed 20/20, and the
wheel/sdist build passed. The rebuilt wheel has the same SHA-256 recorded above;
all 57 packaged source files match the checkout, so the installed-wheel smoke
evidence still applies to this exact wheel. The initial sandboxed build could not
resolve PyPI; the successful build used an authorized environment and a temporary
uv cache. No dependency manifests or reference-project files changed.

The first pre-commit full-suite attempt ran inside the restricted development
sandbox, which denied loopback port allocation, Docker socket access and the build
cache. Its original result and log are retained without treating skips as passes:

```text
PermissionError: [Errno 1] Operation not permitted
FAIL: Could not allocate a loopback port for denied.
15 failed, 3122 passed, 23 skipped in 238.14s (0:03:58)
```

Evidence: `artifacts/release-audit/precommit-pytest.log` and its JUnit XML. No source
changes were made in response to those environment failures. An independently
authorized Docker rerun passed `10 passed, 4 deselected in 13.99s`; its JUnit XML
records exactly ten tests with zero failures, errors or skips
(`precommit-docker.xml`).

The subsequent complete run in the authorized environment passed:

```text
3159 passed, 1 skipped in 277.69s (0:04:37)
```

`artifacts/release-audit/precommit-final-pytest.xml` records 3160 tests, zero failures,
zero errors and one skip. All ten `container_integration` cases ran successfully;
the only skip is the optional cross-interpreter digest check because `python3.11`
is not on PATH. Its log is `precommit-final-pytest.log`. This run followed the spec
sync and archive, and verifies the checkout to be committed. Earlier isolated Python
3.11 and installed-wheel checks retain the scopes described above.

## Subsequent credentialed acceptance

After the local fix commit `a2bc878`, the user authorized requests to a specific
MAAS gateway. The separate [live-model acceptance report](2026-11-18-live-model-acceptance.md)
records 15/15 real Golden cases and 3/3 stream checks, two generated images with
size mismatches, and failed Duo/Triad acceptance. The latter exposed a reproducible
restricted-worker standard-library submodule import defect. The offline gates
above remain historical measured results; they do not establish complete live-model
acceptance. That acceptance did not include a product-code fix. The subsequent
[restricted import fix and successful Duo/Triad rerun](2026-11-18-fix-restricted-stdlib-imports-verify.md)
records the resolution separately; the historical gates above are preserved.
