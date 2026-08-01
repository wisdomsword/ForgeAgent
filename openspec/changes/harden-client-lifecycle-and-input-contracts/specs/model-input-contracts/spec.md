## ADDED Requirements

### Requirement: Generation parameters reject invalid numeric values

`GenerationParams` MUST reject `max_output_tokens` when it is zero or negative. It MUST reject `timeout_seconds` when it is zero, negative, NaN, or infinite. Existing defaults and all positive finite values MUST remain accepted.

#### Scenario: Invalid generation limit
- **WHEN** a caller constructs `GenerationParams(max_output_tokens=0)` or with a negative value
- **THEN** model validation fails before provider request construction

#### Scenario: Invalid timeout
- **WHEN** a caller constructs `GenerationParams(timeout_seconds=0)`, a negative value, NaN, or infinity
- **THEN** model validation fails before Task execution

#### Scenario: Positive default remains compatible
- **WHEN** a caller constructs `GenerationParams()` or supplies a positive finite timeout and output limit
- **THEN** construction succeeds and existing provider defaults/translation remain unchanged

### Requirement: Registry capability limits are positive

`ModelCapability` and `ModelEntry` MUST reject zero or negative `context_window` and `max_output_tokens` values. Registry loading MUST fail with its existing structured registry error path when an entry violates these bounds.

#### Scenario: Invalid model registry entry
- **WHEN** a model entry declares a zero or negative context window or output ceiling
- **THEN** registry validation rejects the entry before it becomes selectable

#### Scenario: Valid large model entry
- **WHEN** a model entry declares positive integer capability limits within the existing configuration format
- **THEN** registry loading and capability projection remain unchanged

### Requirement: Request fallback distinguishes absence from invalidity

Provider request builders MUST use explicit `None` checks for optional output limits rather than truthiness fallback, so validation and defaulting cannot silently convert zero or other invalid values into a provider default.

#### Scenario: Explicit positive override
- **WHEN** `max_output_tokens` is a positive value
- **THEN** the provider request uses that exact value

#### Scenario: Omitted override
- **WHEN** `max_output_tokens` is `None`
- **THEN** the provider request uses the model capability ceiling as before
