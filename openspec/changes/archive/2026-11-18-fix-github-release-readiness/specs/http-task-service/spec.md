## ADDED Requirements

### Requirement: Invalid HTTP enum field types are client errors
HTTP request validation MUST reject non-string enum fields with status 400 rather than an internal error.

#### Scenario: Mode is an array or object
- **WHEN** an authenticated request supplies an array, object, boolean or null task or collaboration mode
- **THEN** the service returns invalid_request with status 400 and does not create a task
