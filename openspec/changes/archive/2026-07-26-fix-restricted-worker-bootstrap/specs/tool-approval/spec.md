## ADDED Requirements

### Requirement: Restricted worker bootstrap is installation-bound
ForgeAgent MUST launch the restricted execution worker through an interpreter mode that excludes the task working directory, user site-packages and Python path environment overrides from worker module resolution. Files below `allowed_root` MUST NOT replace the installed `forgeagent._sandbox_worker` or its trusted runtime module during bootstrap.

#### Scenario: Task directory shadows the worker package
- **WHEN** `allowed_root` contains a `forgeagent` package with attacker-controlled `_sandbox_worker.py` or `runtime.py`
- **THEN** restricted execution loads the installed ForgeAgent worker and runtime, does not execute either shadow module, and applies the normal audit-hook boundary before executing model code

#### Scenario: Installed worker remains usable
- **WHEN** ForgeAgent runs from its supported installed or editable Python environment with an ordinary project root
- **THEN** restricted execution starts successfully and preserves the existing structured worker protocol
