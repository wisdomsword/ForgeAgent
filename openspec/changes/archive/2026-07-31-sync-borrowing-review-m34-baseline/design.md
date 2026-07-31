## Context

M34 delivered runtime Skill exit-contract enforcement, but the two review planning documents still identify M32 as the current baseline. This is a documentation-only consistency gap.

## Goals / Non-Goals

**Goals:**

- Update both review documents to M34.
- State the completed runtime Skill enforcement and preserve the two genuinely conditional candidates.
- Add deterministic offline assertions for baseline, completion, and release freeze.

**Non-Goals:**

- No source code, runtime spec, dependency, Memory data, or release change modifications.
- No PyPI upload, tag, push, or publish workflow advancement.

## Decisions

- Modify only the two review documents and their existing roadmap test.
- Keep M33 historical traceability and M34 as `milestones/latest`.
- Use exact marker assertions rather than broad prose checks so future drift fails locally.

## Risks / Trade-offs

- [Risk] Marker tests can be overly literal → Mitigation: assert only stable facts (M34, archived runtime change, conditional candidates, release freeze).

## Migration Plan

No data migration. The document edits take effect immediately for the next planning session.

## Open Questions

None.
