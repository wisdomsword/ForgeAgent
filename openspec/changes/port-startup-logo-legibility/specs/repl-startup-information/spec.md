## MODIFIED Requirements

### Requirement: 交互式启动展示产品标识

ForgeAgent SHALL only in a real interactive REPL (stdin and stdout are TTYs, default reader in use) render a pure ASCII ForgeAgent product mark before the first goal prompt. The full product mark SHALL use five lines of uppercase ASCII lettering, SHALL be no wider than 63 columns, and SHALL keep the `A` apex/crossbar and final `T` top bar/stem visually distinguishable. During initialization the mark SHALL use a bounded low-frequency seven-color animation, SHALL stop deterministically when startup succeeds, fails, or receives process control, and SHALL pause while an interactive confirmation or Survey answer is being read. After successful initialization, ForgeAgent SHALL leave exactly one stable pure ASCII product mark visible in the terminal above the startup summary and first goal prompt.

#### Scenario: Interactive startup reaches ready state with a legible mark

- **WHEN** the default REPL starts with TTY stdin and stdout and initialization completes
- **THEN** the animation ends, exactly one stable five-line uppercase ASCII ForgeAgent mark no wider than 63 columns remains visible above the startup summary and first goal prompt, and no residual refresh lines are rendered

#### Scenario: Interactive startup requires confirmation

- **WHEN** initialization reaches an identity, Skill, or other confirmation prompt
- **THEN** the Logo renderer pauses before the prompt and resumes or terminates after the answer without corrupting the input line

#### Scenario: Interactive startup is interrupted

- **WHEN** the user presses `Ctrl-C` while the startup renderer is active
- **THEN** the renderer stops in bounded time, no background renderer remains, and the original process-control behavior is preserved
