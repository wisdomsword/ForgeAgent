## ADDED Requirements

### Requirement: Tool-bearing responses cannot complete a task
ForgeAgent MUST ignore a completion declaration in any response that also contains one or more tool calls and SHALL feed the tool results into a later round.

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
ForgeAgent SHALL mark a task complete only from a response that explicitly declares completion and contains neither tool calls nor protocol parse errors.

#### Scenario: Standalone completion after tool feedback
- **WHEN** a tool-bearing response has been processed and a later response contains no tools, no parse errors and declares `completed: true`
- **THEN** ForgeAgent marks the task complete using the later response

#### Scenario: Standalone response does not declare completion
- **WHEN** a response contains no tools and no parse errors but does not declare completion
- **THEN** ForgeAgent does not fabricate a completed status
