## ADDED Requirements

### Requirement: File reads and worker results have ingress bounds
FileRead MUST reject non-regular files without blocking and MUST enforce a byte limit while reading. Execution stdout, stderr and the worker result frame MUST be bounded before host accumulation, with explicit failure or truncation. Restricted code MUST use the task project working directory independently of its filesystem authority. External result text MUST render literally.

#### Scenario: FIFO or oversized file is requested
- **WHEN** FileRead targets a FIFO or a file larger than its supported byte limit
- **THEN** it returns a stable failure without blocking or reading the complete oversized file

#### Scenario: Execution produces excessive output or state
- **WHEN** a worker prints beyond the capture limit or returns an oversized state frame
- **THEN** retained output is bounded and truncation or rejection is disclosed

#### Scenario: Host and project directories differ
- **WHEN** restricted execution writes a relative file for a project different from the host cwd
- **THEN** the file is written within that project

#### Scenario: Result includes Rich delimiters
- **WHEN** a model response or tool result contains unmatched Rich tags
- **THEN** the literal text is displayed without a rendering exception
