# Third-Party Notices

ForgeAgent is licensed under the MIT License; see [LICENSE](LICENSE).

Everything in this repository is original work written for this project **except** the files
listed below. Each entry states what the material is, where it comes from, and how that
provenance was checked.

## Comet skill snapshots

| | |
| --- | --- |
| Paths | `openspec/changes/archive/**/.comet/skill-snapshots/<skill-id>/{package.json,sha256}` |
| Count | 162 files — 81 change directories × 2 files |
| Origin | `@rpamis/comet` v0.4.5, MIT License, Copyright (c) 2026 rpamis |
| What it is | Snapshot of one Comet skill definition: `apiVersion: comet/v1alpha1`, `kind: Skill`, `metadata.name: comet-classic`, version 1 |
| Role here | Workflow metadata captured by the Comet harness at the start of each change. Build/tooling audit record — not product code, not a runtime dependency of ForgeAgent |

Provenance checks, all performed against the installed `@rpamis/comet`:

- All 81 `package.json` copies are byte-identical: 7,775 bytes, SHA-256
  `266794f984a4656ca72632540286fc980b67eea54332ed6e3f893936416eedca`.
- All 81 `sha256` copies are byte-identical.
- All 81 snapshots reference a single skill id,
  `e211dc93b4bbc218965022f6d64f54a26e2240bd45b8bf6e1321ceb96775a3a3` — this is one skill
  duplicated across 81 changes, not 81 distinct skills.
- The distinctive definition text inside the snapshot also appears in `@rpamis/comet`'s own
  vendored skill tree (`eval/local/skills/benchmarks/.../runtime/classic/skill.yaml`), which
  is how the upstream origin was established.

Two things worth knowing:

- The file named `sha256` stores the **skill identifier**, not a digest of `package.json`.
  The actual digest of `package.json` is the `266794f9...` value above. The two differ, so do
  not treat that file as a checksum.
- The snapshot carries no `license`, `copyright`, or `author` field of its own. Its terms come
  from `@rpamis/comet`, which is MIT.

If you do not want these in the published history, they can be dropped wholesale: deleting a
change's `skill-snapshots/` directory removes its audit record but nothing else, because no
code, spec, or test references the path.

## Plans, specs, verification reports, and evaluation transcripts

| | |
| --- | --- |
| Paths | `docs/superpowers/**` (164 files), `docs/evaluation/**` (392 files) |
| Origin | Written for this project |
| Attribution needed | None — no upstream source was found, so there is nothing to credit |

Checks:

- No file in `docs/superpowers/` carries a LICENSE, copyright, or SPDX header, so these are not
  verbatim downstream copies of another project's document set.
- 36 of the 164 files carry one boilerplate line naming the upstream `superpowers` skill
  workflow (`REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development ...`). That is a
  pointer to a skill *name and workflow convention*, not reproduced content. This line was not
  compared against an upstream source copy — none is available in this environment — so the
  reference is disclosed rather than characterised as original.
- `docs/evaluation/` holds generated evaluation transcripts: model runs, raw JSON outputs,
  environment metadata, and run-level `INVALID.md` markers. They record what happened during
  benchmarking; they are evidence, not code.
- Scanned all three corpora together (35,887 lines, ~2.7 MB) for secret-shaped strings. Zero
  real matches. The only hit was the deliberate test fixture
  `sk-testkeyabcdef1234567890longenough` in
  `docs/superpowers/plans/2026-07-17-compose-runtime-identity.md`, inside an illustrative
  snippet that asserts the value does *not* leak into a snapshot.

## Reviewer agent definition

| | |
| --- | --- |
| Path | `.claude/agent/code-reviewer.md` (1 file) |
| Origin | Written for this project |

A local agent persona definition for code review. No upstream source.

## What is deliberately *not* in this repository

`resource/` is gitignored and contains zero tracked files. That directory holds a third-party
reference implementation kept locally for comparison only. It is not distributed here and
nothing in `src/` depends on it.

`.worktrees/` and `.codegraph/` are also gitignored.
