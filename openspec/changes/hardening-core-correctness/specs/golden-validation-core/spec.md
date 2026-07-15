## ADDED Requirements

### Requirement: Golden core contains exactly twenty offline scenarios
ForgeAgent SHALL maintain a trusted core manifest containing exactly G01, G03, G05, G06, G08, G11, G13, G14, G15, G17, G27, G43, G58, G59, G324, G329, G330, G332, G333 and G355. Every scenario SHALL execute offline with local fixtures and without network access, Docker, vendor credentials or user configuration. Agent-loop scenarios SHALL use MockClient; boundary scenarios MAY directly exercise CLI, Tool, RestrictedBackend, guarded URL or local stdio MCP fixtures.

#### Scenario: Base CI runs the golden core
- **WHEN** the golden core command runs in an isolated environment with no network or model credentials
- **THEN** all 20 scenarios execute and each produces an automatic pass or fail result

#### Scenario: Standalone offline entry ignores user configuration before imports
- **WHEN** the standalone golden command is launched with a parent home containing a hostile `.forgeagent/mcp.yaml`
- **THEN** it installs a temporary HOME, USERPROFILE and XDG_CONFIG_HOME before importing manifest, cases, CLI, MCP or model configuration modules and executes without reading the hostile file

#### Scenario: Offline entry restores process environment
- **WHEN** offline `main()` returns normally or a runner failure exits through its cleanup path in the same process
- **THEN** HOME, USERPROFILE and XDG_CONFIG_HOME are restored to their exact prior value or unset state

#### Scenario: Manifest selection is validated
- **WHEN** the golden runner performs preflight validation
- **THEN** it rejects duplicate, missing, additional or substituted core or catalog scenario IDs before executing the suite

#### Scenario: Core IDs remain defined in the candidate catalog
- **WHEN** automated documentation consistency tests inspect the trusted-core manifest and `docs/golden-tasks-seed.md`
- **THEN** every manifest ID has a corresponding task definition in the candidate catalog

### Requirement: Golden catalog has one exact ID universe
The candidate catalog SHALL contain each and only each ID from `G01` through `G380`, inclusive. The trusted core SHALL be the exact 20-ID set above; its complement SHALL contain exactly 360 non-core candidates. Validation MUST reject duplicate, missing, additional or substituted catalog IDs before any claim about core or candidate counts.

#### Scenario: Candidate ID universe is exact
- **WHEN** catalog consistency validation reads the candidate documentation and trusted-core manifest
- **THEN** it accepts only the unique inclusive `G01` through `G380` universe, exactly 20 core IDs and exactly 360 non-core IDs

### Requirement: Golden scenarios are machine judged and reported
The golden runner MUST validate declared expectations for each scenario and SHALL emit both machine-readable results and a human-readable summary containing counts and pass rate.

#### Scenario: All expectations pass
- **WHEN** every scenario satisfies its declared outcome
- **THEN** the runner reports 20 passed, 0 failed and a 100 percent pass rate with a successful process exit

#### Scenario: One expectation fails
- **WHEN** any scenario violates its declared outcome
- **THEN** the runner identifies the scenario and failed expectation, reports a reduced pass rate and exits non-zero

#### Scenario: Catalog pass criteria has multiple observable conditions
- **WHEN** a trusted-core catalog entry requires runtime instrumentation, unchanged fixture hashes, an Edit version chain, AST validity or exact structured output in addition to a final value or passing test
- **THEN** that scenario's judge checks every declared observable condition and fails when any one is missing, so a hard-coded result or whole-block replacement cannot produce a false pass

#### Scenario: Scenario returns invalid report evidence
- **WHEN** a scenario returns evidence containing a tuple, non-string mapping key, non-JSON object, subclass of an otherwise allowed built-in scalar/container, or non-finite number
- **THEN** the runner rejects it without coercing keys or container types, records that scenario as failed with fixed serializable evidence, continues the remaining scenarios, and still emits complete JSON and Markdown reports instead of failing during final serialization

#### Scenario: Real-model identifier contains path syntax
- **WHEN** the selected configured model identifier contains separators, dot segments, Unicode or punctuation
- **THEN** the default real-model report directory is derived from a bounded ASCII slug plus a digest of the original identifier, remains under `artifacts/golden/real`, and cannot collide solely because unsafe characters were normalized

### Requirement: Five core scenarios support opt-in real-model execution
Exactly G01, G03, G08, G11 and G43 SHALL be tagged as compatible with an explicitly configured real model, and real-model execution MUST remain opt-in and outside the base CI gate.

#### Scenario: No real-model option is supplied
- **WHEN** the base golden command runs without a real-model selection
- **THEN** Agent-loop scenarios use MockClient, direct boundary scenarios use only local fixtures, and no external model request is made

#### Scenario: Real-model execution is requested
- **WHEN** a user supplies the explicit real-model command and valid model configuration
- **THEN** the runner preserves the caller's HOME, USERPROFILE and XDG_CONFIG_HOME while resolving user model configuration and credentials, executes only the 5 compatible scenarios, and produces a separate pass-rate report

#### Scenario: Real-model preflight lacks configuration or credentials
- **WHEN** a user explicitly requests real-model execution but the selected model cannot be resolved or its required local credential is unavailable
- **THEN** the runner exits with status 2 before executing scenarios and does not generate a pass-rate report

### Requirement: Candidate catalog is not presented as validated
ForgeAgent documentation SHALL distinguish the 20 executable trusted-core scenarios from the remaining candidate task catalog and MUST NOT describe candidates as validated without executable evidence.

#### Scenario: User reads golden task documentation
- **WHEN** documentation lists the wider task catalog
- **THEN** it labels exactly 20 scenarios as executable trusted core and exactly 360 other IDs in the `G01` through `G380` universe as non-core candidates

### Requirement: Public protocol documentation matches runtime behavior
The milestone SHALL update model-client, text-protocol, threat-model, README and milestone documentation so claims about streaming, multimodal input, WebFetch/File tools, proxy behavior and golden validation match the verified implementation.

#### Scenario: Documentation is reviewed after implementation
- **WHEN** the change is ready for verification
- **THEN** affected documents no longer contradict supported runtime contracts or claim unexecuted validation
