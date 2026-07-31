## MODIFIED Requirements

### Requirement: Completion requires a standalone final response
ForgeAgent SHALL mark a single-role task complete only from a response that explicitly declares completion, contains neither tool calls nor protocol parse errors, and has a non-empty body after protocol whitespace normalization. In Duo/Triad mode, the same standalone Generator response SHALL mean only "submitted for evaluation"; ForgeAgent MUST mark the collaborative execution complete only after an independent Evaluator returns a valid structured pass for every frozen acceptance item.

#### Scenario: Standalone completion after tool feedback
- **WHEN** a tool-bearing response has been processed and a later response contains no tools, no parse errors, a non-empty body and declares `completed: true` in single mode
- **THEN** ForgeAgent marks the task complete using the later response

#### Scenario: Empty standalone response does not complete
- **WHEN** a response declares `completed: true` but its body is empty or whitespace-only
- **THEN** ForgeAgent keeps the task incomplete and emits the existing empty-response correction feedback

#### Scenario: Collaborative Generator submits for evaluation
- **WHEN** a Duo/Triad Generator produces an otherwise eligible standalone `completed: true` response with a non-empty body
- **THEN** ForgeAgent starts an isolated Evaluator and does not yet report the collaborative execution as completed

#### Scenario: Evaluator rejects submitted work
- **WHEN** the independent Evaluator reports one or more frozen acceptance items as failed
- **THEN** ForgeAgent keeps the collaborative execution incomplete and either starts a bounded correction attempt or stops with a rejection report
