## ADDED Requirements

### Requirement: Task terminal outcomes disclose attempted tools
Every ForgeAgent Task MUST maintain an ordered, task-scoped record of tools that reached an execution attempt and MUST expose a bounded terminal projection containing each tool's stable name and stable outcome status. The projection MUST remain available when the Task completes, answers in prose, stops, fails, refuses, needs information, or is cancelled, and MUST NOT claim that a tool ran when it was only parsed but never attempted.

#### Scenario: Successful and failed tools are reported
- **WHEN** a Task attempts one tool successfully and a later tool fails before the Task terminates
- **THEN** the terminal evidence lists both attempted tools in deterministic order with distinct stable success and failure statuses

#### Scenario: Parsed tool after a terminal submission is not reported as attempted
- **WHEN** a response contains a terminal structured submission followed by another parsed tool that the runtime intentionally does not execute
- **THEN** terminal evidence includes the submission attempt but does not represent the skipped later tool as executed

#### Scenario: Direct prose uses an empty evidence projection
- **WHEN** a Task terminates as `answered_in_prose` without attempting any tool or program
- **THEN** the terminal projection explicitly represents that no tools or programs were executed and does not fabricate evidence

### Requirement: Executed generated code has a task-owned program artifact
Before ForgeAgent dispatches generated code to any trusted, restricted, or container execution backend, it MUST persist the exact code selected for that execution attempt as a regular file in a host-owned task artifact directory and associate the tool attempt with a stable task-relative artifact reference. This requirement applies to both stored named blocks and inline Exec code. Model-supplied block path metadata MUST NOT select or escape the host-owned artifact directory.

#### Scenario: Named block execution is persisted
- **WHEN** Exec resolves and prepares to run a stored named code block
- **THEN** ForgeAgent atomically writes the selected block version to the Task's program artifact directory before backend dispatch and associates that execution attempt with its artifact reference

#### Scenario: Inline Exec is persisted
- **WHEN** Exec receives inline generated code rather than a stored block name
- **THEN** ForgeAgent atomically writes the inline code to the same Task-owned program artifact contract before backend dispatch and associates that execution attempt with its artifact reference

#### Scenario: Restricted and container execution retain a file artifact
- **WHEN** generated code is delivered to a restricted or container worker through an in-memory or stdin payload
- **THEN** the host still retains the corresponding task-owned program file and reports its reference independently of the worker transport

#### Scenario: Model path metadata cannot redirect persistence
- **WHEN** a parsed code block supplies an absolute path, traversal path, symbolic-link target, or other path metadata outside the Task artifact directory
- **THEN** ForgeAgent ignores that metadata for program persistence, generates a safe host-owned artifact name, and does not write outside the artifact directory

#### Scenario: Artifact directories are replaced or linked
- **WHEN** any `.forgeagent/execution-artifacts` directory component is a symbolic link or is rebound while a program is being published
- **THEN** ForgeAgent fails the Exec attempt without backend dispatch and does not write through the linked or replacement directory

### Requirement: Program artifact persistence fails closed
ForgeAgent MUST NOT dispatch generated code to an execution backend when its required program artifact cannot be created atomically as a safe regular file. The failed Exec attempt MUST remain in terminal evidence with a stable artifact-persistence failure status and MUST NOT expose a misleading program path.

#### Scenario: Artifact directory is unavailable
- **WHEN** ForgeAgent cannot create or safely open the Task program artifact directory before an Exec attempt
- **THEN** Exec fails without dispatching code to any backend and terminal evidence reports a stable persistence failure without a fabricated artifact reference

#### Scenario: Artifact write fails before replacement
- **WHEN** writing or atomically publishing a program artifact fails
- **THEN** ForgeAgent does not execute a partial or unrecorded program and does not expose a partial file as a valid artifact

#### Scenario: Per-task program capacity is exceeded
- **WHEN** an Exec would exceed 100 programs, 1 MiB for one program, or 8 MiB across one Task
- **THEN** ForgeAgent returns the stable `artifact_persistence_failed` evidence status, does not dispatch that code, and does not expose a fabricated artifact reference

### Requirement: Execution evidence projections are entrypoint-safe
ForgeAgent MUST render one terminal execution-evidence summary for CLI, HTTP, Loop, Duo, and Triad task operations. Local CLI output SHALL show the local path for every persisted program artifact available on that host. HTTP output MUST expose only bounded safe task-relative artifact references and MUST NOT expose host absolute paths. Loop and collaboration reports MUST aggregate child Task evidence with stable origin metadata and global bounds.

#### Scenario: CLI displays local program paths once
- **WHEN** a local CLI or REPL Task terminates after executing generated code
- **THEN** the terminal result contains one summary of attempted tools and statuses plus each available local program path, without repeating the summary after every round

#### Scenario: HTTP displays only relative references
- **WHEN** an authenticated HTTP caller queries a terminal Task that executed generated code
- **THEN** the response contains bounded tool statuses and safe task-relative artifact references but no host absolute path or code content

#### Scenario: Loop aggregates attempted evidence
- **WHEN** a Loop terminates after one or more iterations attempted tools or programs
- **THEN** its terminal report includes a bounded deterministic aggregation that identifies the originating iteration without exposing child prompts, raw arguments, code, or absolute host paths

#### Scenario: Collaboration aggregates attempted evidence
- **WHEN** a Duo or Triad terminates after one or more role attempts used tools or programs
- **THEN** its terminal report includes a bounded deterministic aggregation that identifies the originating role and attempt without exposing role conversations, raw arguments, code, or absolute host paths

#### Scenario: Cancellation retains prior attempts
- **WHEN** a Task, Loop, Duo, or Triad is cancelled after some tools were attempted
- **THEN** the terminal evidence retains those prior attempts and does not fabricate evidence for work prevented by cancellation

### Requirement: Public execution evidence is bounded and minimally disclosing
Every public execution-evidence projection MUST enforce a deterministic 32-item bound, fixed text bounds, stable ordering, masking, and explicit truncation and omitted-count fields. It MUST NOT include raw tool arguments, credentials, full prompts, generated code content, arbitrary file contents, unbounded stdout or stderr, raw exceptions, or host absolute paths outside a local CLI path field.

#### Scenario: Evidence exceeds the public item bound
- **WHEN** a Task or aggregate report contains more execution records than the public projection allows
- **THEN** ForgeAgent returns the first 32 records in deterministic order with explicit truncation and omitted-count fields and preserves the terminal status

#### Scenario: Tool metadata contains sensitive material
- **WHEN** internal tool metadata, block labels, errors, or artifact metadata contain known secrets or unsafe display characters
- **THEN** the public projection masks and bounds the value or replaces it with a stable safe value without changing the underlying execution result
