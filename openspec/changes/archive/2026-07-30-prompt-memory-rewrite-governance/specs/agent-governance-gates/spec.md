# agent-governance-gates Specification

## ADDED Requirements

### Requirement: Long-lived Prompt and Skill instructions declare bounded exits

The project SHALL require every newly added or materially changed long-lived Prompt or Skill instruction to declare five exit classes: success, failure, blocked, needs-input, and timeout-or-budget. Each exit declaration MUST name an observable condition and the responsible verifier, and MUST NOT use an unbounded absolute claim as its only acceptance condition. A model upgrade MUST record the model version, a runnable minimum regression set, and whether stale scaffolding was retired.

#### Scenario: A new Skill is proposed
- **WHEN** a change adds or materially changes a long-lived Skill or Prompt instruction
- **THEN** its proposal or design records all five exit classes, a bounded condition for each, and the verifier that observes the condition
- **THEN** its proposal or design records all five exit classes, a bounded condition for each, the verifier that observes the condition, the model version, the minimum regression set, and stale-scaffolding disposition

#### Scenario: A prompt instruction lacks a verifier
- **WHEN** a proposed instruction has prose guidance but no observable verifier or exit condition
- **THEN** the change is rejected by the governance review until the condition and verifier are added or the instruction is removed

### Requirement: Durable Memory proposals answer the four governance questions

The project SHALL require every proposal to write or change durable project Memory to answer who can write it, what source is authoritative truth, when the item expires or is revalidated, and which copy recovers after a crash. The proposal SHALL additionally record why the item is remembered, who can see it, and how a user deletes or corrects it. Session-only Memory MAY use the session boundary as its visibility and recovery answer, but SHALL still identify its writer, source, and correction behavior.

#### Scenario: A project Memory write is proposed
- **WHEN** a change adds or changes a durable project Memory path
- **THEN** the design records writer authority, purpose, authoritative source, expiry or revalidation rule, visibility, recovery copy, and deletion/correction action

#### Scenario: A Memory item becomes stale
- **WHEN** its expiry or revalidation condition is reached
- **THEN** the process stops treating it as authoritative and records the required revalidation or correction path instead of silently refreshing it

### Requirement: Rewrite and dependency changes pass a six-metric gate

The project SHALL require a large rewrite or new runtime dependency to provide a baseline, threshold, evidence source, migration plan, and rollback plan for performance, reliability, maintenance cost, compatibility, team capability, and migration/rollback risk. A rewrite MUST NOT be justified solely by model quality, novelty, or an unmeasured architectural preference.

#### Scenario: A rewrite is proposed
- **WHEN** a change replaces a module, execution backend, language layer, or introduces a runtime dependency with cross-module impact
- **THEN** the design includes six metric rows with baseline, threshold, evidence source, migration steps, and rollback trigger

#### Scenario: A rewrite gate is not met
- **WHEN** one or more metrics lacks a baseline, threshold, or evidence source
- **THEN** the change remains exploratory and cannot enter implementation as an approved rewrite

### Requirement: Governance gates are regression-tested and release-neutral

The project SHALL keep a local, deterministic document contract test for the governance gate. The test MUST check the five Prompt/Skill exits, the Memory questions including visibility and correction, the six rewrite metrics, and the release pause wording. The gate MUST NOT publish artifacts, create tags, push remotes, or advance the active PyPI release change.

#### Scenario: Governance wording is accidentally removed
- **WHEN** a required heading, field, or release-pause guard is deleted from the canonical governance document
- **THEN** the document contract test fails with the missing contract name

#### Scenario: Governance verification runs in CI
- **WHEN** the contract test runs in an offline test environment
- **THEN** it completes without network access, model credentials, package upload, tag creation, or remote push
