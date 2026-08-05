# repl-startup-information Specification

## Purpose
Define deterministic REPL startup diagnostics that expose usable model, sandbox, MCP, and workspace state without leaking secrets.
## Requirements
### Requirement: 交互式启动展示产品标识

ForgeAgent SHALL only in a real interactive REPL (stdin and stdout are TTYs, default reader in use) render a pure ASCII ForgeAgent product mark before the first goal prompt. The full product mark SHALL use five lines of uppercase ASCII lettering, SHALL be no wider than 63 columns, and SHALL keep the `A` apex/crossbar and final `T` top bar/stem visually distinguishable. During initialization the mark SHALL use a bounded low-frequency seven-color animation, SHALL stop deterministically when startup succeeds, fails, or receives process control, and SHALL pause while an interactive confirmation or Survey answer is being read. After successful initialization, ForgeAgent SHALL leave exactly one stable pure ASCII product mark visible in the terminal above the startup summary and first goal prompt.

#### Scenario: Interactive startup reaches ready state with a legible mark

- **WHEN** the default REPL starts with TTY stdin and stdout, the terminal is at least 63 columns wide, and initialization completes
- **THEN** the animation ends, exactly one stable five-line uppercase ASCII ForgeAgent mark no wider than 63 columns remains visible above the startup summary and first goal prompt, and no residual refresh lines are rendered

#### Scenario: Interactive startup requires confirmation

- **WHEN** initialization reaches an identity, Skill, or other confirmation prompt
- **THEN** the Logo renderer pauses before the prompt and resumes or terminates after the answer without corrupting the input line

#### Scenario: Interactive startup is interrupted

- **WHEN** the user presses `Ctrl-C` while the startup renderer is active
- **THEN** the renderer stops in bounded time, no background renderer remains, and the original process-control behavior is preserved

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

### Requirement: 终端能力决定 Logo 降级

ForgeAgent SHALL render the Logo animation only when the interactive startup requirement is met. A `NO_COLOR` or color-disabled terminal SHALL receive a static monochrome mark; a narrow terminal SHALL receive a compact single-line `ForgeAgent` mark; non-TTY, `TERM=dumb`, CI, `run`, and `serve` paths SHALL receive no Logo or ANSI animation.

#### Scenario: Color is disabled
- **WHEN** `NO_COLOR` is set or Rich reports no color system
- **THEN** the interactive user receives a static monochrome mark with no ANSI color sequences

#### Scenario: Terminal is narrow
- **WHEN** the terminal width cannot contain the full ASCII mark
- **THEN** ForgeAgent uses the compact single-line mark without wrapping or corrupting the first prompt

