## ADDED Requirements

### Requirement: Skill disk reads are bounded before parsing
Skill loading MUST read no more than its disk limit plus one byte and MUST reject oversized content before decoding or parsing it, while preserving native and standard compatibility semantics.

#### Scenario: Oversized Skill is present
- **WHEN** a Skill file exceeds the maximum supported disk size
- **THEN** it is excluded using a bounded read and other valid Skills remain available
