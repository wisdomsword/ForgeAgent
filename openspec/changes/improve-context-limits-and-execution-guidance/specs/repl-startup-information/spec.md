## MODIFIED Requirements

### Requirement: 启动摘要反映实际能力

ForgeAgent SHALL render one compact startup summary after successful interactive initialization containing the selected model, the actual sandbox tier, the resolved project root, the effective round/tool feedback limits, and an MCP availability summary when at least one MCP server is enabled. The feedback values MUST come from the shared current-model limit resolution. When an explicit round or tool value is lower than its current-model adaptive value, ForgeAgent SHALL emit one compact bounded warning containing only the affected field names and numeric configured/adaptive values. A successful `/model` or `/reload` SHALL recompute and display the same limit status. Non-interactive entry points MUST NOT gain startup output. The MCP summary denominator SHALL be the number of servers with `enabled: true` in the startup snapshot; disabled servers SHALL be excluded. The numerator SHALL be the servers that completed startup and are available. A required-server failure SHALL abort before a partial summary is rendered.

#### Scenario: One optional server fails
- **WHEN** two servers are enabled, one available and one optional unavailable
- **THEN** the summary reports `MCP 1/2`, keeps the REPL usable, and emits one compact optional-degradation line

#### Scenario: Disabled server is present
- **WHEN** a configured server is disabled and another enabled server is available
- **THEN** the disabled server is excluded from the startup denominator and does not create an optional-degradation warning

#### Scenario: No MCP server is enabled
- **WHEN** every configured MCP entry is disabled or no MCP configuration exists
- **THEN** the startup summary omits MCP counts and the REPL starts normally

#### Scenario: Adaptive feedback limits are active
- **WHEN** neither feedback limit is explicitly configured
- **THEN** the interactive startup summary displays the effective adaptive round and tool values without a low-value warning

#### Scenario: Explicit low limits are active
- **WHEN** one or both explicit limits are lower than the current model adaptive values
- **THEN** the startup summary displays the actual effective values and one bounded warning identifies each low configured/adaptive pair

#### Scenario: Model command refreshes limits
- **WHEN** an interactive user successfully changes models with `/model`
- **THEN** ForgeAgent recomputes and displays effective/adaptive feedback limits and warnings for the newly selected model

#### Scenario: Reload command refreshes limits
- **WHEN** an interactive user successfully runs `/reload`
- **THEN** ForgeAgent recomputes and displays effective/adaptive feedback limits and warnings from the reloaded configuration and current model

#### Scenario: Non-interactive output remains quiet
- **WHEN** ForgeAgent runs through piped REPL input, `run`, or HTTP
- **THEN** no feedback-limit startup summary or low-value banner is added to stdout or stderr
