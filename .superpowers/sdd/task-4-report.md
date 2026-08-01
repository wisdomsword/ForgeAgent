# M47 Task 4 Report

- Status: complete
- Commit: `a0be1cf`
- Changed files: `tests/test_repository_lifecycle.py`

## Implementation

- Replaced interpreter-sensitive `ast.dump` hashing with AST-selected source segments.
- Normalized CRLF/CR line endings, joined segments with a fixed blank-line separator, and hashed UTF-8 bytes.
- Preserved top-level function/assignment lookup and missing-symbol reporting.
- Updated the protected M34 Skill and SkillTool digests to the canonical source-slice representation.
- Added source mutation coverage and a Python 3.11/3.12/3.14 subprocess stability probe.
- Review-fix: added `_supported_interpreters_or_skip()` and a regression test proving missing supported interpreters produce an explicit pytest environment skip instead of a silent return; the subprocess stability assertion remains unchanged when all interpreters are available.

## TDD evidence

- RED: Python 3.11 lifecycle verifier failed against the pre-implementation digest (`3361044e...` vs the new canonical digest), while the mutation test passed.
- GREEN: focused verifier and mutation tests pass under Python 3.11, 3.12, and 3.14 (`3 passed` each); repository lifecycle tests pass under the active interpreter (`9 passed, 1 skipped`); Ruff check and format pass.

## Risk signals

- The digest intentionally remains sensitive to selected source formatting/content changes, so governed verifier edits still require digest reconfirmation.
- The cross-version probe skips only when one of the supported interpreter executables is unavailable; CI environments with all supported interpreters exercise the full assertion.
