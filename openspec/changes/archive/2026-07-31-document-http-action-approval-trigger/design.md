## Context

M35 synchronized the review documents to the M34 runtime Skill baseline. A second consistency audit found that the detailed borrowing table still calls HTTP approval binding partially covered, while the summary says only Memory migration and Rewrite/dependency work remain triggerable. ForgeAgent currently restricts its HTTP service to loopback and bearer-token access; it does not provide a remote action control plane.

## Goals / Non-Goals

**Goals:**

- Make the review documents agree about the HTTP approval-binding gap.
- State a concrete trigger and a minimal future scope for that candidate.
- Preserve an offline, testable record that the candidate is not active today.

**Non-Goals:**

- Do not add remote HTTP access, action approval APIs, new receipt types, or identity schema changes.
- Do not migrate Memory, introduce dependencies, or alter the paused release change.

## Decisions

- Treat the item as a conditional candidate, not a new milestone commitment, because no remote-control requirement exists today.
- Use the existing borrowing-review-baseline specification and add a delta requirement for the candidate rather than creating a second governance spec.
- Require a future trigger of an externally reachable HTTP action surface and a real verifier before implementation can be proposed.

## Risks / Trade-offs

- [Risk] Future readers may interpret the candidate as delivered. -> Explicitly state current loopback-only scope and no runtime change in both documents and the test.
- [Risk] The trigger may be too vague. -> Name the minimum evidence: a concrete remote action, approval fields, and a verifier that binds the approval to the action digest/scope.

