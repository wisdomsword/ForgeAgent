## ADDED Requirements

### Requirement: Invalid tool identity types remain recoverable
The parser MUST reject a non-string tool name as a structured parse error without raising an exception.

#### Scenario: Tool name is an array or object
- **WHEN** a text tool call supplies an array, object, boolean or null name
- **THEN** parsing returns an invalid-format error and the task can request correction
