## ADDED Requirements

### Requirement: Borrowing candidates are evidence-mapped before completion

The project SHALL map every borrowing candidate marked complete to an archived OpenSpec change,
milestone, or verification report that states its delivered scope and boundaries. A candidate list
MUST NOT be treated as an execution queue, and deferred or conditional candidates MUST state the
trigger or independent change required before implementation.

#### Scenario: Completed candidate has evidence

- **WHEN** a borrowing candidate is marked complete in the planning baseline
- **THEN** the baseline names an archived change or milestone and a verifier-visible scope boundary

#### Scenario: Candidate remains deferred or conditional

- **WHEN** a candidate is not authorized for implementation
- **THEN** the baseline records its deferred/conditional status and the trigger or independent change
  required before work begins
