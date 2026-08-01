# repository-lifecycle-integrity Specification

## Purpose
Define traceable, current-baseline-safe recovery of the authorized M29-M38 lifecycle evidence set and descriptive canonical specifications.
## Requirements
### Requirement: Completed milestones retain a traceable lifecycle chain

ForgeAgent SHALL keep a repository-local evidence chain for the authorized M29-M38 recovery set: M29-M32 and M35-M38. Every milestone in that set MUST have a milestone record, and each referenced archived change, technical design, implementation plan, and verification report MUST exist. Historical verification counts MUST be identified as evidence for their original snapshot rather than current HEAD. M39 and later milestones remain governed by their current milestone records and are not recursively rewritten by this historical recovery.

#### Scenario: Historical milestone evidence is inspected
- **WHEN** a reviewer follows a restored M29-M38 milestone link
- **THEN** every referenced repository artifact exists and the record distinguishes historical counts from the current baseline verifier

#### Scenario: A lifecycle artifact disappears
- **WHEN** a required milestone, archive, design, plan, or report is removed or renamed without updating its references
- **THEN** the offline lifecycle contract test fails with the missing path

### Requirement: Archived changes retain verified terminal state

Every recovered Comet change MUST remain under `openspec/changes/archive/` and its `.comet.yaml` MUST record `phase: archive`, `verify_result: pass`, and `archived: true`. Recovery MUST NOT recreate an active publication change or represent a canceled PyPI goal as pending work.

#### Scenario: Recovered archive is audited
- **WHEN** M45 validates a recovered M29-M38 archive
- **THEN** the archive has verified terminal state and no corresponding active change is created

#### Scenario: Removed distribution goal is reviewed
- **WHEN** historical M38 publication records are read
- **THEN** they preserve the canceled history without restoring PyPI, a formal tag, or publication automation as a current roadmap item

### Requirement: Current baseline wins over historical recovery sources

Artifact recovery MUST NOT overwrite a newer current milestone pointer, borrowing-review baseline, HTTP action approval contract, or MCP progressive-disclosure contract with an older historical version. An explicitly authorized development-branch push MUST remain distinguishable from package publication, a formal release tag, or publication automation.

#### Scenario: Historical and current files conflict
- **WHEN** a recovery source differs from an existing M44 or later baseline file
- **THEN** the current file is retained and the rejected historical source is recorded in the reconciliation report

### Requirement: Canonical specifications have descriptive purposes

Every `openspec/specs/*/spec.md` MUST contain a non-placeholder Purpose describing the capability boundary and MUST NOT contain delta-only section headings such as `ADDED Requirements`, `MODIFIED Requirements`, or `REMOVED Requirements`.

#### Scenario: Archive template leaves a placeholder
- **WHEN** a canonical spec contains `TBD - created by archiving` or a delta-only heading
- **THEN** the offline lifecycle contract test fails before the change can be accepted

### Requirement: Reconciled runtime claims retain executable verifiers

When a completed runtime capability is reconciled into the current baseline, ForgeAgent SHALL retain executable regression tests for its security, compatibility, and trust-boundary claims. Historical milestone text or an archived change alone MUST NOT be treated as current executable proof.

#### Scenario: Runtime Skill exit contract is reconciled
- **WHEN** M45 audits the completed M34 runtime Skill exit contract
- **THEN** the current test suite directly verifies valid version 2 contracts, fail-closed invalid inputs, legacy compatibility, secret masking, immutable exit metadata, and effective trust digest changes

#### Scenario: A critical verifier disappears
- **WHEN** the M34 implementation and specifications remain but its executable contract tests are removed
- **THEN** the repository lifecycle verification fails before the baseline is declared complete
