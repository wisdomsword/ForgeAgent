## MODIFIED Requirements

### Requirement: Existing CLI and HTTP behavior remains unchanged

The extraction MUST preserve command names, option names, defaults, parser behavior, help bytes, stdout/stderr routing, exit codes, existing `forgeagent.cli` imports, supported monkeypatch locations, HTTP request/response shapes, cancellation semantics, and resource cleanup behavior. It MUST NOT add configuration, persistence, data migration, publication, tag, push, or package-index behavior. The lifecycle hardening MUST make cleanup deterministic without changing any successful or failed public projection.

#### Scenario: Existing help commands run
- **WHEN** the seven recorded top-level and subcommand help invocations are executed after lifecycle hardening
- **THEN** their exit codes and stdout/stderr SHA-256 values match the pre-change baseline byte for byte

#### Scenario: Existing boundary tests run
- **WHEN** CLI, collaboration integration, HTTP, startup, model, and full regression tests execute
- **THEN** all previously passing scenarios still pass and the change introduces no additional skip

#### Scenario: A test replaces a CLI dependency
- **WHEN** an existing test monkeypatches a supported `forgeagent.cli` class, callback, factory, or helper before invoking a façade entry point
- **THEN** the extracted implementation uses that replacement for the current call and still closes only resources owned by that call

#### Scenario: Early failure has no leaked client
- **WHEN** a CLI or evaluation command returns from preflight, persistence failure, cancellation, or exception
- **THEN** every client and Task created by that command has completed its bounded cleanup before the command returns
