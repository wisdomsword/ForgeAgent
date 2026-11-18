# Third-Party Notices

ForgeAgent is licensed under the MIT License; see [LICENSE](LICENSE).
Everything in this repository is original work written for this project except the items below.

## Generated and templated documents

- `docs/superpowers/` (164 files) — plans, specs and verification reports written for this
  project. 36 of them carry one boilerplate line naming the upstream `superpowers` skill
  workflow (`REQUIRED SUB-SKILL: Use superpowers:…`). That line points at a skill name and a
  workflow convention; it is not reproduced content. No upstream copy exists here to compare
  against, so it is disclosed rather than treated as original.
- `docs/evaluation/` (392 files) — generated evaluation transcripts: model runs, raw JSON,
  environment metadata and run-level `INVALID.md` markers. Evidence, not code.
- `.claude/agent/code-reviewer.md` — a local code-review agent definition.

The only secret-shaped string in either tree is the deliberate test fixture
`sk-testkeyabcdef1234567890longenough` in
`docs/superpowers/plans/2026-07-17-compose-runtime-identity.md`, inside a snippet that asserts
the value must not leak into a snapshot.

## Not distributed

`resource/` is gitignored and tracks zero files. It holds a third-party reference implementation
kept locally for comparison only; nothing in `src/` depends on it.

`.worktrees/` and `.codegraph/` are also gitignored.

## Python dependencies and redistribution

The ForgeAgent source archive and wheel include ForgeAgent's MIT license and this notice.
Python dependencies are installed separately. Their upstream license and copyright terms
continue to apply. See the [dependency license inventory](docs/security/dependency-inventory-2026-11-18.json)
for the versions and license files examined on 2026-11-18. Check the exact artifacts
again when preparing a distribution with bundled dependencies.

- Keep each dependency's copyright, license and disclaimer. Where an Apache-2.0
  distribution supplies a NOTICE, retain the applicable notices.
- certifi and tqdm contain MPL-2.0 covered files. For bundled distributions, retain
  the notices and follow MPL source availability requirements for the covered files.
  tqdm also contains MIT licensed contributions.
- For Windows bundles, pywin32 includes separate component terms. The audited wheel
  contains LGPL 2.1 license text for adodbapi, along with BSD-style, MIT and Scintilla
  terms for other components. Retain all component notices and review corresponding
  source and recipient rights for the exact Windows artifact before distributing it.

Apply the same artifact-level review to an offline archive or container that embeds
dependencies. A package's top-level metadata may omit licenses for included components.
