# completion-integrity Specification

## Purpose
TBD - created by archiving change hardening-core-correctness. Update Purpose after archive.
## Requirements
### Requirement: Tool-bearing responses cannot complete a task
ForgeAgent MUST apply the two-stage eligibility check only to an explicit `completed: true` declaration: it MUST ignore that completion declaration in any response that also contains one or more tool calls and SHALL feed the tool results into a later round.

#### Scenario: Successful tool and completion declaration share a response
- **WHEN** a model response declares `completed: true` and invokes a tool that succeeds
- **THEN** ForgeAgent records the tool result, continues to another model round and does not mark the task complete from that response

#### Scenario: Failed tool and completion declaration share a response
- **WHEN** a model response declares `completed: true` and invokes a tool that fails
- **THEN** ForgeAgent records the failure, continues to another model round and does not mark the task complete

### Requirement: Parse errors prevent same-round completion
ForgeAgent MUST NOT complete a task from a response that contains protocol parse errors, even when that response also declares completion.

#### Scenario: Completion declaration accompanies a parse error
- **WHEN** a model response contains a parse error and `completed: true`
- **THEN** ForgeAgent feeds the parse error back for correction and keeps the task incomplete

### Requirement: Completion requires a standalone final response
ForgeAgent SHALL mark a single-role task complete only from a response that explicitly declares completion and contains neither tool calls nor protocol parse errors. In Duo/Triad mode, the same standalone Generator response SHALL mean only "submitted for evaluation"; ForgeAgent MUST mark the collaborative execution complete only after an independent Evaluator returns a valid structured pass for every frozen acceptance item.

#### Scenario: Standalone completion after tool feedback
- **WHEN** a tool-bearing response has been processed and a later response contains no tools, no parse errors and declares `completed: true` in single mode
- **THEN** ForgeAgent marks the task complete using the later response

#### Scenario: Standalone response does not declare completion
- **WHEN** a response contains no tools and no parse errors but does not declare completion
- **THEN** ForgeAgent does not fabricate a completed status

#### Scenario: Collaborative Generator submits for evaluation
- **WHEN** a Duo/Triad Generator produces an otherwise eligible standalone `completed: true` response
- **THEN** ForgeAgent starts an isolated Evaluator and does not yet report the collaborative execution as completed

#### Scenario: Evaluator rejects submitted work
- **WHEN** the independent Evaluator reports one or more frozen acceptance items as failed
- **THEN** ForgeAgent keeps the collaborative execution incomplete and either starts a bounded correction attempt or stops with a rejection report

### Requirement: Explicit non-completion keeps existing terminal semantics
An explicit `completed: false` declaration SHALL NOT be delayed, overwritten or reclassified by the two-stage completion eligibility check.

#### Scenario: Refused non-completion accompanies tool activity
- **WHEN** a response declares `completed: false` with status `refused` and also contains tool calls or parse errors
- **THEN** ForgeAgent preserves the existing `refused` terminal mapping rather than treating it as a blocked completion declaration

#### Scenario: Need-info or failed non-completion accompanies tool activity
- **WHEN** a response declares `completed: false` with status `need_info` or `failed` and also contains tool calls or parse errors
- **THEN** ForgeAgent preserves the existing corresponding terminal mapping rather than delaying it to a later round

