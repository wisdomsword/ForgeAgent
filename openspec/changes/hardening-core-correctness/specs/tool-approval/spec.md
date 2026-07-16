## ADDED Requirements

### Requirement: Restricted tools use one type-safe confirmation interface
ForgeAgent SHALL allow the CLI confirmer to describe and decide MCP, WebFetch and FileWrite requests without assuming that every request has MCP-specific fields.

#### Scenario: Confirming a WebFetch request
- **WHEN** the confirmer receives `WebFetchArgs`
- **THEN** it presents the request using WebFetch fields and does not raise an attribute or type error

#### Scenario: Confirming a FileWrite request
- **WHEN** the confirmer receives `FileWriteArgs`
- **THEN** it presents the target operation using FileWrite fields and does not raise an attribute or type error

#### Scenario: Confirming an MCP request
- **WHEN** the confirmer receives `MCPArgs`
- **THEN** it presents the server, tool and arguments using MCP fields

### Requirement: Terminal capability controls automatic confirmation
ForgeAgent SHALL attach the generic confirmer to restricted WebFetch, FileWrite and MCP operations independently of whether MCP servers are configured.

#### Scenario: Interactive terminal run
- **WHEN** a restricted tool is requested and the command has interactive TTY input and output
- **THEN** ForgeAgent asks the user to approve or reject the operation before execution

#### Scenario: REPL operation
- **WHEN** a restricted tool is requested from a REPL whose stdin and stdout are both TTYs
- **THEN** ForgeAgent asks for confirmation before execution

#### Scenario: Non-interactive REPL operation
- **WHEN** a restricted tool is requested from a REPL whose stdin or stdout is not a TTY
- **THEN** ForgeAgent rejects the operation without invoking the confirmation input reader

#### Scenario: Non-interactive input
- **WHEN** WebFetch, FileWrite or an MCP call that still requires human confirmation is requested while stdin or stdout is not a TTY
- **THEN** ForgeAgent rejects the operation deterministically without waiting for input and identifies that no interactive confirmation channel is available

#### Scenario: Non-interactive auto-approved MCP call
- **WHEN** an MCP tool is listed in that server's `autoApprove` configuration and stdin or stdout is not a TTY
- **THEN** ForgeAgent treats the explicit configuration as pre-approval and executes without an interactive prompt

### Requirement: Confirmation prompts minimize sensitive exposure
ForgeAgent MUST redact structured secret-key values and known sensitive environment values from confirmation prompts, MUST NOT display FileWrite content, and MUST minimize disclosure of absolute file paths while retaining enough information for the user to identify the target.

#### Scenario: MCP arguments contain nested sensitive keys
- **WHEN** MCP arguments contain values under keys matching the existing secret-name policy at any nesting level
- **THEN** the confirmer replaces those values with a redaction marker and does not print the original values

#### Scenario: MCP argument key contains a known secret
- **WHEN** a mapping key at any MCP argument nesting level contains a known sensitive environment value
- **THEN** the confirmer applies secret-name policy to the original key, masks the displayed key itself, and does not expose the known value through object structure

#### Scenario: MCP identifiers contain a known secret
- **WHEN** an MCP server or tool identifier contains a known sensitive environment value
- **THEN** the confirmer masks the identifier value as well as sensitive argument values

#### Scenario: WebFetch URL contains credentials or sensitive query fields
- **WHEN** a WebFetch URL contains user information, known secret values or query keys matching the existing secret-name policy
- **THEN** the confirmer displays a sanitized URL without the sensitive values

#### Scenario: WebFetch hostname encodes a known secret
- **WHEN** a WebFetch hostname contains a percent-encoded or DNS case-normalized form of a known sensitive environment value
- **THEN** the confirmer decodes the hostname, performs one longest-first non-overlapping ASCII case-insensitive match pass, safely re-encodes the hostname component, and does not display the sensitive value or reinterpret decoded delimiters as URL structure

#### Scenario: WebFetch hostname contains encoded URL delimiters
- **WHEN** a hostname contains percent-encoded `@`, `/`, `?`, `#` or `:` that cannot be represented as the original hostname component
- **THEN** the confirmer returns the fixed malformed-URL summary or safely re-encodes the component without creating userinfo, path, query, fragment or port structure

#### Scenario: WebFetch URL uses IPv6 or a zone identifier
- **WHEN** a WebFetch URL contains an IPv6 literal or percent-encoded zone identifier
- **THEN** the confirmer uses the original bracketed netloc to identify IPv6, preserves valid bracket and zone-id encoding, masks known secret material once, and treats an encoded colon in an unbracketed DNS hostname as malformed

#### Scenario: Multiple URL components contain known secrets
- **WHEN** known secret values appear across hostname, path and query components
- **THEN** hostname matching and global `mask_secrets()` each operate once on their assigned components, and the rebuilt URL is not globally masked a second time

#### Scenario: WebFetch URL contains an unpaired surrogate
- **WHEN** a WebFetch confirmation URL contains an unpaired surrogate in its hostname, path or query
- **THEN** the confirmer returns exactly the fixed ASCII summary `WebFetch <redacted malformed URL>`; it does not apply a generic sanitizer, preserve any URL component, or expose the surrogate or surrounding raw material

#### Scenario: FileWrite uses an absolute path and sensitive content
- **WHEN** FileWrite requests an absolute path and arbitrary content
- **THEN** the confirmer displays a project-relative path when possible or a basename-only external path, displays only the content character count labeled `characters`, and never displays the content

#### Scenario: FileWrite display path contains a known secret
- **WHEN** the project-relative path or external basename contains a known sensitive environment value
- **THEN** the confirmer masks that value in the displayed safe path without revealing the content or host directory

#### Scenario: Confirmation summary contains markup or unsafe display code points
- **WHEN** a model-provided MCP identifier, nested argument mapping key or string value, or FileWrite path contains Rich markup delimiters, ANSI/control characters, carriage returns, line feeds, Unicode line separators, Unicode format controls such as bidi overrides and isolates, or an unpaired surrogate in those non-WebFetch display values
- **THEN** the confirmation prompt renders the value as escaped single-line literal text, does not raise a rendering/encoding exception, change prompt styling, create an injected line or reorder the approval text, and still reads exactly one approval answer

### Requirement: REPL command routing is explicit after compatibility expiry
ForgeAgent SHALL interpret only slash-prefixed REPL inputs as embedded commands after the M9 one-milestone compatibility period, while retaining the top-level `forgeagent models` CLI subcommand.

#### Scenario: Former bare-word aliases are ordinary goals
- **WHEN** a REPL user enters `models`, `reload`, `mcp` or an input beginning with `mcp ` without a leading slash
- **THEN** ForgeAgent sends the complete input to the task loop and does not emit a deprecation notice or invoke an embedded command handler

#### Scenario: Slash commands remain routed
- **WHEN** a REPL user enters `/model`, `/reload` or `/mcp`
- **THEN** ForgeAgent invokes the corresponding embedded command handler without sending that command text to the model

### Requirement: Restricted tool outcomes minimize sensitive exposure
ForgeAgent MUST prevent WebFetch failure outcomes and FileWrite success or failure outcomes from reintroducing raw URLs, hostnames, content or host absolute paths after confirmation.

#### Scenario: WebFetch success reports artifact byte length
- **WHEN** a confirmed WebFetch request saves a response containing multibyte characters after secret masking
- **THEN** the success detail reports `N bytes` where `N` is the actual UTF-8 byte length of the saved, masked artifact, not the Python character count

#### Scenario: WebFetch is blocked by network policy
- **WHEN** a confirmed WebFetch request fails with `SSRFGuardError`
- **THEN** the tool returns the fixed detail `WebFetch blocked by network policy` without the original URL, hostname or exception text

#### Scenario: WebFetch fails at the network layer
- **WHEN** a confirmed WebFetch request fails with `OSError`, `http.client.HTTPException` or an invalid-URL `ValueError`
- **THEN** the tool returns the fixed detail `WebFetch request failed` without the original URL, hostname or exception text

#### Scenario: WebFetch cannot save the fetched response
- **WHEN** a confirmed WebFetch request reads the response successfully but artifact digest/filename derivation, canonical path validation or writing raises `ValueError` or `OSError`, including an unpaired surrogate in a URL fragment that cannot be UTF-8 encoded for the digest
- **THEN** the tool returns the fixed detail `WebFetch response save failed` without the artifact's absolute path or exception text

#### Scenario: WebFetch artifact path is a symlink escape
- **WHEN** the predictable WebFetch artifact file directly below canonical `allowed_root` resolves through a pre-existing symlink outside that canonical root
- **THEN** ForgeAgent rejects the artifact write with `WebFetch response save failed`, leaves the outside target unchanged and does not disclose its path

#### Scenario: FileWrite succeeds with an absolute project path
- **WHEN** a confirmed FileWrite request resolves inside `allowed_root` and succeeds
- **THEN** the tool result identifies the target only by its project-relative path and does not include the model-provided absolute path or content

#### Scenario: FileWrite fails during the write operation
- **WHEN** a confirmed FileWrite request passes project-root validation but the filesystem write raises `OSError`, or the model path raises `ValueError` during validation
- **THEN** the tool returns the fixed detail `FileWrite failed` without the absolute path, content or exception text

### Requirement: File tool path boundaries are root-safe and minimally disclosing
ForgeAgent MUST evaluate canonical WebFetch artifact and file-tool targets with a containment predicate that accepts the root itself and all real descendants, including when `allowed_root` is the filesystem root, and MUST NOT disclose model or host absolute paths in failure outcomes.

This requirement prevents static symlink escape by returning and using the canonical target. It does not claim resistance to a hostile host process that replaces the canonical target itself or one of its ancestor path components between validation and pathname open.

#### Scenario: Filesystem root is the allowed root
- **WHEN** a file tool or restricted audit hook evaluates a target below `allowed_root="/"`
- **THEN** the target is treated as contained instead of being rejected by a doubled-separator prefix check

#### Scenario: A file tool receives an invalid path
- **WHEN** FileRead, FileWrite or FileList receives a syntactically invalid path such as one containing NUL
- **THEN** the tool returns its structured fixed failure outcome and does not propagate `ValueError`

#### Scenario: FileRead or FileList fails on a host path
- **WHEN** FileRead or FileList rejects an out-of-root target or receives a filesystem error whose text contains an absolute path
- **THEN** it returns the fixed detail `FileRead failed` or `FileList failed` without the model path, canonical root or exception text

### Requirement: Survey interaction remains separately controlled
ForgeAgent MUST keep `--interactive` scoped to Survey behavior and SHALL NOT require that flag for automatic TTY confirmation of WebFetch, FileWrite or MCP.

#### Scenario: TTY run without interactive flag
- **WHEN** a terminal user runs a task without `--interactive` and the task requests a restricted non-Survey tool
- **THEN** ForgeAgent still asks for tool confirmation while Survey remains disabled
