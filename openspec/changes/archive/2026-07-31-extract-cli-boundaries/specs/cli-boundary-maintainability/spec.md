## ADDED Requirements

### Requirement: CLI extraction is gated by six measured dimensions

M41 MUST record baseline, threshold, evidence, migration, and rollback trigger for performance, reliability, maintenance cost, compatibility, team capability, and migration/rollback risk before implementation. If any hard threshold cannot be met with the original measurement method, the extraction MUST stop and M41 implementation changes MUST be rolled back without altering pre-existing workspace changes.

#### Scenario: All six gates are measurable
- **WHEN** implementation begins
- **THEN** each metric has a concrete baseline, threshold, evidence source, migration step, and rollback trigger recorded in the M41 baseline

#### Scenario: A hard threshold fails
- **WHEN** a final same-method measurement still exceeds a threshold or detects a contract regression
- **THEN** M41 extraction changes are not accepted and the pre-M41 CLI implementation remains authoritative

### Requirement: CLI responsibilities have four internal boundaries

ForgeAgent SHALL separate parser/config, collaboration adapter, REPL, and HTTP/client responsibilities into private internal modules while keeping `forgeagent.cli` as the console entry point and compatibility façade. Internal boundary modules MUST NOT import `forgeagent.cli`, form dependency cycles, introduce a general dependency-injection framework, or own domain state that belongs to Task, Loop, Collaboration, MCP, Memory, Skills, or HTTP service models.

#### Scenario: A maintainer locates a CLI responsibility
- **WHEN** the maintainer inspects parser/config, collaboration adapter, REPL, or HTTP/client assembly
- **THEN** the responsibility is implemented in the corresponding named internal boundary and exposed through `forgeagent.cli` only where compatibility requires it

#### Scenario: Runtime dependencies are inspected
- **WHEN** the post-extraction dependency tree is compared with the baseline
- **THEN** no runtime dependency, framework, registry, or generated-code layer has been added for the extraction

### Requirement: Existing CLI and HTTP behavior remains unchanged

The extraction MUST preserve command names, option names, defaults, parser behavior, help bytes, stdout/stderr routing, exit codes, existing `forgeagent.cli` imports, supported monkeypatch locations, HTTP request/response shapes, cancellation semantics, and resource cleanup behavior. It MUST NOT add configuration, persistence, data migration, publication, tag, push, or package-index behavior.

#### Scenario: Existing help commands run
- **WHEN** the seven recorded top-level and subcommand help invocations are executed after extraction
- **THEN** their exit codes and stdout/stderr SHA-256 values match the pre-extraction baseline byte for byte

#### Scenario: Existing boundary tests run
- **WHEN** CLI, collaboration integration, HTTP, startup, and full regression tests execute
- **THEN** all previously passing scenarios still pass and M41 introduces no additional skip

#### Scenario: A test replaces a CLI dependency
- **WHEN** an existing test monkeypatches a supported `forgeagent.cli` class, callback, factory, or helper before invoking a façade entry point
- **THEN** the extracted implementation uses that replacement for the current call just as the pre-extraction implementation did

### Requirement: Extraction remains bounded and reversible

The final `cli.py` MUST contain no more than 1800 lines, each new boundary module MUST contain no more than 900 lines, and the runtime direct dependency count MUST remain at eight. Migration MUST proceed in the order parser/config, collaboration adapter, REPL, HTTP/client with targeted verification at each boundary, and each boundary MUST remain independently reviewable and revertible.

#### Scenario: Structural threshold is measured
- **WHEN** the final AST and file statistics are generated
- **THEN** `cli.py`, every extracted module, and the dependency tree satisfy the recorded maintenance thresholds

#### Scenario: One boundary regresses behavior
- **WHEN** targeted verification fails after a boundary extraction
- **THEN** that boundary is corrected or its M41 extraction is reverted before the next boundary begins
