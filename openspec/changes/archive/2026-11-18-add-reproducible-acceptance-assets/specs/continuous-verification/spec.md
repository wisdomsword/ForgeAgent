## ADDED Requirements

### Requirement: Public model acceptance is reproducible and explicitly authorized
The repository MUST provide credential-free configuration examples and an acceptance entry point for the documented text, collaboration and image checks. Its default execution MUST validate and show the plan without network requests or credentials. Paid execution MUST require explicit opt-in, use a finite request budget and a fresh ignored evidence directory, and redact known sensitive values from saved responses. Examples MUST NOT include real keys or a fixed private gateway endpoint.

#### Scenario: Contributor validates the example without credentials
- **WHEN** a fresh checkout invokes the acceptance entry point without paid opt-in
- **THEN** it displays the selected checks without network access or creating runtime evidence

#### Scenario: Collaboration claims completion with an incorrect candidate
- **WHEN** the model reports completed but the candidate fails independent function or unittest checks
- **THEN** acceptance fails and preserves the failure result

#### Scenario: Image service ignores the requested dimensions
- **WHEN** a generated PNG has dimensions different from those requested
- **THEN** the image evidence is retained but parameter acceptance fails

#### Scenario: Request budget is exhausted
- **WHEN** execution reaches its configured request limit
- **THEN** no further provider request is sent and acceptance records a failure
