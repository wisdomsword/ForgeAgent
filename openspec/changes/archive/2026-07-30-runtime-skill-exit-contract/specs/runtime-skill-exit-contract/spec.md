## ADDED Requirements

### Requirement: Versioned Skills declare bounded exit contracts
Runtime Skill documents declaring `format_version: 2` SHALL include exactly five exit classes: `success`, `failure`, `blocked`, `needs_input`, and `timeout_or_budget`. Each class MUST contain non-empty string fields `condition` and `verifier`, each bounded to 512 UTF-8 bytes. The runtime MUST reject an absolute, unbounded claim when it is the only condition text, including claims that rely solely on words such as "always", "never", "all", "100%", or "完美".

#### Scenario: Version 2 Skill with complete exits is accepted
- **WHEN** a Skill front matter declares `format_version: 2` and all five exit classes contain bounded condition and verifier strings
- **THEN** the Skill enters the immutable registry and its structured exits are available to the read-only Skill tool

#### Scenario: Version 2 Skill missing one exit is isolated
- **WHEN** a version 2 Skill omits `blocked` or gives it an empty field
- **THEN** the runtime skips that Skill, emits one bounded `invalid exit contract` diagnostic, and continues discovering other Skills

#### Scenario: Version 2 Skill uses an unbounded absolute condition
- **WHEN** a version 2 Skill uses only an absolute claim such as `100% complete` as an exit condition
- **THEN** the runtime skips that Skill with an `invalid exit contract` diagnostic

### Requirement: Legacy Skill compatibility is explicit and bounded
Runtime Skills without `format_version` SHALL continue to use the existing five-section parser and SHALL be represented as legacy definitions. Legacy definitions MUST NOT be treated as satisfying the version 2 exit contract, and the runtime SHALL expose their version so callers can distinguish compatibility from governed declarations.

#### Scenario: Existing legacy Skill remains readable
- **WHEN** a pre-existing Skill has only `name`, `trigger`, `Steps`, `Failure Branches`, and `Completion Criteria`
- **THEN** the Skill remains discoverable with `format_version` equal to 1 and its existing full/section reads are unchanged

#### Scenario: Unsupported format version is isolated
- **WHEN** a Skill declares a format version other than 1 or 2
- **THEN** the runtime skips it with a bounded `invalid format version` diagnostic

### Requirement: Trust and reads include the governed contract
The runtime SHALL include a version 2 Skill's five exit classes in deterministic full rendering and project trust effective-input digests. The read-only Skill tool SHALL allow the `exit_conditions` section and SHALL return a deterministic structured rendering without exposing unmasked secret values.

#### Scenario: Project approval covers exit conditions
- **WHEN** a trusted project Skill changes only one exit condition or verifier
- **THEN** its effective-input digest changes and the project Skill requires re-confirmation before overriding a user Skill

#### Scenario: Exit conditions are read by section
- **WHEN** the model requests `exit_conditions` for a governed Skill
- **THEN** the tool returns the five named classes and their condition/verifier pairs, with secrets masked
