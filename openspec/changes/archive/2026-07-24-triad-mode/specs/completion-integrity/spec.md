## MODIFIED Requirements

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

